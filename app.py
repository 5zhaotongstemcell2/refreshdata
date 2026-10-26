"""数据洞察 · 轻量级数据可视化分析工具。

运行：python app.py --open
"""
from __future__ import annotations

from deps import ensure_dependencies

ensure_dependencies()

import argparse  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import webbrowser  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

try:
    from flask import (  # noqa: E402
        Flask,
        abort,
        jsonify,
        redirect,
        render_template,
        request,
        send_file,
        url_for,
    )

    import config  # noqa: E402
    import database  # noqa: E402
    from services import charts, cleaner, exporter, filters, history, importer, storage  # noqa: E402
    from services.serialize import column_meta, dataframe_records, friendly_type  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - 仅用于首次运行提示
    raise SystemExit(
        f"缺少 Python 依赖：{exc.name}\n"
        "请先执行：pip install -r requirements.txt\n"
        "或使用项目根目录的 run.bat 启动。"
    ) from exc

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

config.ensure_dirs()
database.init_db()


def _cleanup_uploads(max_age_hours: int = 24) -> None:
    cutoff = time.time() - max_age_hours * 3600
    for item in config.UPLOAD_DIR.glob("*"):
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
        except OSError:
            continue


_cleanup_uploads()

app = Flask(__name__, template_folder=str(config.TEMPLATE_DIR), static_folder=str(config.STATIC_DIR))
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    MAX_CONTENT_LENGTH=config.MAX_UPLOAD_BYTES,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    JSON_SORT_KEYS=False,
)
app.json.ensure_ascii = False
app.json.sort_keys = False


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _api_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _display_filename(raw: str) -> str:
    name = (raw or "").replace("\\", "/").split("/")[-1].strip()
    return name or "未命名文件"


def _upload_path(token: str) -> Path:
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        raise ValueError("上传标识无效，请重新选择文件。")
    matches = [item for item in config.UPLOAD_DIR.glob(f"{token}.*") if item.is_file()]
    if not matches:
        raise ValueError("上传文件已过期，请重新选择文件。")
    path = matches[0]
    if path.parent.resolve() != config.UPLOAD_DIR.resolve():
        raise ValueError("上传路径无效。")
    return path


def _kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".xlsx":
        return "xlsx"
    raise ValueError("仅支持 .csv 与 .xlsx 文件。")


def _dataset(dataset_id: str) -> storage.Dataset:
    dataset = storage.store.get(dataset_id)
    if dataset is None:
        abort(404)
    return dataset


def _build_summary(dataset: storage.Dataset) -> dict[str, Any]:
    frame = dataset.view()
    profiles = dataset.profile()
    columns = column_meta(dataset.df)
    for column in columns:
        series = dataset.df[column["name"]]
        column["kind"] = filters.column_kind(series)
        column["operators"] = filters.operators_for(series)

    return {
        "id": dataset.id,
        "meta": dataset.meta,
        "profiles": profiles,
        "columns": columns,
        "view_rows": int(len(frame)),
        "base_rows": int(len(dataset.df)),
        "missing_cells": int(dataset.df.isna().sum().sum()),
        "filters": dataset.meta.get("filters", []),
        "logic": dataset.meta.get("logic", "AND"),
        "sorts": dataset.meta.get("sorts", []),
        "versions": list(reversed(dataset.meta.get("versions", []))),
        "chart": dataset.meta.get("chart"),
        "can_undo": int(dataset.meta.get("version", 0)) > 0,
        "can_reset": int(dataset.meta.get("version", 0)) > 0,
        "chart_labels": charts.CHART_LABELS,
        "agg_labels": charts.AGG_LABELS,
        "sort_labels": charts.SORT_LABELS,
        "filter_labels": filters.OPERATOR_LABELS,
        "operator_map": {
            "number": filters.ORDERED_OPERATORS,
            "datetime": filters.ORDERED_OPERATORS,
            "text": filters.TEXT_OPERATORS,
        },
        "limits": {
            "max_rows": config.MAX_ROWS,
            "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
        },
    }


