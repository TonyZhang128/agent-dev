"""依赖自检:各处理能力用到的库是否可用。每类功能只有一个包(见 pyproject.toml)。
运行依赖统一由 pyproject.toml 与 uv.lock 管理。"""

import importlib
from importlib import metadata

# 能力 → 依赖模块(import 名, 显示名)
CAPS = {
    "PDF(渲染 / 文字层 / 写字 / 拆页)": [("pymupdf", "PyMuPDF")],
    "Excel(单元格 / 合并区)": [("openpyxl", "openpyxl")],
    "图像(灰度 / 轮廓 / 骨架 / SIFT / ORB / HOG)": [("cv2", "OpenCV"), ("numpy", "numpy")],
    "文字识别(手写 / 印刷)": [("rapidocr", "RapidOCR")],
    "模型推理(OCR ONNX)": [("onnxruntime", "onnxruntime")],
}


def _version(mod) -> str:
    for attr in ("__version__", "VersionBind", "version"):
        v = getattr(mod, attr, None)
        if isinstance(v, str):
            return v
    try:
        return metadata.version(mod.__name__)
    except Exception:  # noqa: BLE001 —— 取不到版本不影响依赖可用性判断
        return "ok"


def check() -> dict:
    out = {}
    for cap, mods in CAPS.items():
        items = []
        for name, label in mods:
            try:
                m = importlib.import_module(name)
                items.append({"name": label, "ok": True, "version": _version(m)})
            except Exception as e:  # noqa: BLE001 —— 自检要把任何导入失败都报出来
                items.append({"name": label, "ok": False, "error": f"{type(e).__name__}: {e}"})
        out[cap] = {"ok": all(i["ok"] for i in items), "deps": items}
    try:
        import cv2

        out["OpenCV 特征"] = {
            "ok": hasattr(cv2, "SIFT_create") and hasattr(cv2, "ORB_create"),
            "SIFT": hasattr(cv2, "SIFT_create"),
            "ORB": hasattr(cv2, "ORB_create"),
        }
    except Exception as e:  # noqa: BLE001
        out["OpenCV 特征"] = {"ok": False, "error": str(e)}
    try:
        import onnxruntime as ort

        out["推理设备"] = {"ok": True, "providers": ort.get_available_providers()}
    except Exception as e:  # noqa: BLE001
        out["推理设备"] = {"ok": False, "error": str(e)}
    return out
