"""项目本地 CUDA 运行库：免系统安装，供 onnxruntime-gpu 的 CUDA EP 加载。

onnxruntime-gpu 的 Windows wheel 不附带 CUDA/cuDNN 动态库；把 NVIDIA redist
压缩包（cuda_cudart / libcublas / cudnn 的 windows-x86_64-archive）解压到
Settings.ocr_cuda_root（默认 .cache/cuda，Git 已忽略）后，首次创建 GPU 引擎前
把各包的 bin 目录加入 DLL 搜索路径即可。Linux 部署由系统 CUDA 环境提供动态库，
本模块找不到本地目录时不做任何事，可用性由 probe_cuda 验证。
"""

import os
from pathlib import Path

from app.ocr.core.resources import OCRModelError, OCRResources

CUDA_UNAVAILABLE = (
    "OCR 固定使用 CUDA 推理，但 CUDA 不可用：请安装 CUDA 12 与 cuDNN 9，"
    "或将 redist 包解压到 OCR_CUDA_ROOT 后重试"
)


def enable_local_cuda(root: Path) -> list[Path]:
    """把 root 下各 redist 包的 bin 目录加入 DLL 搜索路径，返回加入的目录（升序）。

    同时前置 PATH，兼容依赖 PATH 解析的间接加载；非 Windows 或目录为空时返回 []。
    """
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if not callable(add_dll_directory):
        return []
    added = sorted(
        d.resolve() for pattern in ("bin", "*/bin") for d in root.glob(pattern) if d.is_dir()
    )
    if not added:
        return []
    for directory in added:
        add_dll_directory(str(directory))
    os.environ["PATH"] = os.pathsep.join([*(str(d) for d in added), os.environ.get("PATH", "")])
    return added


def probe_cuda(models: Path) -> bool | None:
    """用模型目录里已有的任一 ONNX 模型验证 CUDA EP 真实可初始化。

    onnxruntime 在 EP 初始化失败时会静默回退 CPU，所以必须看实际生效的 providers；
    目录里没有模型时返回 None，表示本阶段无法验证（交给 rapidocr 自己的加载流程）。
    """
    candidates = sorted(models.glob("*.onnx"))
    if not candidates:
        return None
    import onnxruntime as ort

    session = ort.InferenceSession(str(candidates[0]), providers=["CUDAExecutionProvider"])
    return "CUDAExecutionProvider" in session.get_providers()


def ensure_cuda_runtime(resources: OCRResources) -> None:
    """接入本地运行库并验证 CUDA 真实可用，否则抛 OCRModelError。"""
    enable_local_cuda(resources.cuda_root)
    import onnxruntime as ort

    if (
        ort.get_device() != "GPU"
        or "CUDAExecutionProvider" not in ort.get_available_providers()
        or probe_cuda(resources.models) is False
    ):
        raise OCRModelError(CUDA_UNAVAILABLE)