def _enrich_logs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        item["summary"] = history.summarize(item["operation_type"], item.get("detail"))
        item["type_class"] = history.type_class(item["operation_type"])
        item["detail_json"] = history.detail_json(item.get("detail"))
        dataset_id = str((item.get("detail") or {}).get("dataset_id") or "")
        item["dataset_exists"] = bool(
            re.fullmatch(r"[0-9a-f]{12}", dataset_id)
            and (storage.store.root / dataset_id / "meta.json").exists()
        )
    return items


def _history_url(page: int, type_filter: str, keyword: str, date_from: str, date_to: str) -> str:
    return url_for(
        "history_page",
        page=page,
        type=type_filter or None,
        q=keyword or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    datasets = storage.store.recent(6)
    recent_logs = _enrich_logs(database.recent_logs(6))
    stats = database.get_stats()
    samples = []
    if config.SAMPLE_DIR.exists():
        for item in sorted(config.SAMPLE_DIR.glob("*")):
            if item.suffix.lower() in config.ALLOWED_EXTENSIONS:
                samples.append({"name": item.name, "size": item.stat().st_size})
    return render_template(
        "index.html",
        active_page="index",
        datasets=datasets,
        recent_logs=recent_logs,
        stats=stats,
        samples=samples,
    )


@app.get("/workspace/<dataset_id>")
def workspace(dataset_id: str):
    dataset = _dataset(dataset_id)
    summary = _build_summary(dataset)
    return render_template(
        "workspace.html",
        active_page="workspace",
        ds=dataset.meta,
        summary=summary,
    )


@app.get("/history")
def history_page():
    page = request.args.get("page", 1, type=int) or 1
    type_filter = (request.args.get("type") or "").strip()
    keyword = (request.args.get("q") or "").strip()[:100]
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    if date_from and not _DATE_RE.match(date_from):
        date_from = ""
    if date_to and not _DATE_RE.match(date_to):
        date_to = ""

    result = database.list_logs(
        page=page,
        per_page=20,
        operation_type=type_filter or None,
        keyword=keyword or None,
        date_from=date_from or None,
        date_to=date_to or None,
    )
    items = _enrich_logs(result["items"])
    total = result["total"]
    page = result["page"]
    pages = result["pages"]
    types = database.distinct_types()
    for name in config.LOG_TYPES:
        if name not in types:
            types.append(name)

    return render_template(
        "history.html",
        active_page="history",
        items=items,
        total=total,
        page=page,
        pages=pages,
        per_page=result["per_page"],
        type_filter=type_filter,
        keyword=keyword,
        date_from=date_from,
        date_to=date_to,
        types=types,
        stats=database.get_stats(),
        prev_url=_history_url(max(1, page - 1), type_filter, keyword, date_from, date_to),
        next_url=_history_url(min(pages, page + 1), type_filter, keyword, date_from, date_to),
        start_index=(page - 1) * result["per_page"] + 1 if total else 0,
        end_index=min(page * result["per_page"], total),
        cleared=request.args.get("cleared") == "1",
    )


@app.get("/sample/<path:name>")
def download_sample(name: str):
    safe_name = Path(name).name
    path = config.SAMPLE_DIR / safe_name
    if not path.exists() or path.suffix.lower() not in config.ALLOWED_EXTENSIONS:
        abort(404)
    return send_file(path, as_attachment=True, download_name=safe_name)


# ---------------------------------------------------------------------------
# 文件导入
# ---------------------------------------------------------------------------


@app.post("/api/files/inspect")
def api_inspect():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _api_error("请选择要上传的文件。")
    file_name = _display_filename(upload.filename)
    suffix = Path(file_name).suffix.lower()
    if suffix not in config.ALLOWED_EXTENSIONS:
        return _api_error("仅支持 .csv 与 .xlsx 文件。")

    token = secrets.token_hex(16)
    target = config.UPLOAD_DIR / f"{token}{suffix}"
    try:
        upload.save(target)
    except OSError as exc:
        return _api_error(f"文件保存失败：{exc}", 500)

    if target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return _api_error("文件内容为空。")

    try:
        info = importer.inspect_file(target, file_name)
    except importer.ImportErrorDetail as exc:
        target.unlink(missing_ok=True)
        return _api_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        app.logger.exception("文件检查失败")
        return _api_error(f"文件解析失败：{exc}", 500)

    info["token"] = token
    info["size"] = target.stat().st_size
    return jsonify({"ok": True, "file": info})


@app.post("/api/files/preview")
def api_preview():
    payload = _payload()
    try:
        path = _upload_path(str(payload.get("token") or ""))
        kind = _kind_of(path)
        result = importer.preview_with_options(path, kind, payload)
    except ValueError as exc:
        return _api_error(str(exc))
    except importer.ImportErrorDetail as exc:
        return _api_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("预览失败")
        return _api_error(f"预览失败：{exc}", 500)
    return jsonify({"ok": True, **result})


@app.post("/api/files/import")
def api_import():
    payload = _payload()
    try:
        path = _upload_path(str(payload.get("token") or ""))
        kind = _kind_of(path)
        frame, info = importer.import_file(path, kind, payload)
    except ValueError as exc:
        return _api_error(str(exc))
    except importer.ImportErrorDetail as exc:
        return _api_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("导入失败")
        return _api_error(f"导入失败：{exc}", 500)

    file_name = _display_filename(str(payload.get("file_name") or path.name))
    raw_name = str(payload.get("name") or Path(file_name).stem or "数据集")
    dataset = storage.store.create(
        frame,
        name=raw_name,
        file_name=file_name,
        kind=kind,
        sheet=info.get("sheet"),
        encoding=info.get("encoding"),
        delimiter=info.get("delimiter"),
        header_row=int(info.get("header_row") or 1),
        has_header=bool(info.get("has_header", True)),
    )
    database.log_operation(
        file_name,
        "上传",
        {
            "dataset_id": dataset.id,
            "dataset_name": dataset.meta["name"],
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "kind": kind,
            "sheet": info.get("sheet"),
            "encoding": info.get("encoding"),
            "delimiter": info.get("delimiter"),
            "size": path.stat().st_size,
            "warnings": info.get("warnings", []),
        },
    )
    path.unlink(missing_ok=True)
    return jsonify(
        {
            "ok": True,
            "dataset_id": dataset.id,
            "redirect": url_for("workspace", dataset_id=dataset.id),
            "message": f"已导入 {len(frame):,} 行 × {len(frame.columns)} 列数据。",
        }
    )


# ---------------------------------------------------------------------------
# 数据集 API
# ---------------------------------------------------------------------------


@app.get("/api/datasets/<dataset_id>/summary")
def api_summary(dataset_id: str):
    dataset = _dataset(dataset_id)
    with storage.store.lock:
        summary = _build_summary(dataset)
    return jsonify({"ok": True, "summary": summary})


@app.get("/api/datasets/<dataset_id>/rows")
def api_rows(dataset_id: str):
    dataset = _dataset(dataset_id)
    page = request.args.get("page", 1, type=int) or 1
    page_size = request.args.get("page_size", config.DEFAULT_PAGE_SIZE, type=int)
    page_size = max(5, min(config.MAX_PAGE_SIZE, page_size or config.DEFAULT_PAGE_SIZE))

    with storage.store.lock:
        frame = dataset.view()
        total = int(len(frame))
        pages = max(1, math.ceil(total / page_size)) if total else 1
        page = max(1, min(page, pages))
        start = (page - 1) * page_size
        end = min(start + page_size, total)
        slice_frame = frame.iloc[start:end]
        rows = dataframe_records(slice_frame)
        columns = []
        for name in frame.columns:
            series = frame[name]
            columns.append(
                {
                    "name": str(name),
                    "type": friendly_type(series),
                    "numeric": bool(pd_is_numeric(series)),
                }
            )

    return jsonify(
        {
            "ok": True,
            "rows": rows,
            "columns": columns,
            "total": total,
            "page": page,
            "pages": pages,
            "page_size": page_size,
            "start": start + 1 if total else 0,
            "end": end,
            "filtered": bool(dataset.meta.get("filters")),
        }
    )


def pd_is_numeric(series) -> bool:
    import pandas as pd

    return bool(pd.api.types.is_numeric_dtype(series)) and not bool(
        pd.api.types.is_bool_dtype(series)
    )


@app.post("/api/datasets/<dataset_id>/clean")
def api_clean(dataset_id: str):
    payload = _payload()
    action = str(payload.get("action") or "")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    dataset = _dataset(dataset_id)
    try:
        with storage.store.lock:
            frame, result = cleaner.apply_clean(dataset.df, action, params)
            if not result.get("changed"):
                return jsonify({"ok": True, "changed": False, "message": result.get("message")})

            dataset.df = frame
            store_entry = storage.store.commit(dataset, result.get("label") or "数据清洗")
            storage.store.sanitize_state(dataset)
            storage.store.save_meta(dataset)
            detail = {
                "dataset_id": dataset.id,
                "dataset_name": dataset.meta["name"],
                **result.get("detail", {}),
                "version": store_entry["version"],
            }
            database.log_operation(dataset.file_name, result.get("log_type") or "清洗", detail)
    except cleaner.CleanError as exc:
        return _api_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("清洗失败")
        return _api_error(f"清洗失败：{exc}", 500)

    return jsonify(
        {
            "ok": True,
            "changed": True,
            "message": result.get("message"),
            "redirect": url_for("workspace", dataset_id=dataset.id) + "#clean",
            "version": store_entry["version"],
            "rows": len(dataset.df),
        }
    )


@app.post("/api/datasets/<dataset_id>/undo")
def api_undo(dataset_id: str):
    dataset = _dataset(dataset_id)
    with storage.store.lock:
        from_version = int(dataset.meta.get("version", 0))
        if not storage.store.undo(dataset):
            return jsonify({"ok": True, "changed": False, "message": "已经处于原始数据状态。"})
        to_version = int(dataset.meta.get("version", 0))
        database.log_operation(
            dataset.file_name,
            "撤销",
            {
                "dataset_id": dataset.id,
                "dataset_name": dataset.meta["name"],
                "from_version": from_version,
                "to_version": to_version,
            },
        )
    return jsonify(
        {
            "ok": True,
            "changed": True,
            "message": f"已撤销到 v{to_version}。",
            "redirect": url_for("workspace", dataset_id=dataset.id) + "#clean",
        }
    )


@app.post("/api/datasets/<dataset_id>/reset")
def api_reset(dataset_id: str):
    dataset = _dataset(dataset_id)
    with storage.store.lock:
        from_version = int(dataset.meta.get("version", 0))
        if not storage.store.reset(dataset):
            return jsonify({"ok": True, "changed": False, "message": "数据已经是原始状态。"})
        database.log_operation(
            dataset.file_name,
            "重置",
            {
                "dataset_id": dataset.id,
                "dataset_name": dataset.meta["name"],
                "from_version": from_version,
            },
        )
    return jsonify(
        {
            "ok": True,
            "changed": True,
            "message": "已恢复原始数据，筛选、排序与图表配置已清空。",
            "redirect": url_for("workspace", dataset_id=dataset.id) + "#clean",
        }
    )


@app.post("/api/datasets/<dataset_id>/filters")
def api_filters(dataset_id: str):
    payload = _payload()
    dataset = _dataset(dataset_id)
    try:
        with storage.store.lock:
            new_filters, logic = filters.normalize_filters(
                dataset.df, payload.get("filters"), payload.get("logic")
            )
            new_sorts = filters.normalize_sorts(dataset.df, payload.get("sorts"))

            old_filters = dataset.meta.get("filters", [])
            old_logic = dataset.meta.get("logic", "AND")
            old_sorts = dataset.meta.get("sorts", [])
            filters_changed = new_filters != old_filters or logic != old_logic
            sorts_changed = new_sorts != old_sorts
            if not filters_changed and not sorts_changed:
                return jsonify({"ok": True, "changed": False, "message": "筛选与排序没有变化。"})

            dataset.meta["filters"] = new_filters
            dataset.meta["logic"] = logic
            dataset.meta["sorts"] = new_sorts
            storage.store.save_meta(dataset)
            dataset.invalidate_view()
            matched = len(dataset.view())

            if filters_changed:
                database.log_operation(
                    dataset.file_name,
                    "筛选",
                    {
                        "dataset_id": dataset.id,
                        "dataset_name": dataset.meta["name"],
                        "filters": new_filters,
                        "logic": logic,
                        "matched_rows": matched,
                        "total_rows": len(dataset.df),
                    },
                )
            if sorts_changed:
                database.log_operation(
                    dataset.file_name,
                    "排序",
                    {
                        "dataset_id": dataset.id,
                        "dataset_name": dataset.meta["name"],
                        "sorts": new_sorts,
                        "rows": len(dataset.df),
                    },
                )
    except filters.FilterError as exc:
        return _api_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("筛选失败")
        return _api_error(f"筛选失败：{exc}", 500)

    message = f"筛选与排序已应用，当前匹配 {matched:,} 行。"
    return jsonify(
        {
            "ok": True,
            "changed": True,
            "message": message,
            "redirect": url_for("workspace", dataset_id=dataset.id) + "#filter",
            "matched": matched,
        }
    )


@app.post("/api/datasets/<dataset_id>/chart")
def api_chart(dataset_id: str):
    dataset = _dataset(dataset_id)
    payload = _payload()
    cfg = {
        "type": payload.get("type"),
        "x": payload.get("x"),
        "y": payload.get("y"),
        "agg": payload.get("agg"),
        "top_n": payload.get("top_n"),
        "sort": payload.get("sort"),
    }
    try:
        with storage.store.lock:
            data = charts.prepare_chart(dataset.view(), cfg)
            title = f"{dataset.meta['name']} · {charts.chart_title(data)}"
            option = charts.to_echarts_option(data, title)
            dataset.meta["chart"] = {
                "type": data["type"],
                "x": data["x"],
                "y": data["y"],
                "agg": data["agg"],
                "top_n": int(cfg.get("top_n") or 0),
                "sort": str(cfg.get("sort") or "auto"),
            }
            storage.store.save_meta(dataset)
    except charts.ChartError as exc:
        return _api_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("图表生成失败")
        return _api_error(f"图表生成失败：{exc}", 500)

    return jsonify(
        {
            "ok": True,
            "option": option,
            "config": dataset.meta["chart"],
            "meta": {
                "title": title,
                "type": data["type"],
                "type_label": charts.CHART_LABELS[data["type"]],
                "rows_used": data["rows_used"],
                "category_count": len(data["categories"]),
                "series_names": [item["name"] for item in data["series"]],
                "warnings": data["warnings"],
                "aggregated": data["aggregated"],
                "agg_label": charts.AGG_LABELS.get(data["agg"], data["agg"]),
            },
        }
    )


@app.post("/api/datasets/<dataset_id>/chart/export")
def api_chart_export(dataset_id: str):
    dataset = _dataset(dataset_id)
    payload = _payload()
    cfg = {
        "type": payload.get("type"),
        "x": payload.get("x"),
        "y": payload.get("y"),
        "agg": payload.get("agg"),
        "top_n": payload.get("top_n"),
        "sort": payload.get("sort"),
    }
    try:
        with storage.store.lock:
            data = charts.prepare_chart(dataset.view(), cfg)
            title = f"{dataset.meta['name']} · {charts.chart_title(data)}"
            buffer = charts.render_png(data, title)
            filename = exporter.build_chart_filename(
                dataset.meta, charts.CHART_LABELS[data["type"]]
            )
            database.log_operation(
                dataset.file_name,
                "图表导出",
                {
                    "dataset_id": dataset.id,
                    "dataset_name": dataset.meta["name"],
                    "chart_type": data["type"],
                    "x": data["x"],
                    "y": data["y"],
                    "agg": data["agg"],
                    "rows_used": data["rows_used"],
                    "categories": len(data["categories"]),
                    "aggregated": data["aggregated"],
                },
            )
    except charts.ChartError as exc:
        return _api_error(str(exc))
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("图表导出失败")
        return _api_error(f"图表导出失败：{exc}", 500)

    return send_file(
        buffer,
        mimetype="image/png",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )


@app.get("/api/datasets/<dataset_id>/export.xlsx")
def api_export_excel(dataset_id: str):
    dataset = _dataset(dataset_id)
    scope = "all" if request.args.get("scope") == "all" else "view"
    try:
        with storage.store.lock:
            frame = dataset.df if scope == "all" else dataset.view()
            filters_text = filters.describe_filters(
                dataset.meta.get("filters", []), dataset.meta.get("logic", "AND")
            )
            sorts_text = filters.describe_sorts(dataset.meta.get("sorts", []))
            buffer, filename = exporter.build_excel(
                frame,
                dataset.meta,
                scope=scope,
                filters_text=filters_text,
                sorts_text=sorts_text,
            )
            database.log_operation(
                dataset.file_name,
                "导出",
                {
                    "dataset_id": dataset.id,
                    "dataset_name": dataset.meta["name"],
                    "scope": scope,
                    "rows": int(len(frame)),
                    "columns": int(len(frame.columns)),
                    "filters": dataset.meta.get("filters", []),
                    "logic": dataset.meta.get("logic", "AND"),
                    "sorts": dataset.meta.get("sorts", []),
                    "filename": filename,
                },
            )
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Excel 导出失败")
        return _api_error(f"导出失败：{exc}", 500)

    return send_file(
        buffer,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )


@app.delete("/api/datasets/<dataset_id>")
def api_delete_dataset(dataset_id: str):
    dataset = _dataset(dataset_id)
    with storage.store.lock:
        meta = dict(dataset.meta)
        if not storage.store.delete(dataset_id):
            return _api_error("删除失败，数据集可能已不存在。", 404)
        database.log_operation(
            meta.get("file_name", ""),
            "删除数据集",
            {
                "dataset_id": dataset_id,
                "dataset_name": meta.get("name"),
                "rows": int(meta.get("row_count", 0)),
            },
        )
    return jsonify({"ok": True, "message": "数据集已删除。", "redirect": url_for("index")})


# ---------------------------------------------------------------------------
# 历史记录
# ---------------------------------------------------------------------------


@app.post("/history/clear")
def clear_history():
    database.clear_logs()
    return redirect(url_for("history_page", cleared=1))


# ---------------------------------------------------------------------------
# 错误处理与响应头
# ---------------------------------------------------------------------------


def _wants_json() -> bool:
    return request.path.startswith("/api/") or request.is_json


@app.errorhandler(404)
def handle_404(error):
    if _wants_json():
        return _api_error("资源不存在或已删除。", 404)
    return render_template("error.html", code=404, message="页面或数据集不存在，可能已被删除。"), 404


@app.errorhandler(413)
def handle_413(error):
    message = f"文件超过 {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB 限制。"
    if _wants_json():
        return _api_error(message, 413)
    return render_template("error.html", code=413, message=message), 413


@app.errorhandler(500)
def handle_500(error):
    if _wants_json():
        return _api_error("服务器内部错误，请查看控制台日志。", 500)
    return render_template("error.html", code=500, message="服务器内部错误，请查看控制台日志。"), 500


@app.after_request
def add_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# 模板过滤器
# ---------------------------------------------------------------------------


@app.template_filter("filesize")
def format_filesize(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "—"
    if size < 1024:
        return f"{size:.0f} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


@app.template_filter("num")
def format_number(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


@app.context_processor
def inject_globals():
    return {"current_year": datetime.now().year, "app_version": "1.0"}


def _open_browser(host: str, port: int) -> None:
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    threading.Timer(2.0, lambda: webbrowser.open(f"http://{url_host}:{port}")).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="数据洞察 - 轻量级数据可视化分析工具")
    parser.add_argument("--host", default=os.environ.get("DV_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DV_PORT", "5000")))
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args()

    if args.open:
        _open_browser(args.host, args.port)
    print(f"数据洞察已启动：http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
