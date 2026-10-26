"""应用配置。"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 可通过环境变量把运行数据放到其他目录（测试时会用到）
DATA_DIR = Path(os.environ.get("DV_DATA_DIR", BASE_DIR / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATASET_DIR = DATA_DIR / "datasets"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "app.db"

SAMPLE_DIR = BASE_DIR / "sample_data"
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

SECRET_KEY = os.environ.get("DV_SECRET_KEY") or secrets.token_hex(16)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_ROWS = 200_000
PREVIEW_ROWS = 8
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

ALLOWED_EXTENSIONS = {".csv", ".xlsx"}

# 朴素、低饱和的图表配色（Tableau muted）
CHART_PALETTE = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
]

ENCODING_CHOICES = [
    ("auto", "自动识别"),
    ("utf-8", "UTF-8"),
    ("utf-8-sig", "UTF-8（含 BOM）"),
    ("gb18030", "GB18030 / GBK"),
    ("big5", "Big5"),
    ("latin-1", "Latin-1"),
]

DELIMITER_CHOICES = [
    (",", "逗号 ,"),
    (";", "分号 ;"),
    ("\t", "制表符 Tab"),
    ("|", "竖线 |"),
]

LOG_TYPES = [
    "上传",
    "去重",
    "填充",
    "删除列",
    "类型转换",
    "筛选",
    "排序",
    "导出",
    "图表导出",
    "撤销",
    "重置",
    "删除数据集",
]


def ensure_dirs() -> None:
    for directory in (DATA_DIR, UPLOAD_DIR, DATASET_DIR, EXPORT_DIR):
        directory.mkdir(parents=True, exist_ok=True)
