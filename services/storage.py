"""数据集持久化：元数据 JSON + 每个版本的 Pickle 文件。"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import config

_ID_PATTERN = re.compile(r"^[0-9a-f]{12}$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _version_entry(version: int, label: str, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "version": int(version),
        "label": label,
        "time": _now(),
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "missing": int(frame.isna().sum().sum()),
    }


class Dataset:
    def __init__(self, directory: Path, meta: dict[str, Any], frame: pd.DataFrame):
        self.directory = directory
        self.meta = meta
        self.df = frame
        self._view_key: str | None = None
        self._view_frame: pd.DataFrame | None = None
        self._profile_key: str | None = None
        self._profile_value: list[dict[str, Any]] | None = None

    @property
    def id(self) -> str:
        return str(self.meta["id"])

    @property
    def file_name(self) -> str:
        return str(self.meta.get("file_name") or "未命名")

    def invalidate_view(self) -> None:
        self._view_key = None
        self._view_frame = None
        self._profile_key = None
        self._profile_value = None

    def view(self) -> pd.DataFrame:
        from services.filters import apply_view

        key = json.dumps(
            {
                "version": self.meta.get("version"),
                "filters": self.meta.get("filters", []),
                "logic": self.meta.get("logic", "AND"),
                "sorts": self.meta.get("sorts", []),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if self._view_key == key and self._view_frame is not None:
            return self._view_frame
        frame = apply_view(
            self.df,
            self.meta.get("filters", []),
            self.meta.get("logic", "AND"),
            self.meta.get("sorts", []),
        )
        self._view_key = key
        self._view_frame = frame
        return frame

    def profile(self) -> list[dict[str, Any]]:
        from services.serialize import column_profile

        frame = self.view()
        key = f"{self.meta.get('version')}:{len(frame)}:{self._view_key}"
        if self._profile_key == key and self._profile_value is not None:
            return self._profile_value
        self._profile_key = key
        self._profile_value = column_profile(frame)
        return self._profile_value


class DatasetStore:
    def __init__(self, root: Path, cache_size: int = 4):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._cache: OrderedDict[str, Dataset] = OrderedDict()
        self._cache_size = cache_size

    def _dir(self, dataset_id: str) -> Path:
        return self.root / dataset_id

    def create(
        self,
        frame: pd.DataFrame,
        *,
        name: str,
        file_name: str,
        kind: str,
        sheet: str | None = None,
        encoding: str | None = None,
        delimiter: str | None = None,
        header_row: int = 1,
        has_header: bool = True,
    ) -> Dataset:
        with self.lock:
            dataset_id = uuid.uuid4().hex[:12]
            directory = self._dir(dataset_id)
            directory.mkdir(parents=True, exist_ok=True)
            frame = frame.reset_index(drop=True)
            frame.to_pickle(directory / "v0.pkl")

            clean_name = re.sub(r"\s+", " ", name or file_name).strip() or "未命名数据集"
            meta: dict[str, Any] = {
                "id": dataset_id,
                "name": clean_name[:80],
                "file_name": file_name,
                "kind": kind,
                "sheet": sheet,
                "encoding": encoding,
                "delimiter": delimiter,
                "header_row": header_row,
                "has_header": has_header,
                "created_at": _now(),
                "updated_at": _now(),
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "missing_cells": int(frame.isna().sum().sum()),
                "version": 0,
                "versions": [_version_entry(0, "原始数据", frame)],
                "filters": [],
                "logic": "AND",
                "sorts": [],
                "chart": None,
            }
            _atomic_json(directory / "meta.json", meta)
            dataset = Dataset(directory, meta, frame)
            self._remember(dataset)
            return dataset

    def get(self, dataset_id: str) -> Dataset | None:
        if not dataset_id or not _ID_PATTERN.match(dataset_id):
            return None
        with self.lock:
            cached = self._cache.get(dataset_id)
            if cached is not None:
                self._cache.move_to_end(dataset_id)
                return cached

            directory = self._dir(dataset_id)
            meta_path = directory / "meta.json"
            if not meta_path.exists():
                return None
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                version = int(meta.get("version", 0))
                frame = pd.read_pickle(directory / f"v{version}.pkl")
            except (OSError, ValueError, json.JSONDecodeError):
                return None
            dataset = Dataset(directory, meta, frame)
            self._remember(dataset)
            return dataset

    def _remember(self, dataset: Dataset) -> None:
        self._cache[dataset.id] = dataset
        self._cache.move_to_end(dataset.id)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    def save_meta(self, dataset: Dataset) -> None:
        with self.lock:
            dataset.meta["updated_at"] = _now()
            _atomic_json(dataset.directory / "meta.json", dataset.meta)

    def _write_frame(self, dataset: Dataset, version: int) -> None:
        target = dataset.directory / f"v{version}.pkl"
        temp = dataset.directory / f"v{version}.pkl.tmp"
        dataset.df.to_pickle(temp)
        os.replace(temp, target)

    def _refresh_counts(self, dataset: Dataset) -> None:
        dataset.meta["row_count"] = int(len(dataset.df))
        dataset.meta["column_count"] = int(len(dataset.df.columns))
        dataset.meta["missing_cells"] = int(dataset.df.isna().sum().sum())
        dataset.meta["updated_at"] = _now()

    def commit(self, dataset: Dataset, label: str) -> dict[str, Any]:
        """保存清洗后的新版本。"""
        with self.lock:
            version = int(dataset.meta.get("version", 0)) + 1
            dataset.meta["version"] = version
            self._refresh_counts(dataset)
            self._write_frame(dataset, version)
            versions = [
                entry
                for entry in dataset.meta.get("versions", [])
                if int(entry.get("version", -1)) < version
            ]
            versions.append(_version_entry(version, label, dataset.df))
            dataset.meta["versions"] = versions
            self.save_meta(dataset)
            dataset.invalidate_view()
            return _version_entry(version, label, dataset.df)

    def undo(self, dataset: Dataset) -> bool:
        with self.lock:
            version = int(dataset.meta.get("version", 0))
            if version <= 0:
                return False
            version -= 1
            frame = pd.read_pickle(dataset.directory / f"v{version}.pkl")
            dataset.df = frame
            dataset.meta["version"] = version
            self._refresh_counts(dataset)
            dataset.meta["versions"] = [
                entry
                for entry in dataset.meta.get("versions", [])
                if int(entry.get("version", -1)) <= version
            ]
            self.sanitize_state(dataset)
            self.save_meta(dataset)
            dataset.invalidate_view()
            for stale in dataset.directory.glob("v*.pkl"):
                match = re.fullmatch(r"v(\d+)\.pkl", stale.name)
                if match and int(match.group(1)) > version:
                    stale.unlink(missing_ok=True)
            return True

    def reset(self, dataset: Dataset) -> bool:
        with self.lock:
            if int(dataset.meta.get("version", 0)) == 0:
                dataset.meta["filters"] = []
                dataset.meta["logic"] = "AND"
                dataset.meta["sorts"] = []
                dataset.meta["chart"] = None
                self.save_meta(dataset)
                dataset.invalidate_view()
                return False
            frame = pd.read_pickle(dataset.directory / "v0.pkl")
            dataset.df = frame
            dataset.meta["version"] = 0
            dataset.meta["filters"] = []
            dataset.meta["logic"] = "AND"
            dataset.meta["sorts"] = []
            dataset.meta["chart"] = None
            self._refresh_counts(dataset)
            dataset.meta["versions"] = [
                entry
                for entry in dataset.meta.get("versions", [])
                if int(entry.get("version", -1)) == 0
            ]
            if not dataset.meta["versions"]:
                dataset.meta["versions"] = [_version_entry(0, "原始数据", frame)]
            self.save_meta(dataset)
            dataset.invalidate_view()
            for stale in dataset.directory.glob("v*.pkl"):
                match = re.fullmatch(r"v(\d+)\.pkl", stale.name)
                if match and int(match.group(1)) > 0:
                    stale.unlink(missing_ok=True)
            return True

    def sanitize_state(self, dataset: Dataset) -> None:
        columns = set(str(column) for column in dataset.df.columns)
        dataset.meta["filters"] = [
            item
            for item in dataset.meta.get("filters", [])
            if str(item.get("column")) in columns
        ]
        dataset.meta["sorts"] = [
            item
            for item in dataset.meta.get("sorts", [])
            if str(item.get("column")) in columns
        ]
        chart = dataset.meta.get("chart")
        if chart:
            if str(chart.get("x")) not in columns:
                dataset.meta["chart"] = None
            else:
                chart["y"] = [name for name in chart.get("y", []) if str(name) in columns]
                if not chart["y"]:
                    dataset.meta["chart"] = None

    def delete(self, dataset_id: str) -> bool:
        if not _ID_PATTERN.match(dataset_id or ""):
            return False
        with self.lock:
            self._cache.pop(dataset_id, None)
            directory = self._dir(dataset_id)
            if not directory.exists():
                return False
            for item in sorted(directory.glob("*"), reverse=True):
                try:
                    item.unlink()
                except OSError:
                    pass
            try:
                directory.rmdir()
            except OSError:
                return False
            return True

    def recent(self, limit: int = 6) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        with self.lock:
            for meta_path in self.root.glob("*/meta.json"):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                items.append(meta)
        items.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return items[:limit]

    def count(self) -> int:
        return len(list(self.root.glob("*/meta.json")))


store = DatasetStore(config.DATASET_DIR)
