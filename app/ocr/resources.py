"""按应用隔离 OCR 资源；导入时不读取外部模板或初始化模型。"""

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any

from app.config import Settings


class OCRResourceError(Exception):
    """模板库未配置、不可读或格式不正确。"""


class OCRModelError(Exception):
    """文字识别模型初始化或模型文件下载失败。"""


class OCRResources:
    def __init__(self, settings: Settings) -> None:
        self.templates = settings.templates_root
        self.admin = settings.admin_root
        self.assets = settings.asset_root
        self.projects = settings.projects_root
        self.models = settings.ocr_model_root
        self.engine: Any = None
        self.lock = threading.Lock()
        self.caches: dict[Callable, Callable] = {}
        self._json: dict[str, dict] = {}

    def close(self) -> None:
        """释放 ONNX 会话引用和模板缓存；应用停止后不保留昂贵资源。"""
        self.engine = None
        self.caches.clear()
        self._json.clear()

    def load(self, relative: str) -> dict:
        if relative not in self._json:
            try:
                data = json.loads((self.templates / relative).read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("模板必须为 JSON 对象")
                if relative.startswith(("forms/", "layouts/")) and not isinstance(
                    data.get("forms"), dict
                ):
                    raise ValueError("模板缺少 forms 对象")
            except (OSError, ValueError) as exc:
                raise OCRResourceError(
                    f"OCR 模板不可用，请检查 TEMPLATES_ROOT 下的 {relative}"
                ) from exc
            self._json[relative] = data
        return self._json[relative]

    def asset(self, relative: str) -> Path:
        """管理端优先，再查规范资料；兼容模板记录的旧目录名。"""
        for root in (self.admin, self.assets):
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("模板资源路径必须位于配置目录内")
            if path.exists():
                return path
        parts = relative.split("/")
        rename_file = self.templates / "library/pdf_dirs.json"
        if len(parts) > 2 and parts[0] == "pdf" and rename_file.is_file():
            books = self.load("library/pdf_dirs.json").get("books", {})
            for book in books.values():
                if book.get("old") == parts[1] and book.get("dir"):
                    path = (self.assets / "pdf" / book["dir"] / Path(*parts[2:])).resolve()
                    if path.is_relative_to(self.assets) and path.exists():
                        return path
        return self.assets / relative


_current: ContextVar[OCRResources | None] = ContextVar("ocr_resources", default=None)


def get_resources() -> OCRResources:
    """HTTP 显式绑定应用资源；CLI 在自己的上下文中按需创建。"""
    resources = _current.get()
    if resources is None:
        resources = OCRResources(Settings())
        _current.set(resources)
    return resources


@contextmanager
def use_resources(resources: OCRResources) -> Iterator[None]:
    token = _current.set(resources)
    try:
        yield
    finally:
        _current.reset(token)


def resource_cache(maxsize: int = 128) -> Callable:
    """缓存随应用资源释放，表号相同而资料不同的应用互不串用。"""

    def decorate(function: Callable) -> Callable:
        @wraps(function)
        def wrapped(*args, **kwargs):
            resources = get_resources()
            cached = resources.caches.setdefault(function, lru_cache(maxsize=maxsize)(function))
            return cached(*args, **kwargs)

        return wrapped

    return decorate


def forms() -> dict:
    return get_resources().load("forms/files.json")["forms"]


def asset(relative: str) -> Path:
    return get_resources().asset(relative)
