"""图表数据准备（ECharts 与 Matplotlib 共用）。"""
from __future__ import annotations

import io
import math
import threading
from datetime import date, datetime, time
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

import config  # noqa: E402

CHART_TYPES = ["bar", "line", "pie", "scatter"]
CHART_LABELS = {"bar": "柱状图", "line": "折线图", "pie": "饼图", "scatter": "散点图"}
AGG_LABELS = {
    "none": "不聚合",
    "sum": "求和",
    "mean": "平均值",
    "count": "计数",
    "max": "最大值",
    "min": "最小值",
}
SORT_LABELS = {
    "auto": "自动",
    "none": "不排序",
    "x_asc": "X 升序",
    "x_desc": "X 降序",
    "value_asc": "值升序",
    "value_desc": "值降序",
}

MAX_CATEGORY_POINTS = 2000
MAX_SCATTER_POINTS = 5000

_font_lock = threading.Lock()
_font_ready = False


class ChartError(ValueError):
    """图表配置不合法。"""


def _is_missing(value: Any) -> bool:
    if value is None or value is pd.NaT or value is pd.NA:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if isinstance(result, (bool, np.bool_)) else False
    except (TypeError, ValueError):
        return False


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _json_number(value: Any) -> int | float | None:
    number = _number(value)
    if number is None:
        return None
    if number.is_integer() and abs(number) < 1e15:
        return int(number)
    return number


def _display_x(value: Any) -> str:
    if _is_missing(value):
        return "（空值）"
    if isinstance(value, (pd.Timestamp, datetime)):
        if value.time() == time(0, 0):
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value)


def _sort_key(value: Any) -> tuple[int, Any]:
    if _is_missing(value):
        return (3, "")
    if isinstance(value, (pd.Timestamp, datetime)):
        return (1, pd.Timestamp(value).value)
    if isinstance(value, (date,)):
        return (1, pd.Timestamp(value).value)
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return (0, float(value))
    return (2, str(value))


def _normalize_config(df: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    chart_type = str(cfg.get("type") or "bar").lower()
    if chart_type not in CHART_TYPES:
        raise ChartError("不支持的图表类型。")

    x = str(cfg.get("x") or "").strip()
    if not x or x not in df.columns:
        raise ChartError("请选择有效的 X 轴字段。")

    raw_y = cfg.get("y")
    if isinstance(raw_y, str):
        ys = [raw_y]
    elif isinstance(raw_y, (list, tuple)):
        ys = [str(item) for item in raw_y if str(item).strip()]
    else:
        ys = []
    ys = list(dict.fromkeys(ys))
    if not ys:
        raise ChartError("请选择至少一个 Y 轴字段。")
    if chart_type in {"pie", "scatter"} and len(ys) > 1:
        ys = ys[:1]
    if len(ys) > 8:
        raise ChartError("最多支持 8 个 Y 轴字段。")
    if x in ys:
        raise ChartError("X 轴与 Y 轴不能选择同一个字段。")
    missing = [name for name in ys if name not in df.columns]
    if missing:
        raise ChartError(f"Y 轴字段「{'、'.join(missing)}」不存在。")

    for name in [x, *ys]:
        series = df[name]
        if not (pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)):
            role = "X 轴" if name == x else "Y 轴"
            if chart_type == "scatter":
                raise ChartError(f"散点图的{role}字段「{name}」必须是数值类型。")
            if name != x:
                raise ChartError(f"Y 轴字段「{name}」必须是数值类型。")

    agg = str(cfg.get("agg") or "sum").lower()
    if agg not in AGG_LABELS:
        raise ChartError("不支持的聚合方式。")
    if chart_type == "scatter":
        agg = "none"

    try:
        top_n = int(cfg.get("top_n") or 0)
    except (TypeError, ValueError):
        top_n = 0
    top_n = max(0, min(500, top_n))

    sort = str(cfg.get("sort") or "auto").lower()
    if sort not in SORT_LABELS:
        sort = "auto"

    return {
        "type": chart_type,
        "x": x,
        "y": ys,
        "agg": agg,
        "top_n": top_n,
        "sort": sort,
    }


