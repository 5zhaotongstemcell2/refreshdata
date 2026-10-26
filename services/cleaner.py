"""数据清洗：去重、空值填充、删除列、类型转换。"""
from __future__ import annotations

from typing import Any

import pandas as pd

TARGET_LABELS = {
    "int": "整数",
    "float": "小数",
    "text": "文本",
    "datetime": "日期时间",
}

METHOD_LABELS = {
    "zero": "0",
    "mean": "平均值",
    "median": "中位数",
    "mode": "众数",
    "custom": "自定义值",
}


class CleanError(ValueError):
    """清洗操作不合法。"""


def _as_columns(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return []


def _is_numeric(series: pd.Series) -> bool:
    return bool(pd.api.types.is_numeric_dtype(series)) and not bool(
        pd.api.types.is_bool_dtype(series)
    )


def _numeric_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        text = series.astype("string").str.replace(",", "", regex=False).str.strip()
        return pd.to_numeric(text, errors="coerce")
    return pd.to_numeric(series, errors="coerce")


def _custom_value(series: pd.Series, raw: Any) -> Any:
    if raw is None or str(raw).strip() == "":
        raise CleanError("请填写自定义填充值。")
    if _is_numeric(series):
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise CleanError("该列是数值列，自定义填充值必须是数字。") from exc
        return int(number) if number.is_integer() else number
    if pd.api.types.is_datetime64_any_dtype(series):
        try:
            return pd.to_datetime(raw, errors="raise")
        except (TypeError, ValueError) as exc:
            raise CleanError("该列是日期列，请填写有效的日期。") from exc
    return str(raw)


def _dedup(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    subset = _as_columns(params.get("subset")) or None
    if subset:
        missing = [column for column in subset if column not in df.columns]
        if missing:
            raise CleanError(f"字段「{'、'.join(missing)}」不存在。")
    before = len(df)
    result = df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
    removed = before - len(result)
    return result, {
        "changed": removed > 0,
        "message": f"已删除 {removed} 行重复数据。" if removed else "没有发现重复数据。",
        "label": f"去重（删除 {removed} 行）",
        "log_type": "去重",
        "detail": {
            "removed": removed,
            "subset": subset or "全部列",
            "rows_before": before,
            "rows_after": len(result),
        },
    }


def _fillna(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = _as_columns(params.get("columns"))
    if not columns:
        columns = [str(column) for column in df.columns if df[column].isna().any()]
    if not columns:
        return df, {
            "changed": False,
            "message": "所有字段都没有缺失值，无需填充。",
            "label": "空值填充",
            "log_type": "填充",
            "detail": {},
        }

    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise CleanError(f"字段「{'、'.join(missing)}」不存在。")

    method = str(params.get("method") or "zero")
    if method not in METHOD_LABELS:
        raise CleanError("不支持的空值填充方式。")

    result = df.copy()
    filled: dict[str, int] = {}
    fill_values: dict[str, Any] = {}

    for column in columns:
        series = result[column]
        missing_count = int(series.isna().sum())
        if not missing_count:
            continue

        if method == "zero":
            if pd.api.types.is_datetime64_any_dtype(series):
                raise CleanError(f"字段「{column}」是日期列，不能用 0 填充，请选择众数或自定义值。")
            fill_value: Any = 0 if _is_numeric(series) else "0"
        elif method in {"mean", "median"}:
            if not _is_numeric(series):
                raise CleanError(
                    f"字段「{column}」不是数值类型，无法用{METHOD_LABELS[method]}填充。"
                )
            numeric = _numeric_series(series)
            fill_value = numeric.mean() if method == "mean" else numeric.median()
            if pd.isna(fill_value):
                raise CleanError(f"字段「{column}」没有可用于计算{METHOD_LABELS[method]}的数据。")
            # Int64 等可空整数列无法直接写入小数，先转为浮点列
            if pd.api.types.is_integer_dtype(series):
                series = series.astype("float64")
                result[column] = series
        elif method == "mode":
            modes = series.mode(dropna=True)
            if modes.empty:
                raise CleanError(f"字段「{column}」没有可用于计算众数的数据。")
            fill_value = modes.iloc[0]
        else:
            fill_value = _custom_value(series, params.get("value"))

        if pd.api.types.is_integer_dtype(series) and isinstance(fill_value, float):
            if not fill_value.is_integer():
                series = series.astype("float64")
                result[column] = series

        result[column] = series.fillna(fill_value)
        filled[column] = missing_count
        fill_values[column] = fill_value

    total = sum(filled.values())
    changed = total > 0
    method_text = METHOD_LABELS[method]
    if method == "custom":
        method_text = f"自定义值「{params.get('value')}」"
    message = (
        f"已使用{method_text}填充 {total} 个空值（{len(filled)} 个字段）。"
        if changed
        else "所选字段没有缺失值，无需填充。"
    )
    return result, {
        "changed": changed,
        "message": message,
        "label": f"空值填充（{total} 个）",
        "log_type": "填充",
        "detail": {
            "columns": list(filled.keys()),
            "method": method,
            "method_label": method_text,
            "filled": total,
            "details": filled,
            "rows": len(result),
        },
    }


def _drop_columns(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = _as_columns(params.get("columns"))
    if not columns:
        raise CleanError("请至少选择一个要删除的字段。")
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise CleanError(f"字段「{'、'.join(missing)}」不存在。")
    if len(set(columns)) >= len(df.columns):
        raise CleanError("不能删除全部字段，请至少保留一列。")
    result = df.drop(columns=columns)
    return result, {
        "changed": True,
        "message": f"已删除 {len(columns)} 个字段：{'、'.join(columns)}。",
        "label": f"删除字段（{len(columns)} 个）",
        "log_type": "删除列",
        "detail": {
            "columns": columns,
            "remaining": len(result.columns),
            "rows": len(result),
        },
    }


def _convert(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    column = str(params.get("column") or "").strip()
    if not column:
        raise CleanError("请选择要转换的字段。")
    if column not in df.columns:
        raise CleanError(f"字段「{column}」不存在。")
    target = str(params.get("target") or "").strip()
    if target not in TARGET_LABELS:
        raise CleanError("不支持的目标类型。")
    on_error = str(params.get("on_error") or "coerce")
    if on_error not in {"coerce", "raise"}:
        on_error = "coerce"

    result = df.copy()
    series = result[column]
    original_non_null = series.notna()
    failed = 0
    note = ""

    if target in {"int", "float"}:
        numeric = _numeric_series(series)
        invalid = numeric.isna() & original_non_null
        failed = int(invalid.sum())
        if target == "int":
            fractional = numeric.notna() & (numeric % 1 != 0)
            fractional_count = int(fractional.sum())
            if fractional_count:
                if on_error == "raise":
                    raise CleanError(f"字段「{column}」有 {fractional_count} 个小数，无法转为整数。")
                numeric = numeric.where(numeric.isna() | (numeric % 1 == 0))
                failed += fractional_count
                note = f"，{fractional_count} 个小数已置空"
            if on_error == "raise" and failed:
                raise CleanError(f"字段「{column}」有 {failed} 个值无法转换为整数。")
            if numeric.isna().any():
                converted = numeric.astype("Int64")
            else:
                converted = numeric.astype("int64")
        else:
            if on_error == "raise" and failed:
                raise CleanError(f"字段「{column}」有 {failed} 个值无法转换为小数。")
            converted = numeric.astype("float64")
    elif target == "text":
        converted = series.astype("string")
    else:
        fmt = str(params.get("format") or "").strip()
        try:
            if fmt:
                converted = pd.to_datetime(series, format=fmt, errors="coerce")
            else:
                converted = pd.to_datetime(series, errors="coerce", format="mixed")
        except (TypeError, ValueError):
            converted = pd.to_datetime(series, errors="coerce")
        invalid = converted.isna() & original_non_null
        failed = int(invalid.sum())
        if on_error == "raise" and failed:
            raise CleanError(f"字段「{column}」有 {failed} 个值无法转换为日期时间。")
        fmt_note = f"（格式 {fmt}）" if fmt else ""
        note = fmt_note

    result[column] = converted
    if failed:
        message = (
            f"字段「{column}」已转换为{TARGET_LABELS[target]}，"
            f"其中 {failed} 个无法转换的值已置空{note}。"
        )
    else:
        message = f"字段「{column}」已转换为{TARGET_LABELS[target]}{note}。"
    return result, {
        "changed": True,
        "message": message,
        "label": f"类型转换（{column} → {TARGET_LABELS[target]}）",
        "log_type": "类型转换",
        "detail": {
            "column": column,
            "target": target,
            "target_label": TARGET_LABELS[target],
            "failed": failed,
            "on_error": on_error,
            "rows": len(result),
        },
    }


def apply_clean(
    df: pd.DataFrame, action: str, params: dict[str, Any] | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    params = params or {}
    if action == "dedup":
        return _dedup(df, params)
    if action == "fillna":
        return _fillna(df, params)
    if action == "drop_columns":
        return _drop_columns(df, params)
    if action == "convert":
        return _convert(df, params)
    raise CleanError("不支持的清洗操作。")
