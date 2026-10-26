"""历史记录展示文案。"""
from __future__ import annotations

import json
from typing import Any

TYPE_CLASS = {
    "上传": "upload",
    "去重": "clean",
    "填充": "clean",
    "删除列": "clean",
    "类型转换": "clean",
    "筛选": "clean",
    "排序": "clean",
    "撤销": "clean",
    "重置": "clean",
    "导出": "export",
    "图表导出": "export",
    "删除数据集": "danger",
}

CHART_TYPE_LABELS = {"bar": "柱状图", "line": "折线图", "pie": "饼图", "scatter": "散点图"}


def type_class(operation_type: str) -> str:
    return TYPE_CLASS.get(operation_type, "other")


def _join(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value)
    return str(value) if value else "—"


def summarize(operation_type: str, detail: dict[str, Any] | None) -> str:
    detail = detail or {}
    try:
        if operation_type == "上传":
            suffix = f"，工作表「{detail.get('sheet')}」" if detail.get("sheet") else ""
            return (
                f"导入 {int(detail.get('rows', 0)):,} 行 × {int(detail.get('columns', 0))} 列"
                f"{suffix}"
            )
        if operation_type == "去重":
            removed = int(detail.get("removed", 0))
            return f"删除 {removed} 行重复数据，剩余 {int(detail.get('rows_after', 0)):,} 行"
        if operation_type == "填充":
            columns = _join(detail.get("columns"))
            method = detail.get("method_label") or detail.get("method") or "指定值"
            return f"用{method}填充 {int(detail.get('filled', 0))} 个空值：{columns}"
        if operation_type == "删除列":
            return f"删除 {len(detail.get('columns', []))} 个字段：{_join(detail.get('columns'))}"
        if operation_type == "类型转换":
            target = detail.get("target_label") or detail.get("target") or ""
            failed = int(detail.get("failed", 0))
            suffix = f"，{failed} 个值置空" if failed else ""
            return f"「{detail.get('column', '')}」转换为{target}{suffix}"
        if operation_type == "筛选":
            filters = detail.get("filters") or []
            if not filters:
                return "清空筛选条件"
            return f"{len(filters)} 个条件（{'且' if detail.get('logic') != 'OR' else '或'}），匹配 {int(detail.get('matched_rows', 0)):,} 行"
        if operation_type == "排序":
            sorts = detail.get("sorts") or []
            if not sorts:
                return "清空排序"
            parts = [
                f"{item.get('column')} {'升序' if item.get('order') == 'asc' else '降序'}"
                for item in sorts
            ]
            return "、".join(parts)
        if operation_type == "导出":
            scope = "当前筛选视图" if detail.get("scope") == "view" else "全部清洗数据"
            return f"Excel · {scope} · {int(detail.get('rows', 0)):,} 行 × {int(detail.get('columns', 0))} 列"
        if operation_type == "图表导出":
            label = CHART_TYPE_LABELS.get(str(detail.get("chart_type")), "图表")
            ys = _join(detail.get("y"))
            return f"PNG · {label} · {detail.get('x', '')} / {ys}"
        if operation_type == "撤销":
            return f"从 v{detail.get('from_version')} 撤销到 v{detail.get('to_version')}"
        if operation_type == "重置":
            return f"从 v{detail.get('from_version')} 恢复到原始数据 v0"
        if operation_type == "删除数据集":
            return f"删除数据集「{detail.get('dataset_name', '')}」及其文件"
    except (TypeError, ValueError):
        return "操作已完成"
    return "—"


def detail_json(detail: dict[str, Any] | None) -> str:
    return json.dumps(detail or {}, ensure_ascii=False, indent=2, default=str)
