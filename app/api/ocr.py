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
from app.schemas.ocr import (
    JournalProcessRequest,
    JournalRecognitionResponse,
    JournalReq,
    JournalResponse,
)

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


async def _recognize_photo(req: JournalReq, request: Request) -> journal.JournalRecognition:
    """共享图片校验和线程池识别，资源上下文随工作线程传入。"""
    with document_resources(request) as resources:
        path, img = photo_input(req, resources)
        return await run_in_threadpool(journal.recognize_journal, path, img, req.task_id)


@router.post("/ocr/journal", response_model=JournalResponse)
async def journal_recognize(req: JournalReq, request: Request) -> JournalResponse:
    """顺序执行图片识别与业务生成，复用两个独立入口的同一处理阶段。"""
    sheet = await _recognize_photo(req, request)
    recognized = journal.build_recognition_response(sheet)
    return await journal.generate_journal(
        JournalProcessRequest.model_validate(recognized.data.model_dump()),
        request.app.state.journal_agent.generate,
    )


@router.post("/ocr/journal/recognize", response_model=JournalRecognitionResponse)
async def journal_recognize_only(req: JournalReq, request: Request) -> JournalRecognitionResponse:
    """仅识别：返回完整文字框、原图坐标和拆分前栏目，不调用语言模型。"""
    sheet = await _recognize_photo(req, request)
    return journal.build_recognition_response(sheet)


@router.post("/ocr/journal/process", response_model=JournalResponse)
async def journal_process(req: JournalProcessRequest, request: Request) -> JournalResponse:
    """基于完整 OCR 栏目生成业务日记，不重新识别图片。"""
    return await journal.generate_journal(req, request.app.state.journal_agent.generate)