def _sort_indices(
    raw_categories: list[Any], values: list[list[Any]], sort: str, chart_type: str
) -> list[int]:
    indices = list(range(len(raw_categories)))
    if sort == "auto":
        sort = "x_asc" if chart_type == "line" else "value_desc" if chart_type in {"bar", "pie"} else "none"
    if sort == "none" or not indices:
        return indices

    if sort in {"x_asc", "x_desc"}:
        indices.sort(key=lambda index: _sort_key(raw_categories[index]), reverse=sort == "x_desc")
    else:
        def value_key(index: int):
            number = _number(values[0][index]) if values and values[0] else None
            return (number is None, number if number is not None else 0.0)

        indices.sort(key=value_key, reverse=sort == "value_desc")
    return indices


def prepare_chart(df: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    config_data = _normalize_config(df, cfg)
    chart_type = config_data["type"]
    x_name = config_data["x"]
    y_names = config_data["y"]
    agg = config_data["agg"]
    warnings: list[str] = []

    if chart_type == "scatter":
        work = df[[x_name, y_names[0]]].copy()
        work[x_name] = pd.to_numeric(work[x_name], errors="coerce")
        work[y_names[0]] = pd.to_numeric(work[y_names[0]], errors="coerce")
        work = work.dropna(subset=[x_name, y_names[0]])
        total = len(work)
        if total > MAX_SCATTER_POINTS:
            step = int(math.ceil(total / MAX_SCATTER_POINTS))
            work = work.iloc[::step]
            warnings.append(f"散点数量较多，已按每 {step} 条抽样显示 {len(work)} 个点。")
        points = [
            [_json_number(row[0]), _json_number(row[1])]
            for row in work.itertuples(index=False, name=None)
        ]
        return {
            "type": chart_type,
            "x": x_name,
            "y": y_names,
            "agg": "none",
            "categories": [],
            "series": [{"name": y_names[0], "data": points}],
            "points": points,
            "x_label": x_name,
            "y_label": y_names[0],
            "warnings": warnings,
            "rows_used": len(work),
            "aggregated": False,
        }

    if chart_type == "pie" and agg == "none":
        agg = "sum"
        warnings.append("饼图按 X 轴汇总后展示各分类占比。")

    work = df[[x_name, *y_names]].copy()
    work = work[work[x_name].notna()]
    if work.empty:
        raise ChartError("X 轴没有可用数据。")

    if agg == "none":
        work = work.dropna(subset=y_names, how="all")
        if work.empty:
            raise ChartError("所选字段没有可用数值。")
        if len(work) > MAX_CATEGORY_POINTS:
            work = work.head(MAX_CATEGORY_POINTS)
            warnings.append(f"数据行较多，仅展示前 {MAX_CATEGORY_POINTS} 行，建议使用聚合方式。")
        if work[x_name].duplicated().any():
            warnings.append("X 轴存在重复值，建议选择聚合方式，以免图形重叠。")
        raw_categories = work[x_name].tolist()
        series_values = [work[name].tolist() for name in y_names]
    else:
        grouped = work.groupby(x_name, dropna=False, sort=False)
        if agg == "count":
            counts = grouped.size()
            raw_categories = list(counts.index)
            series_values = [counts.tolist()]
            y_display = ["记录数"]
        else:
            data = grouped[y_names].agg(agg)
            raw_categories = list(data.index)
            series_values = [data[name].tolist() for name in y_names]
            y_display = y_names
        if len(raw_categories) > MAX_CATEGORY_POINTS:
            warnings.append(
                f"分类过多（{len(raw_categories)} 个），仅保留前 {MAX_CATEGORY_POINTS} 个，可使用前 N 项或筛选。"
            )

    if agg == "count":
        series_names = ["记录数"]
        y_label = "记录数"
    else:
        series_names = y_names
        y_label = y_names[0] if len(y_names) == 1 else "数值"

    # 饼图只保留正数
    if chart_type == "pie":
        values = series_values[0]
        keep = [
            index
            for index, value in enumerate(values)
            if _number(value) is not None and float(value) > 0
        ]
        if not keep:
            raise ChartError("饼图需要至少一个大于 0 的数值。")
        if len(keep) != len(values):
            warnings.append("饼图已忽略小于等于 0 或为空的值。")
        raw_categories = [raw_categories[index] for index in keep]
        series_values = [[values[index] for index in keep]]
        series_names = series_names[:1]
        y_label = series_names[0]

    indices = _sort_indices(raw_categories, series_values, config_data["sort"], chart_type)
    raw_categories = [raw_categories[index] for index in indices]
    series_values = [[values[index] for index in indices] for values in series_values]

    top_n = config_data["top_n"]
    if top_n and len(raw_categories) > top_n:
        if chart_type == "pie":
            kept_categories = raw_categories[:top_n]
            kept_values = series_values[0][:top_n]
            rest = series_values[0][top_n:]
            other_value = sum(_number(value) or 0 for value in rest)
            other_name = "其他"
            existing = [index for index, name in enumerate(kept_categories) if str(name) == other_name]
            if existing:
                kept_values[existing[0]] = (_number(kept_values[existing[0]]) or 0) + other_value
            else:
                kept_categories.append(other_name)
                kept_values.append(other_value)
            raw_categories = kept_categories
            series_values = [kept_values]
            warnings.append(f"饼图仅展示前 {top_n} 个分类，其余合并为“其他”。")
        else:
            raw_categories = raw_categories[:top_n]
            series_values = [values[:top_n] for values in series_values]
            warnings.append(f"仅展示排序后的前 {top_n} 项。")

    display_categories = [_display_x(value) for value in raw_categories]
    series = []
    for name, values in zip(series_names, series_values):
        series.append(
            {
                "name": name,
                "data": [_json_number(value) for value in values],
            }
        )

    return {
        "type": chart_type,
        "x": x_name,
        "y": y_names,
        "agg": agg,
        "categories": display_categories,
        "series": series,
        "points": [],
        "x_label": x_name,
        "y_label": y_label,
        "warnings": list(dict.fromkeys(warnings)),
        "rows_used": len(work),
        "aggregated": agg != "none",
    }


def chart_title(data: dict[str, Any]) -> str:
    if data["type"] == "scatter":
        return f"{data['y'][0]} 与 {data['x']} 的关系"
    y_text = "、".join(data["y"])
    if data["type"] == "pie":
        return f"{y_text} 构成（按 {data['x']}）"
    return f"{y_text} 按 {data['x']}"


def _axis_rotate(categories: list[str]) -> int:
    if not categories:
        return 0
    longest = max(len(str(item)) for item in categories)
    if longest >= 10 or len(categories) > 18:
        return 35
    if longest >= 7 or len(categories) > 10:
        return 20
    return 0


def to_echarts_option(data: dict[str, Any], title: str | None = None) -> dict[str, Any]:
    title = title or chart_title(data)
    chart_type = data["type"]
    option: dict[str, Any] = {
        "color": config.CHART_PALETTE,
        "animationDuration": 350,
        "textStyle": {
            "fontFamily": '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif',
            "color": "#1f2933",
        },
        "title": {
            "text": title,
            "left": "center",
            "top": 10,
            "textStyle": {"fontSize": 14, "fontWeight": "normal", "color": "#1f2933"},
        },
        "toolbox": {
            "right": 12,
            "top": 8,
            "feature": {
                "saveAsImage": {
                    "title": "保存为图片",
                    "pixelRatio": 2,
                    "backgroundColor": "#ffffff",
                }
            },
        },
    }

    if chart_type == "pie":
        values = [
            {"name": category, "value": value}
            for category, value in zip(data["categories"], data["series"][0]["data"])
        ]
        option.update(
            {
                "tooltip": {"trigger": "item", "formatter": "{b}<br/>{c}（{d}%）"},
                "legend": {
                    "bottom": 4,
                    "type": "scroll",
                    "textStyle": {"color": "#4b5563"},
                    "itemWidth": 12,
                    "itemHeight": 8,
                },
                "series": [
                    {
                        "type": "pie",
                        "name": data["series"][0]["name"],
                        "radius": ["0%", "62%"],
                        "center": ["50%", "52%"],
                        "data": values,
                        "label": {
                            "formatter": "{b}  {d}%",
                            "fontSize": 11,
                            "color": "#374151",
                        },
                        "labelLine": {"length": 8, "length2": 8},
                        "emphasis": {"scale": True},
                    }
                ],
            }
        )
        return option

    if chart_type == "scatter":
        option.update(
            {
                "tooltip": {"trigger": "item", "formatter": "{c}"},
                "grid": {"left": 18, "right": 30, "top": 70, "bottom": 58, "containLabel": True},
                "xAxis": {
                    "type": "value",
                    "name": data["x_label"],
                    "nameLocation": "middle",
                    "nameGap": 34,
                    "scale": True,
                    "axisLine": {"lineStyle": {"color": "#b9c2cc"}},
                    "axisLabel": {"color": "#4b5563"},
                    "splitLine": {"lineStyle": {"color": "#eef0f2"}},
                },
                "yAxis": {
                    "type": "value",
                    "name": data["y_label"],
                    "scale": True,
                    "axisLine": {"show": True, "lineStyle": {"color": "#b9c2cc"}},
                    "axisLabel": {"color": "#4b5563"},
                    "splitLine": {"lineStyle": {"color": "#e6e9ec"}},
                },
                "series": [
                    {
                        "type": "scatter",
                        "name": data["y"][0],
                        "data": data["points"],
                        "symbolSize": 9,
                        "large": len(data["points"]) > 2000,
                        "largeThreshold": 2000,
                        "itemStyle": {"color": config.CHART_PALETTE[0]},
                    }
                ],
            }
        )
        return option

    multi_series = len(data["series"]) > 1
    rotate = _axis_rotate(data["categories"])
    show_labels = len(data["categories"]) <= 12 and not multi_series
    category_count = len(data["categories"])
    label_interval = 0 if category_count <= 12 else max(1, math.ceil(category_count / 12))
    option.update(
        {
            "tooltip": {
                "trigger": "axis",
                "axisPointer": {"type": "shadow" if chart_type == "bar" else "line"},
            },
            "legend": (
                {
                    "top": 34,
                    "type": "scroll",
                    "textStyle": {"color": "#4b5563"},
                    "itemWidth": 14,
                    "itemHeight": 8,
                }
                if multi_series
                else {"show": False}
            ),
            "grid": {
                "left": 18,
                "right": 28,
                "top": 74 if multi_series else 62,
                "bottom": 66 if rotate else 52,
                "containLabel": True,
            },
            "xAxis": {
                "type": "category",
                "data": data["categories"],
                "name": data["x_label"],
                "nameLocation": "middle",
                "nameGap": 42 if rotate else 28,
                "axisLine": {"lineStyle": {"color": "#b9c2cc"}},
                "axisTick": {"alignWithLabel": True, "lineStyle": {"color": "#b9c2cc"}},
                "axisLabel": {
                    "color": "#4b5563",
                    "interval": label_interval,
                    "rotate": rotate,
                    "fontSize": 11,
                    "hideOverlap": True,
                },
            },
            "yAxis": {
                "type": "value",
                "name": data["y_label"],
                "nameTextStyle": {"color": "#4b5563"},
                "axisLine": {"show": True, "lineStyle": {"color": "#b9c2cc"}},
                "axisLabel": {"color": "#4b5563"},
                "splitLine": {"lineStyle": {"color": "#e6e9ec"}},
            },
            "dataZoom": (
                [{"type": "inside", "start": 0, "end": 100}]
                if len(data["categories"]) > 25
                else []
            ),
        }
    )

    series = []
    for index, item in enumerate(data["series"]):
        if chart_type == "bar":
            series.append(
                {
                    "type": "bar",
                    "name": item["name"],
                    "data": item["data"],
                    "barMaxWidth": 38,
                    "itemStyle": {"color": config.CHART_PALETTE[index % len(config.CHART_PALETTE)]},
                    "emphasis": {"focus": "series"},
                    "label": {
                        "show": show_labels,
                        "position": "top",
                        "fontSize": 10,
                        "color": "#4b5563",
                    },
                }
            )
        else:
            series.append(
                {
                    "type": "line",
                    "name": item["name"],
                    "data": item["data"],
                    "symbol": "circle",
                    "symbolSize": 5,
                    "lineStyle": {"width": 2},
                    "itemStyle": {"color": config.CHART_PALETTE[index % len(config.CHART_PALETTE)]},
                    "connectNulls": False,
                }
            )
    option["series"] = series
    return option


def _setup_fonts() -> None:
    global _font_ready
    if _font_ready:
        return
    with _font_lock:
        if _font_ready:
            return
        from matplotlib import font_manager

        available = {font.name for font in font_manager.fontManager.ttflist}
        preferred = [
            "Microsoft YaHei",
            "SimHei",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "WenQuanYi Zen Hei",
            "Arial Unicode MS",
        ]
        chosen = [name for name in preferred if name in available]
        plt.rcParams["font.sans-serif"] = chosen + ["DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        _font_ready = True


def _fmt_value(value: float) -> str:
    if abs(value) >= 10000:
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_axis(value: float, position: int) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def render_png(data: dict[str, Any], title: str | None = None) -> io.BytesIO:
    _setup_fonts()
    title = title or chart_title(data)
    chart_type = data["type"]
    categories = data["categories"]
    series = data["series"]
    palette = config.CHART_PALETTE

    if chart_type == "scatter":
        width = 9.6
        height = 6.2
    elif chart_type == "line":
        width = max(8.0, min(13.0, 6.0 + max(0, len(categories)) * 0.12))
        height = 6.2
    else:
        width = max(8.0, min(16.0, 6.0 + max(0, len(categories)) * 0.38))
        height = 6.2

    fig, ax = plt.subplots(figsize=(width, height), dpi=100)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if chart_type == "pie":
        values = [float(value or 0) for value in series[0]["data"]]
        colors = [palette[index % len(palette)] for index in range(len(values))]
        wedges, _ = ax.pie(
            values,
            colors=colors,
            startangle=90,
            counterclock=False,
            wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
        )
        ax.axis("equal")
        total = sum(values)
        legend_labels = [
            f"{category}  {_fmt_value(value)}（{value / total * 100:.1f}%）"
            if total
            else category
            for category, value in zip(categories, values)
        ]
        ax.legend(
            wedges,
            legend_labels,
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            frameon=False,
            fontsize=9,
        )
        ax.set_title(title, loc="left", fontsize=13, color="#1f2933", pad=14)
    elif chart_type == "scatter":
        points = data["points"]
        xs = [float(point[0]) for point in points if point[0] is not None]
        ys = [float(point[1]) for point in points if point[1] is not None]
        ax.scatter(
            xs,
            ys,
            s=26,
            color=palette[0],
            edgecolors="white",
            linewidths=0.5,
            alpha=0.9,
        )
        ax.set_xlabel(data["x_label"], fontsize=10, color="#4b5563")
        ax.set_ylabel(data["y_label"], fontsize=10, color="#4b5563")
        ax.set_title(title, loc="left", fontsize=13, color="#1f2933", pad=14)
        ax.grid(True, color="#e6e9ec", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.xaxis.set_major_formatter(FuncFormatter(_format_axis))
        ax.yaxis.set_major_formatter(FuncFormatter(_format_axis))
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color("#b9c2cc")
        ax.tick_params(colors="#4b5563", labelsize=9)
    else:
        indices = list(range(len(categories)))
        if chart_type == "bar":
            count = max(1, len(series))
            width_bar = min(0.8 / count, 0.8)
            for index, item in enumerate(series):
                offset = (index - (count - 1) / 2) * width_bar
                values = [float(value) if value is not None else 0.0 for value in item["data"]]
                bars = ax.bar(
                    [position + offset for position in indices],
                    values,
                    width=width_bar,
                    color=palette[index % len(palette)],
                    label=item["name"],
                )
                if len(series) == 1 and len(categories) <= 12:
                    for rect, value in zip(bars, values):
                        ax.annotate(
                            _fmt_value(value),
                            (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                            textcoords="offset points",
                            xytext=(0, 3),
                            ha="center",
                            va="bottom",
                            fontsize=8,
                            color="#4b5563",
                        )
            if len(series) > 1:
                ax.legend(frameon=False, fontsize=9)
        else:
            for index, item in enumerate(series):
                values = [float(value) if value is not None else np.nan for value in item["data"]]
                ax.plot(
                    indices,
                    values,
                    marker="o",
                    markersize=4,
                    linewidth=1.8,
                    color=palette[index % len(palette)],
                    label=item["name"],
                )
            if len(series) > 1:
                ax.legend(frameon=False, fontsize=9, loc="best")

        rotate = 0
        if categories:
            longest = max(len(str(item)) for item in categories)
            if longest >= 10 or len(categories) > 18:
                rotate = 35
            elif longest >= 7 or len(categories) > 10:
                rotate = 20

        if len(categories) > 20:
            step = max(1, math.ceil(len(categories) / 10))
            tick_positions = indices[::step]
        else:
            tick_positions = indices
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(
            [str(categories[position]) for position in tick_positions],
            rotation=rotate,
            ha="right" if rotate else "center",
            fontsize=8.5 if len(categories) > 15 else 9.5,
            color="#4b5563",
        )
        ax.set_xlabel(data["x_label"], fontsize=10, color="#4b5563")
        ax.set_ylabel(data["y_label"], fontsize=10, color="#4b5563")
        ax.set_title(title, loc="left", fontsize=13, color="#1f2933", pad=14)
        ax.grid(True, axis="y", color="#e6e9ec", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.yaxis.set_major_formatter(FuncFormatter(_format_axis))
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color("#b9c2cc")
        ax.tick_params(colors="#4b5563", labelsize=9)
        ax.margins(x=0.01)

    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer
