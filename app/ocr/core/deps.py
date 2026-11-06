"""依赖与资源自检：运行库、OCR 推理设备、模板与数据池状态。

只做进程内静态检查：不初始化 OCR 引擎、不加载模型、不注册 CUDA DLL、不写文件。
检查失败通过 ``ok`` / ``warnings`` 表达，调用方不应据此改变 HTTP 状态码。
"""

import importlib
import os
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path
from types import ModuleType

from app.ocr.core.resources import OCRResources

# 能力 → 依赖模块(import 名, 显示名)
CAPS = {
    "PDF(渲染 / 文字层 / 写字 / 拆页)": [("pymupdf", "PyMuPDF")],
    "Excel(单元格 / 合并区)": [("openpyxl", "openpyxl")],
    "图像(灰度 / 轮廓 / 骨架 / SIFT / ORB / HOG)": [("cv2", "OpenCV"), ("numpy", "numpy")],
    "文字识别(手写 / 印刷)": [("rapidocr", "RapidOCR")],
    "模型推理(OCR ONNX)": [("onnxruntime", "onnxruntime")],
}


def _load(name: str) -> ModuleType:
    """可替换的导入入口，便于测试模拟缺失或异常的运行时。"""
    return importlib.import_module(name)


def _version(mod: ModuleType) -> str:
    for attr in ("__version__", "VersionBind", "version"):
        v = getattr(mod, attr, None)
        if isinstance(v, str):
            return v
    try:
        return metadata.version(mod.__name__)
    except Exception:  # noqa: BLE001 —— 取不到版本不影响依赖可用性判断
        return "unknown"


def _imports(mods: Iterable[tuple[str, str]]) -> dict:
    items = []
    for name, label in mods:
        try:
            items.append({"name": label, "ok": True, "version": _version(_load(name))})
        except Exception as exc:  # noqa: BLE001 —— 自检要把任何导入失败都报出来
            # 只保留异常类型，避免把 DLL 路径等运行环境细节写进响应。
            items.append({"name": label, "ok": False, "error": type(exc).__name__})
    return {"ok": all(item["ok"] for item in items), "deps": items}


def _cv_features() -> dict:
    try:
        cv2 = _load("cv2")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}
    return {
        "ok": hasattr(cv2, "SIFT_create") and hasattr(cv2, "ORB_create"),
        "SIFT": hasattr(cv2, "SIFT_create"),
        "ORB": hasattr(cv2, "ORB_create"),
    }


def _distribution(name: str) -> str | None:
    try:
        return metadata.version(name)
    except Exception:  # noqa: BLE001
        return None


def _runtime_label(warnings: list[str]) -> str:
    versions = {
        name: version
        for name in ("onnxruntime", "onnxruntime-gpu")
        if (version := _distribution(name))
    }
    if len(versions) > 1:
        warnings.append("同时安装了 CPU 与 GPU 版 ONNX Runtime，可能互相覆盖")
    if not versions:
        return "unknown"
    return ", ".join(f"{name}=={version}" for name, version in versions.items())


def _inference(resources: OCRResources | None, warnings: list[str]) -> dict:
    configured = resources.device if resources else "unknown"
    try:
        ort = _load("onnxruntime")
        providers = list(ort.get_available_providers())
        device = ort.get_device()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "configured": configured, "error": type(exc).__name__}

    if configured == "cpu":
        ok = "CPUExecutionProvider" in providers
        error = None if ok else "onnxruntime 未提供 CPUExecutionProvider"
    elif configured == "cuda":
        ok = "CUDAExecutionProvider" in providers and device == "GPU"
        error = None if ok else "配置为 cuda，但当前 onnxruntime 未提供 GPU 推理能力"
    else:
        ok = bool(providers)
        error = None if ok else "onnxruntime 未提供可用的执行设备"

    status = {
        "ok": ok,
        "configured": configured,
        "device": device,
        "providers": providers,
        "runtime": _runtime_label(warnings),
        "note": "只验证 provider 与配置一致；CUDA 真实初始化在首次 OCR 时验证",
    }
    if error is not None:
        status["error"] = error
    return status


def _writable(path: Path) -> bool:
    """不创建目录，只检查最近的已存在路径是否可写。"""
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate.exists() and os.access(candidate, os.W_OK)


def _templates_cap(resources: OCRResources) -> dict:
    try:
        forms = resources.load("forms/files.json")["forms"]
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}
    return {"ok": True, "forms": len(forms)}


def _layouts_cap(resources: OCRResources) -> dict:
    status: dict[str, object] = {"ok": True}
    for kind in ("jb12", "book1"):
        try:
            status[kind] = len(resources.load(f"layouts/{kind}.json")["forms"])
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": type(exc).__name__}
    return status


def _wbs_rules_cap(resources: OCRResources) -> dict:
    try:
        resources.load("refs/wbs_rules.json")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}
    return {"ok": True}


def _models_cap(resources: OCRResources, warnings: list[str]) -> dict:
    model_root = resources.models
    if model_root.exists() and not model_root.is_dir():
        return {"ok": False, "files": 0, "writable": False, "error": "OCR 模型路径不是目录"}
    files = len(list(model_root.rglob("*.onnx"))) if model_root.is_dir() else 0
    writable = _writable(model_root)
    ok = files > 0 or writable
    status = {"ok": ok, "files": files, "writable": writable}
    if not ok:
        status["error"] = "OCR 模型目录不可用且父目录不可写"
    elif files == 0:
        warnings.append("OCR 模型目录为空：开发环境首次识别会尝试下载，离线部署需预置模型文件")
    return status


def _ocr_resources(resources: OCRResources | None, warnings: list[str]) -> dict:
    if resources is None:
        return {"ok": False, "error": "应用资源未初始化"}

    templates = _templates_cap(resources)
    layouts = _layouts_cap(resources)
    wbs_rules = _wbs_rules_cap(resources)
    models = _models_cap(resources, warnings)
    projects: dict[str, object] = {"ok": resources.projects.is_dir()}
    if not projects["ok"]:
        projects["error"] = "PROJECTS_ROOT 不存在或不是目录"
    admin = {"ok": resources.admin.is_dir()}
    assets = {"ok": resources.assets.is_dir()}
    if not admin["ok"]:
        warnings.append("ADMIN_ROOT 不存在；表样 PDF 和管理端资源可能不可用")
    if not assets["ok"]:
        warnings.append("ASSET_ROOT 不存在；规范资料和表样 PDF 可能不可用")

    ok = all(item["ok"] for item in (templates, layouts, wbs_rules, models, projects))
    return {
        "ok": ok,
        "templates": templates,
        "layouts": layouts,
        "wbs_rules": wbs_rules,
        "models": models,
        "projects": projects,
        "admin": admin,
        "assets": assets,
    }


def check(resources: OCRResources | None = None) -> dict:
    warnings: list[str] = []
    capabilities = {cap: _imports(mods) for cap, mods in CAPS.items()}
    capabilities["OpenCV 特征"] = _cv_features()
    capabilities["推理设备"] = _inference(resources, warnings)
    capabilities["OCR 资源"] = _ocr_resources(resources, warnings)
    return {
        "ok": all(item["ok"] for item in capabilities.values()),
        "warnings": warnings,
        "caps": capabilities,
    }
