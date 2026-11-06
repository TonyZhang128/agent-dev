"""本机 RapidOCR 引擎：单例加载、全局推理锁、模型缺失统一报 OCRModelError（无业务）。"""

from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import numpy as np

from app.ocr.core import cuda_runtime
from app.ocr.core.resources import OCRModelError, get_resources

if TYPE_CHECKING:
    from rapidocr import RapidOCR

MODEL_UNAVAILABLE = "OCR 模型不可用，请检查 OCR_MODEL_ROOT 是否已准备模型文件；开发环境该目录需可写"


class OCRBox(TypedDict):
    """单条 OCR 结果：文字、像素外接框与置信度。"""

    s: str
    box: list[float]
    conf: float


def rapidocr_params(model_root: Path, use_cuda: bool = True) -> dict[str, object]:
    """识别质量优先:PP-OCRv6 Medium 做检测与识别,PP-OCRv5 Server 做方向分类。
    模型首次使用时由 rapidocr 下载到 model_root,离线部署需提前放入该目录。
    use_cuda=True 时固定启用 onnxruntime CUDA EP,use_cuda=False 时走 CPU 推理;
    线程数固定为 1,避免并发请求互相争抢。"""
    from rapidocr import ModelType, OCRVersion

    params = {
        "Global.model_root_dir": str(model_root),
        "Det.model_type": ModelType.MEDIUM,
        "Det.ocr_version": OCRVersion.PPOCRV6,
        "Rec.model_type": ModelType.MEDIUM,
        "Rec.ocr_version": OCRVersion.PPOCRV6,
        "Cls.model_type": ModelType.SERVER,
        "Cls.ocr_version": OCRVersion.PPOCRV5,
        "EngineConfig.onnxruntime.intra_op_num_threads": 1,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.use_cuda": use_cuda,
    }
    if use_cuda:
        params["EngineConfig.onnxruntime.cuda_ep_cfg"] = {"device_id": 0}
    return params


def engine() -> "RapidOCR":
    """每个应用首次使用时载入 RapidOCR；调用方持有资源锁。
    cuda 模式先验证 CUDA 运行库,cpu 模式直接使用 CPU 推理。"""
    resources = get_resources()
    if resources.engine is None:
        from rapidocr import RapidOCR

        use_cuda = resources.device == "cuda"
        try:
            if use_cuda:
                cuda_runtime.ensure_cuda_runtime(resources)
            resources.engine = RapidOCR(params=rapidocr_params(resources.models, use_cuda=use_cuda))
        except OCRModelError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 模型缺失、下载失败或依赖不可用统一视为模型不可用
            raise OCRModelError(MODEL_UNAVAILABLE) from exc
    return resources.engine


def ocr(img: np.ndarray) -> list[OCRBox]:
    """单图 OCR → [{s, box:[x0,y0,x1,y1](像素), conf}];模型不可用时抛 OCRModelError。"""
    with get_resources().lock:
        try:
            res = engine()(img)
        except OCRModelError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 模型文件缺失或下载失败发生在首次推理时
            raise OCRModelError(MODEL_UNAVAILABLE) from exc
    if res.boxes is None:
        return []
    out: list[OCRBox] = []
    for pts, s, conf in zip(res.boxes, res.txts or (), res.scores or (), strict=True):
        xs, ys = [float(p[0]) for p in pts], [float(p[1]) for p in pts]
        out.append({"s": s, "box": [min(xs), min(ys), max(xs), max(ys)], "conf": float(conf)})
    return out
