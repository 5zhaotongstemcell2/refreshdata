"""筛选与多列排序。"""
from __future__ import annotations

from typing import Any

import pandas as pd

OPERATOR_LABELS = {
    "contains": "包含",
    "not_contains": "不包含",
    "eq": "等于",
    "ne": "不等于",
    "gt": "大于",
    "gte": "大于等于",
    "lt": "小于",
    "lte": "小于等于",
    "between": "介于",
    "is_null": "为空",
    "not_null": "不为空",
}

TEXT_OPERATORS = ["contains", "not_contains", "eq", "ne", "is_null", "not_null"]
ORDERED_OPERATORS = ["eq", "ne", "gt", "gte", "lt", "lte", "between", "is_null", "not_null"]
NO_VALUE_OPERATORS = {"is_null", "not_null"}


class FilterError(ValueError):
    """筛选条件不合法。"""


def column_kind(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "text"


def operators_for(series: pd.Series) -> list[str]:
    return ORDERED_OPERATORS if column_kind(series) in {"number", "datetime"} else TEXT_OPERATORS


def _parse_value(series: pd.Series, raw: Any) -> Any:
    kind = column_kind(series)
    if isinstance(raw, str):
        raw = raw.strip()
    if raw is None or raw == "":
        raise FilterError("请填写筛选值。")
    if kind == "number":
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise FilterError(f"「{series.name}」是数值列，筛选值必须是数字。") from exc
    if kind == "datetime":
        try:
            parsed = pd.to_datetime(raw, errors="raise")
        except (TypeError, ValueError) as exc:
            raise FilterError(f"「{series.name}」是日期列，请填写有效的日期。") from exc
        # 元数据写入 JSON，日期统一保存为字符串
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return str(raw)


def normalize_filters(
    df: pd.DataFrame, filters: Any, logic: Any
) -> tuple[list[dict[str, Any]], str]:
    logic = str(logic or "AND").upper()
    if logic not in {"AND", "OR"}:
        logic = "AND"
    if filters is None:
        return [], logic
    if not isinstance(filters, list):
        raise FilterError("筛选条件格式不正确。")
    if len(filters) > 20:
        raise FilterError("最多支持 20 个筛选条件。")

    normalized: list[dict[str, Any]] = []
    for item in filters:
        if not isinstance(item, dict):
            raise FilterError("筛选条件格式不正确。")
        column = str(item.get("column") or "").strip()
        if not column:
            continue
        if column not in df.columns:
            raise FilterError(f"字段「{column}」不存在。")
        operator = str(item.get("op") or "").strip()
        if operator not in OPERATOR_LABELS:
            raise FilterError("不支持的筛选方式。")
        series = df[column]
        allowed = set(operators_for(series))
        if operator not in allowed:
            raise FilterError(f"字段「{column}」不支持「{OPERATOR_LABELS[operator]}」筛选。")

        entry: dict[str, Any] = {"column": column, "op": operator, "value": None, "value2": None}
        if operator not in NO_VALUE_OPERATORS:
            entry["value"] = _parse_value(series, item.get("value"))
            if operator == "between":
                entry["value2"] = _parse_value(series, item.get("value2"))
                if entry["value"] > entry["value2"]:
                    raise FilterError(f"字段「{column}」的起始值不能大于结束值。")
        normalized.append(entry)

    # 去除完全重复的条件
    unique: list[dict[str, Any]] = []
    seen = set()
    for item in normalized:
        key = (item["column"], item["op"], str(item["value"]), str(item["value2"]))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique, logic


def normalize_sorts(df: pd.DataFrame, sorts: Any) -> list[dict[str, str]]:
    if sorts is None:
        return []
    if not isinstance(sorts, list):
        raise FilterError("排序设置格式不正确。")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in sorts:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column") or "").strip()
        if not column:
            continue
        if column not in df.columns:
            raise FilterError(f"排序字段「{column}」不存在。")
        if column in seen:
            continue
        order = str(item.get("order") or "asc").lower()
        if order not in {"asc", "desc"}:
            order = "asc"
        result.append({"column": column, "order": order})
        seen.add(column)
        if len(result) >= 5:
            break
    return result


def _condition_mask(df: pd.DataFrame, item: dict[str, Any]) -> pd.Series:
    series = df[item["column"]]
    operator = item["op"]
    value = item.get("value")
    kind = column_kind(series)

    if operator == "is_null":
        return series.isna()
    if operator == "not_null":
        return series.notna()

    if kind == "number":
        numbers = pd.to_numeric(series, errors="coerce")
        if operator == "eq":
            return numbers.eq(value).fillna(False)
        if operator == "ne":
            return ~numbers.eq(value).fillna(False)
        if operator == "gt":
            return numbers.gt(value).fillna(False)
        if operator == "gte":
            return numbers.ge(value).fillna(False)
        if operator == "lt":
            return numbers.lt(value).fillna(False)
        if operator == "lte":
            return numbers.le(value).fillna(False)
        if operator == "between":
            return (numbers.ge(value) & numbers.le(item.get("value2"))).fillna(False)
        raise FilterError("不支持的筛选方式。")

    if kind == "datetime":
        dates = pd.to_datetime(series, errors="coerce")
        value = pd.to_datetime(value)
        if operator == "between":
            return (dates.ge(value) & dates.le(pd.to_datetime(item.get("value2")))).fillna(False)
        if operator == "eq":
            return dates.eq(value).fillna(False)
        if operator == "ne":
            return ~dates.eq(value).fillna(False)
        if operator == "gt":
            return dates.gt(value).fillna(False)
        if operator == "gte":
            return dates.ge(value).fillna(False)
        if operator == "lt":
            return dates.lt(value).fillna(False)
        if operator == "lte":
            return dates.le(value).fillna(False)
        raise FilterError("不支持的筛选方式。")

    text = series.astype("string")
    if operator == "contains":
        return text.str.contains(str(value), case=False, na=False, regex=False)
    if operator == "not_contains":
        matched = text.str.contains(str(value), case=False, na=False, regex=False)
        return ~matched.fillna(False)
    if operator == "eq":
        return text.eq(str(value)).fillna(False)
    if operator == "ne":
        return ~text.eq(str(value)).fillna(False)
    raise FilterError("不支持的筛选方式。")


def apply_view(
    df: pd.DataFrame,
    filters: list[dict[str, Any]] | None,
    logic: str,
    sorts: list[dict[str, str]] | None,
) -> pd.DataFrame:
    result = df
    filters = filters or []
    if filters:
        mask: pd.Series | None = None
        for item in filters:
            try:
                condition = _condition_mask(result, item)
            except (KeyError, FilterError, TypeError, ValueError):
                continue
            if mask is None:
                mask = condition
            elif str(logic).upper() == "OR":
                mask = mask | condition
            else:
                mask = mask & condition
        if mask is not None:
            result = result.loc[mask]

    if sorts:
        by = [item["column"] for item in sorts if item.get("column") in result.columns]
        ascending = [item.get("order", "asc") == "asc" for item in sorts if item.get("column") in result.columns]
        if by:
            result = result.sort_values(by=by, ascending=ascending, kind="mergesort", na_position="last")

    return result.reset_index(drop=True)


def describe_value(value: Any) -> str:
    if value is None:
        return "空"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if value.time().isoformat() == "00:00:00" else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def describe_filters(filters: list[dict[str, Any]] | None, logic: str = "AND") -> str:
    if not filters:
        return "无筛选条件"
    parts = []
    for item in filters:
        label = OPERATOR_LABELS.get(item.get("op"), item.get("op"))
        if item.get("op") in NO_VALUE_OPERATORS:
            parts.append(f"{item.get('column')} {label}")
        elif item.get("op") == "between":
            parts.append(
                f"{item.get('column')} {label} {describe_value(item.get('value'))} 与 {describe_value(item.get('value2'))}"
            )
        else:
            parts.append(f"{item.get('column')} {label} {describe_value(item.get('value'))}")
    connector = " 且 " if str(logic).upper() != "OR" else " 或 "
    return connector.join(parts)


def describe_sorts(sorts: list[dict[str, str]] | None) -> str:
    if not sorts:
        return "无排序"
    return "，".join(
        f"{item.get('column')} {'升序' if item.get('order') == 'asc' else '降序'}" for item in sorts
    )
