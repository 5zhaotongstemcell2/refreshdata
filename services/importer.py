"""文件导入：编码识别、Sheet 读取、字段类型推断。"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config
from services.serialize import dataframe_records, friendly_type, json_value

UTF8_BOM = b"\xef\xbb\xbf"
UTF16_LE_BOM = b"\xff\xfe"
UTF16_BE_BOM = b"\xfe\xff"

_ENCODING_ALIASES = {
    "utf_8": "utf-8",
    "utf8": "utf-8",
    "utf_8_sig": "utf-8-sig",
    "ascii": "utf-8",
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "gb18030": "gb18030",
    "big5": "big5",
    "cp950": "big5",
    "cp1252": "cp1252",
    "windows-1252": "cp1252",
    "latin_1": "latin-1",
    "latin1": "latin-1",
}

_ID_LIKE_NAME = re.compile(
    r"(电话|手机|号码|编号|工号|身份证|邮编|编码|代码|单号|订单号|id)$", re.IGNORECASE
)
_DATE_LIKE = re.compile(
    r"^\s*\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?"
    r"(?:[ T].*)?\s*$|^\s*\d{1,2}:\d{2}(?::\d{2})?\s*$"
)
_LEADING_ZERO = re.compile(r"^[+-]?0\d")


class ImportErrorDetail(Exception):
    """给用户看的导入错误。"""


def _decode_sample(sample: bytes, encoding: str) -> str | None:
    try:
        return sample.decode(encoding, errors="strict")
    except (UnicodeDecodeError, LookupError):
        return None


def _text_score(text: str) -> float:
    if not text:
        return -10.0
    length = len(text)
    replacement = text.count("\ufffd")
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\r\n\t")
    han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    hangul = sum(1 for ch in text if "\uac00" <= ch <= "\ud7af")
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
    return (
        (printable / length) * 2.0
        + (han / length) * 3.0
        - (replacement / length) * 8.0
        - (control / length) * 6.0
        - ((hangul + cyrillic) / length) * 2.5
    )


def detect_encoding(raw: bytes) -> dict[str, Any]:
    """识别文本编码，返回 encoding / confidence / source。"""
    if raw.startswith(UTF8_BOM):
        return {"encoding": "utf-8-sig", "confidence": 1.0, "source": "UTF-8 BOM"}
    if raw.startswith(UTF16_LE_BOM) or raw.startswith(UTF16_BE_BOM):
        return {
            "encoding": "utf-16",
            "confidence": 1.0,
            "source": "UTF-16 BOM",
        }

    sample = raw[:262_144]
    try:
        sample.decode("utf-8")
        return {"encoding": "utf-8", "confidence": 1.0, "source": "UTF-8 校验通过"}
    except UnicodeDecodeError:
        pass

    candidates: list[tuple[str, float, str]] = []

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(sample).best()
        if best is not None and best.encoding:
            raw_name = best.encoding.lower().replace("-", "_")
            name = _ENCODING_ALIASES.get(raw_name, raw_name.replace("_", "-"))
            decoded = _decode_sample(sample, name)
            if decoded is not None:
                coherence = float(getattr(best, "percent_coherence", 0.0) or 0.0) / 100.0
                candidates.append((name, coherence, "charset-normalizer"))
    except Exception:  # noqa: BLE001 - 编码探测失败时继续走回退列表
        pass

    for name in ("gb18030", "big5", "cp1252"):
        if any(item[0] == name for item in candidates):
            continue
        decoded = _decode_sample(sample, name)
        if decoded is not None:
            candidates.append((name, 0.0, "回退尝试"))

    if not candidates:
        return {"encoding": "latin-1", "confidence": 0.2, "source": "最终回退"}

    scored = []
    for name, confidence, source in candidates:
        decoded = _decode_sample(sample, name) or ""
        score = _text_score(decoded) + confidence
        scored.append((score, name, confidence, source))
    scored.sort(key=lambda item: item[0], reverse=True)

    best_score, best_name, best_conf, best_source = scored[0]
    return {
        "encoding": best_name,
        "confidence": round(min(1.0, max(0.2, best_conf if best_conf > 0 else 0.5)), 2),
        "source": best_source,
    }


def detect_delimiter(text: str) -> str:
    lines = [line for line in text.splitlines()[:30] if line.strip()]
    if not lines:
        return ","
    sample = "\n".join(lines)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        if dialect.delimiter in {",", ";", "\t", "|"}:
            return dialect.delimiter
    except csv.Error:
        pass

    best_delimiter = ","
    best_score = -1.0
    for delimiter in (",", ";", "\t", "|"):
        counts = [line.count(delimiter) for line in lines]
        if not counts or max(counts) == 0:
            continue
        most_common = max(set(counts), key=counts.count)
        if most_common == 0:
            continue
        consistency = counts.count(most_common) / len(counts)
        score = consistency * math.log1p(most_common)
        if score > best_score:
            best_score = score
            best_delimiter = delimiter
    return best_delimiter


def _normalize_options(options: dict[str, Any] | None) -> dict[str, Any]:
    options = options or {}
    has_header = options.get("has_header", True)
    if isinstance(has_header, str):
        has_header = has_header.lower() not in {"0", "false", "no", "off"}
    try:
        header_row = int(options.get("header_row") or 1)
    except (TypeError, ValueError):
        header_row = 1
    header_row = max(1, min(50, header_row))
    encoding = str(options.get("encoding") or "auto").strip() or "auto"
    delimiter = str(options.get("delimiter") or "auto")
    if delimiter == "auto":
        delimiter = ","
    sheet = options.get("sheet")
    if sheet is not None:
        sheet = str(sheet)
    return {
        "has_header": bool(has_header),
        "header_row": header_row,
        "encoding": encoding,
        "delimiter": delimiter,
        "sheet": sheet,
    }


def _read_sample(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read()


def _resolve_encoding(path: Path, requested: str) -> tuple[str, dict[str, Any]]:
    detected = detect_encoding(_read_sample(path)[:262_144])
    if requested and requested != "auto":
        return requested, detected
    return detected["encoding"], detected


def _excel_sheets(path: Path) -> list[str]:
    try:
        with pd.ExcelFile(path, engine="openpyxl") as workbook:
            return [str(name) for name in workbook.sheet_names]
    except Exception as exc:  # noqa: BLE001
        raise ImportErrorDetail(f"无法读取 Excel 文件：{exc}") from exc


def _read_csv(path: Path, encoding: str, delimiter: str, header: int | None, nrows: int | None) -> pd.DataFrame:
    kwargs: dict[str, Any] = {
        "encoding": encoding,
        "sep": delimiter,
        "header": header,
        "dtype": str,
        "nrows": nrows,
        "skip_blank_lines": True,
        "keep_default_na": True,
    }
    try:
        return pd.read_csv(path, **kwargs)
    except UnicodeDecodeError as exc:
        raise ImportErrorDetail(
            "按所选编码无法解码文件，请在上方切换编码后重试。"
        ) from exc
    except pd.errors.EmptyDataError as exc:
        raise ImportErrorDetail("文件内容为空，或分隔符选择不正确。") from exc
    except pd.errors.ParserError:
        kwargs.update({"engine": "python", "on_bad_lines": "skip"})
        try:
            return pd.read_csv(path, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ImportErrorDetail(f"CSV 解析失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ImportErrorDetail(f"CSV 读取失败：{exc}") from exc


def _read_excel(
    path: Path, sheet: str | None, header: int | None, nrows: int | None
) -> pd.DataFrame:
    try:
        return pd.read_excel(
            path,
            sheet_name=sheet if sheet else 0,
            header=header,
            dtype=object,
            nrows=nrows,
            engine="openpyxl",
        )
    except ValueError as exc:
        raise ImportErrorDetail(f"工作表不存在或无法读取：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ImportErrorDetail(f"Excel 读取失败：{exc}") from exc


def read_table(
    path: Path,
    kind: str,
    options: dict[str, Any] | None,
    nrows: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    opts = _normalize_options(options)
    header = opts["header_row"] - 1 if opts["has_header"] else None

    encoding = opts["encoding"]
    delimiter = opts["delimiter"]
    detected: dict[str, Any] = {}

    if kind == "csv":
        encoding, detected = _resolve_encoding(path, encoding)
        if delimiter == "," and (options or {}).get("delimiter", "auto") == "auto":
            sample = _read_sample(path)[:131_072]
            text = _decode_sample(sample, encoding) or ""
            delimiter = detect_delimiter(text)
        frame = _read_csv(path, encoding, delimiter, header, nrows)
    elif kind == "xlsx":
        frame = _read_excel(path, opts["sheet"], header, nrows)
    else:
        raise ImportErrorDetail("仅支持 .csv 与 .xlsx 文件。")

    frame = _normalize_dataframe(frame)
    info = {
        "encoding": encoding if kind == "csv" else None,
        "encoding_detected": detected.get("encoding"),
        "encoding_source": detected.get("source"),
        "delimiter": delimiter if kind == "csv" else None,
        "sheet": opts["sheet"],
        "header_row": opts["header_row"] if opts["has_header"] else 0,
        "has_header": opts["has_header"],
    }
    return frame, info


def _unique_column_names(columns: list[Any]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for index, raw in enumerate(columns):
        name = str(raw).strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"列{index + 1}"
        name = re.sub(r"\s+", " ", name)
        base = name
        suffix = 2
        while name in seen:
            name = f"{base}_{suffix}"
            suffix += 1
        seen.add(name)
        names.append(name)
    return names


def _is_numeric_like(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def _finalize_numeric(series: pd.Series) -> pd.Series:
    """整数值的数值列使用整数类型，展示更符合业务直觉。"""
    converted = pd.to_numeric(series, errors="coerce")
    non_null = converted.dropna()
    if not len(non_null):
        return converted
    try:
        finite = np.isfinite(non_null.astype("float64")).all()
        integral = bool((non_null % 1 == 0).all())
    except (TypeError, ValueError):
        return converted
    if not finite or not integral:
        return converted
    try:
        return converted.astype("Int64") if converted.isna().any() else converted.astype("int64")
    except (TypeError, ValueError, OverflowError):
        return converted


def coerce_series(series: pd.Series, column_name: str = "") -> pd.Series:
    """把一列尽量转换为数值/日期/文本。保留前导零与编号类字段。"""
    if pd.api.types.is_bool_dtype(series):
        return series

    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    if pd.api.types.is_numeric_dtype(series):
        return _finalize_numeric(series)

    if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
        return series

    non_null = series.dropna()
    if non_null.empty:
        return series.astype("string")

    sample = list(non_null.head(50))
    if sample and all(isinstance(value, (datetime, date, pd.Timestamp)) for value in sample):
        return pd.to_datetime(series, errors="coerce")

    if sample and all(_is_numeric_like(value) for value in sample):
        return _finalize_numeric(series)

    strings = series.astype("string").str.strip()
    non_empty = strings.dropna()
    non_empty = non_empty[non_empty != ""]
    if non_empty.empty:
        return strings.mask(strings == "", pd.NA)

    numeric = pd.to_numeric(non_empty.str.replace(",", "", regex=False), errors="coerce")
    numeric_ratio = float(numeric.notna().mean())
    leading_zero = bool(non_empty.str.match(_LEADING_ZERO).any())
    id_like = bool(_ID_LIKE_NAME.search(column_name or ""))

    if numeric_ratio >= 0.95 and not leading_zero and not id_like:
        converted = pd.to_numeric(strings.str.replace(",", "", regex=False), errors="coerce")
        # 超长数字串容易被误当成数值，保留为文本更安全
        if not any(len(value) > 15 for value in non_empty.head(100)):
            return _finalize_numeric(converted)

    date_like = non_empty.str.match(_DATE_LIKE)
    if float(date_like.mean()) >= 0.6:
        parsed = None
        for kwargs in ({"format": "mixed"}, {}):
            try:
                candidate = pd.to_datetime(strings, errors="coerce", **kwargs)
            except (TypeError, ValueError):
                continue
            if float(candidate.notna().sum()) / max(1, len(non_empty)) >= 0.9:
                parsed = candidate
                break
        if parsed is not None:
            return parsed

    return strings.mask(strings == "", pd.NA)


def _normalize_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.dropna(how="all").copy()
    if frame.empty and len(frame.columns) == 0:
        raise ImportErrorDetail("没有读取到任何数据，请检查表头行与分隔符设置。")

    frame.columns = _unique_column_names(list(frame.columns))
    for column in frame.columns:
        frame[column] = coerce_series(frame[column], column)
    return frame.reset_index(drop=True)


def _column_brief(frame: pd.DataFrame) -> list[dict[str, Any]]:
    result = []
    for column in frame.columns:
        series = frame[column]
        result.append(
            {
                "name": str(column),
                "dtype": str(series.dtype),
                "type": friendly_type(series),
                "missing": int(series.isna().sum()),
            }
        )
    return result


def inspect_file(path: Path, file_name: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    kind = "csv" if suffix == ".csv" else "xlsx" if suffix == ".xlsx" else ""
    if not kind:
        raise ImportErrorDetail("仅支持 .csv 与 .xlsx 文件。")

    size = path.stat().st_size
    sheets: list[str] = []
    options: dict[str, Any] = {"has_header": True, "header_row": 1, "encoding": "auto"}

    if kind == "xlsx":
        sheets = _excel_sheets(path)
        if not sheets:
            raise ImportErrorDetail("Excel 文件里没有工作表。")
        options["sheet"] = sheets[0]
        options["encoding"] = "auto"
    else:
        with path.open("rb") as handle:
            sample = handle.read(262_144)
        detected = detect_encoding(sample)
        text = _decode_sample(sample, detected["encoding"]) or ""
        options["encoding"] = detected["encoding"]
        options["delimiter"] = detect_delimiter(text)

    preview_frame, info = read_table(path, kind, options, nrows=50)
    preview_records = dataframe_records(preview_frame.head(config.PREVIEW_ROWS))
    warnings: list[str] = []
    if kind == "csv" and info["encoding"] != "utf-8":
        warnings.append(f"文件编码识别为 {info['encoding']}。")
    if kind == "xlsx" and len(sheets) > 1:
        warnings.append(f"该文件有 {len(sheets)} 个工作表，请选择需要导入的工作表。")

    return {
        "file_name": file_name,
        "kind": kind,
        "size": size,
        "sheets": sheets,
        "sheet": options.get("sheet"),
        "encoding": options.get("encoding"),
        "encoding_detected": info.get("encoding_detected"),
        "encoding_source": info.get("encoding_source"),
        "delimiter": options.get("delimiter"),
        "has_header": True,
        "header_row": 1,
        "columns": _column_brief(preview_frame),
        "preview": preview_records,
        "preview_columns": [str(column) for column in preview_frame.columns],
        "warnings": warnings,
    }


def preview_with_options(
    path: Path, kind: str, options: dict[str, Any] | None
) -> dict[str, Any]:
    frame, info = read_table(path, kind, options, nrows=50)
    return {
        "columns": _column_brief(frame),
        "preview": dataframe_records(frame.head(config.PREVIEW_ROWS)),
        "preview_columns": [str(column) for column in frame.columns],
        "encoding": info.get("encoding"),
        "delimiter": info.get("delimiter"),
        "sheet": info.get("sheet"),
        "warnings": [],
    }


def import_file(
    path: Path, kind: str, options: dict[str, Any] | None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, info = read_table(path, kind, options)
    warnings: list[str] = []
    if len(frame) > config.MAX_ROWS:
        frame = frame.head(config.MAX_ROWS).reset_index(drop=True)
        warnings.append(f"数据超过 {config.MAX_ROWS:,} 行，已截取前 {config.MAX_ROWS:,} 行。")
    if frame.empty:
        raise ImportErrorDetail("数据为空，无法导入。")
    info["rows"] = int(len(frame))
    info["columns"] = int(len(frame.columns))
    info["warnings"] = warnings
    info["missing_cells"] = int(frame.isna().sum().sum())
    return frame, info


def preview_value(value: Any) -> Any:
    """供模板/调试使用的值格式化。"""
    return json_value(value)
