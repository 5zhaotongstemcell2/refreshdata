"""依赖路径兼容层。

正常情况下直接使用 ``pip install -r requirements.txt`` 安装的依赖。
在部分 Windows 环境里，Python 解释器与已安装的第三方包位于不同目录，
此时本模块会在启动阶段把可用的 site-packages 追加到 sys.path 末尾
（追加而非前置，避免覆盖标准库模块）。
"""
from __future__ import annotations

import glob
import importlib.util
import os
import sys

REQUIRED_MODULES = ("flask", "pandas", "numpy", "matplotlib", "openpyxl")

_checked = False


def _missing_modules() -> list[str]:
    missing: list[str] = []
    for name in REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def _candidate_paths():
    explicit = os.environ.get("DV_EXTRA_SITE")
    if explicit:
        yield explicit

    version = sys.version_info
    tag = f"Python{version.major}{version.minor}"
    dotted = f"python{version.major}.{version.minor}"

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        patterns = (
            os.path.join(
                local_app_data,
                "Packages",
                "PythonSoftwareFoundation.Python.*",
                "LocalCache",
                "local-packages",
                tag,
                "site-packages",
            ),
            os.path.join(local_app_data, "Programs", "Python", tag, "Lib", "site-packages"),
        )
        for pattern in patterns:
            for path in sorted(glob.glob(pattern), reverse=True):
                yield path

    for pattern in (
        f"/usr/local/lib/{dotted}/site-packages",
        "/usr/lib/python3/dist-packages",
    ):
        for path in sorted(glob.glob(pattern), reverse=True):
            yield path


def ensure_dependencies() -> None:
    """尽量补齐缺失依赖的搜索路径；找不到时保留原始 ImportError。"""
    global _checked
    if _checked:
        return
    _checked = True

    if not _missing_modules():
        return

    for path in _candidate_paths():
        if not path or not os.path.isdir(path) or path in sys.path:
            continue
        sys.path.append(path)
        importlib.invalidate_caches()
        if not _missing_modules():
            return
