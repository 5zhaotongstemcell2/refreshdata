"""SQLite 历史记录（按文档要求只使用一张表）。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS operation_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name      TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    operation_time TEXT NOT NULL,
    detail         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_operation_log_time ON operation_log(operation_time DESC);
CREATE INDEX IF NOT EXISTS idx_operation_log_type ON operation_log(operation_type);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    config.ensure_dirs()
    with _connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")


def log_operation(file_name: str, operation_type: str, detail: dict[str, Any] | None = None) -> int:
    detail_text = json.dumps(detail or {}, ensure_ascii=False, default=str)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO operation_log (file_name, operation_type, operation_time, detail) "
            "VALUES (?, ?, ?, ?)",
            (file_name or "未命名", operation_type, timestamp, detail_text),
        )
        return int(cursor.lastrowid or 0)


def _build_where(
    operation_type: str | None,
    keyword: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if operation_type:
        clauses.append("operation_type = ?")
        params.append(operation_type)
    if keyword:
        clauses.append("(file_name LIKE ? OR detail LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like])
    if date_from:
        clauses.append("operation_time >= ?")
        params.append(f"{date_from} 00:00:00")
    if date_to:
        clauses.append("operation_time <= ?")
        params.append(f"{date_to} 23:59:59")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_logs(
    page: int = 1,
    per_page: int = 20,
    operation_type: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    page = max(1, int(page))
    per_page = max(1, min(100, int(per_page)))
    where, params = _build_where(operation_type, keyword, date_from, date_to)

    with _connect() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM operation_log{where}", params).fetchone()[0])
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        rows = conn.execute(
            f"SELECT id, file_name, operation_type, operation_time, detail "
            f"FROM operation_log{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, per_page, (page - 1) * per_page],
        ).fetchall()

    items = []
    for row in rows:
        try:
            detail = json.loads(row["detail"])
        except (TypeError, json.JSONDecodeError):
            detail = {}
        items.append(
            {
                "id": row["id"],
                "file_name": row["file_name"],
                "operation_type": row["operation_type"],
                "operation_time": row["operation_time"],
                "detail": detail,
            }
        )
    return {"items": items, "total": total, "pages": pages, "page": page, "per_page": per_page}


def get_stats() -> dict[str, Any]:
    with _connect() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0])
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM operation_log WHERE operation_time LIKE ?",
                (f"{today}%",),
            ).fetchone()[0]
        )
        rows = conn.execute(
            "SELECT operation_type, COUNT(*) AS n FROM operation_log GROUP BY operation_type"
        ).fetchall()
    by_type = {row["operation_type"]: int(row["n"]) for row in rows}
    uploads = by_type.get("上传", 0)
    cleans = sum(
        by_type.get(key, 0) for key in ("去重", "填充", "删除列", "类型转换", "筛选", "排序")
    )
    exports = by_type.get("导出", 0) + by_type.get("图表导出", 0)
    return {
        "total": total,
        "today": today_count,
        "uploads": uploads,
        "cleans": cleans,
        "exports": exports,
        "by_type": by_type,
    }


def distinct_types() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT operation_type FROM operation_log ORDER BY operation_type"
        ).fetchall()
    return [row["operation_type"] for row in rows]


def clear_logs() -> int:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM operation_log")
        return int(cursor.rowcount or 0)


def recent_logs(limit: int = 8) -> list[dict[str, Any]]:
    result = list_logs(page=1, per_page=limit)
    return result["items"]


def database_size() -> int:
    path = Path(config.DB_PATH)
    return path.stat().st_size if path.exists() else 0
