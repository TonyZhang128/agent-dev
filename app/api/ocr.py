"""新版监理日志识别接口；OCR 等 CPU 操作由同步路由在线程池执行。"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import cv2
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.ocr import journal
from app.ocr.core.resources import (
    OCRModelError,
    OCRResourceError,
    OCRResources,
    use_resources,
)
from app.schemas.ocr import JournalReq

router = APIRouter(tags=["ocr"])


@contextmanager
def document_resources(request: Request) -> Generator[OCRResources, None, None]:
    resources = request.app.state.ocr_resources
    with use_resources(resources):
        try:
            yield resources
        except OCRResourceError as exc:
            raise HTTPException(503, str(exc)) from exc
        except OCRModelError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except (OSError, RuntimeError, cv2.error) as exc:
            raise HTTPException(400, "文档处理失败，请检查输入文件及模板资源") from exc


def project_path(resources: OCRResources, relative: str) -> Path:
    relative = relative.removeprefix("projects/")
    path = (resources.projects / relative).resolve()
    if not relative or Path(relative).is_absolute() or not path.is_relative_to(resources.projects):
        raise HTTPException(400, "文件路径必须位于 PROJECTS_ROOT 数据池内")
    if not path.exists():
        raise HTTPException(400, "数据池内的输入文件不存在")
    return path


def photo_input(req: JournalReq, resources: OCRResources) -> tuple[Path | None, str]:
    """base64 图片优先；否则校验并返回数据池内的照片路径。"""
    if req.img:
        return None, req.img
    path = project_path(resources, req.path)
    if not path.is_file():
        raise HTTPException(400, "照片必须为数据池内的文件")
    return path, ""


@router.post("/ocr/daily-logs-new", response_model=None)
async def journal_recognize(req: JournalReq, request: Request) -> dict:
    """新版监理日志识别：整页OCR后按关键词提取，必要时由Agent基于完整mainWork生成三部分。"""
    with document_resources(request) as resources:
        path, img = photo_input(req, resources)
        # 同步 OCR 在线程池执行；文档资源 ContextVar 随线程上下文传入。
        sheet = await run_in_threadpool(journal.recognize_journal, path, img, req.task_id)
    outcome = await journal.split_main_work(
        sheet.readings, request.app.state.main_work_agent.generate
    )
    data = journal.build_processed_payload(sheet, outcome.values)
    return {"status": 200, "message": "识别完成", "data": data}
