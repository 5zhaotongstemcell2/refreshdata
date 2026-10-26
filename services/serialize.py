"""把 Pandas / NumPy 值转换为可 JSON 序列化的结构。"""
from __future__ import annotations

import math
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd


def json_value(value: Any) -> Any:
    if value is None or value is pd.NaT or value is pd.NA:
        return None

    if isinstance(value, (pd.Timestamp, datetime)):
        if not pd.isna(value):
            if value.time() == time(0, 0):
                return value.strftime("%Y-%m-%d")
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return None

    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value

    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_value(item) for item in value]

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, (str, bytes)):
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    return str(value)


def friendly_type(series: pd.Series) -> str:
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "布尔"
    if pd.api.types.is_integer_dtype(dtype):
        return "整数"
    if pd.api.types.is_float_dtype(dtype):
        return "小数"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "日期时间"
    if pd.api.types.is_numeric_dtype(dtype):
        return "数值"
    return "文本"


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def column_profile(df: pd.DataFrame) -> list[dict[str, Any]]:
    """字段统计：非空、缺失、均值、最值等。"""
    total = len(df)
    profiles: list[dict[str, Any]] = []

    for column in df.columns:
        series = df[column]
        non_null = int(series.notna().sum())
        missing = total - non_null
        item: dict[str, Any] = {
            "name": str(column),
            "dtype": str(series.dtype),
            "type": friendly_type(series),
            "numeric": bool(pd.api.types.is_numeric_dtype(series))
            and not bool(pd.api.types.is_bool_dtype(series)),
            "datetime": bool(pd.api.types.is_datetime64_any_dtype(series)),
            "total": total,
            "non_null": non_null,
            "missing": missing,
            "missing_ratio": round(missing * 100.0 / total, 1) if total else 0.0,
            "unique": int(series.nunique(dropna=True)),
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "top": None,
            "top_count": None,
        }

        if item["numeric"]:
            numeric = pd.to_numeric(series, errors="coerce")
            item["mean"] = _round(numeric.mean())
            item["median"] = _round(numeric.median())
            item["std"] = _round(numeric.std()) if non_null > 1 else None
            item["min"] = json_value(numeric.min())
            item["max"] = json_value(numeric.max())
        elif item["datetime"]:
            item["min"] = json_value(series.min())
            item["max"] = json_value(series.max())
        elif non_null:
            counts = series.value_counts(dropna=True)
            if len(counts):
                item["top"] = json_value(counts.index[0])
                item["top_count"] = int(counts.iloc[0])

        profiles.append(item)

    return profiles


def dataframe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [str(column) for column in df.columns]
    records: list[dict[str, Any]] = []
    for row in df.itertuples(index=False, name=None):
        records.append({columns[index]: json_value(value) for index, value in enumerate(row)})
    return records


def column_meta(df: pd.DataFrame) -> list[dict[str, Any]]:
    columns = []
    for name in df.columns:
        series = df[name]
        columns.append(
            {
                "name": str(name),
                "dtype": str(series.dtype),
                "type": friendly_type(series),
                "numeric": bool(pd.api.types.is_numeric_dtype(series))
                and not bool(pd.api.types.is_bool_dtype(series)),
                "datetime": bool(pd.api.types.is_datetime64_any_dtype(series)),
                "missing": int(series.isna().sum()),
            }
        )
    return columns
