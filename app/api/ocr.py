"""现场照片、监理日志、简表与填表接口；CPU 操作由同步路由在线程池执行。"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import cv2
import pymupdf
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.ocr import daily_logs, journal
from app.ocr.core.resources import (
    OCRModelError,
    OCRResourceError,
    OCRResources,
    forms,
    use_resources,
)
from app.ocr.form import form_ocr
from app.ocr.jianbiao.fill import compute
from app.ocr.jianbiao.recognize import run
from app.ocr.sheets import grid
from app.schemas.ocr import DailyLogsReq, FillReq, JianbiaoReq, JournalReq, RecognizeReq

router = APIRouter(tags=["ocr"])

DEFAULT_BLANK_WIDTH = 1400
MAX_BLANK_WIDTH = 2400
BLANK_CACHE_SECONDS = 3600

PhotoRequest = RecognizeReq | DailyLogsReq | JournalReq | JianbiaoReq


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


def project_path(resources: OCRResources, relative: str, *, output: bool = False) -> Path:
    relative = relative.removeprefix("projects/")
    path = (resources.projects / relative).resolve()
    if not relative or Path(relative).is_absolute() or not path.is_relative_to(resources.projects):
        raise HTTPException(400, "文件路径必须位于 PROJECTS_ROOT 数据池内")
    if output:
        if path.suffix.lower() != ".pdf":
            raise HTTPException(400, "输出文件必须为 PDF，相应 Excel 使用同名 .xlsx")
        # 同名伴生文件也需要检查，避免预先存在的符号链接越界写入。
        if any(
            not path.with_suffix(suffix).resolve().is_relative_to(resources.projects)
            for suffix in (".xlsx", ".warp.jpg")
        ):
            raise HTTPException(400, "输出文件必须位于 PROJECTS_ROOT 数据池内")
    elif not path.exists():
        raise HTTPException(400, "数据池内的输入文件不存在")
    return path


def relative_outputs(result: dict, resources: OCRResources) -> dict:
    """把数据池内的绝对输出路径转换为相对路径，返回新字典，不修改入参。"""
    converted = dict(result)
    for key in ("pdf", "xlsx"):
        if converted.get(key):
            converted[key] = (
                Path(converted[key]).resolve().relative_to(resources.projects).as_posix()
            )
    return converted


def photo_input(req: PhotoRequest, resources: OCRResources) -> tuple[Path | None, str]:
    """base64 图片优先；否则校验并返回数据池内的照片路径。"""
    if req.img:
        return None, req.img
    path = project_path(resources, req.path)
    if not path.is_file():
        raise HTTPException(400, "照片必须为数据池内的文件")
    return path, ""


def elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


@router.post("/ocr/recognize", response_model=None)
def recognize(req: RecognizeReq, request: Request) -> dict:
    with document_resources(request) as resources:
        started = time.monotonic()
        path, img = photo_input(req, resources)
        result = form_ocr.recognize(path, req.form.strip(), img)
        result["ms"] = elapsed_ms(started)
        return {"status": 200, "data": result}


@router.post("/ocr/daily-logs", response_model=None)
def daily_logs_recognize(req: DailyLogsReq, request: Request) -> dict:
    with document_resources(request) as resources:
        started = time.monotonic()
        path, img = photo_input(req, resources)
        result = daily_logs.run(path, img, req.task_id)
        result["ms"] = elapsed_ms(started)
        return {"status": 200, "data": result}


@router.post("/ocr/daily-logs-new", response_model=None)
def journal_recognize(req: JournalReq, request: Request) -> dict:
    """新版监理日志识别：单次整页 OCR + 固定栏目匹配，不读取旧识别链。"""
    with document_resources(request) as resources:
        started = time.monotonic()
        path, img = photo_input(req, resources)
        result = journal.read_photo(path, img, req.task_id)
        result["ms"] = elapsed_ms(started)
        return {"status": 200, "data": result}


@router.post("/ocr/jianbiao", response_model=None)
def jianbiao_fill(req: JianbiaoReq, request: Request) -> dict:
    with document_resources(request) as resources:
        output = project_path(resources, req.out, output=True) if req.out else None
        started = time.monotonic()
        path, img = photo_input(req, resources)
        result = run(path, req.form.strip(), req.cfg, req.bound, output, img)
        result["ms"] = elapsed_ms(started)
        return {"status": 200, "data": relative_outputs(result, resources)}


@router.post("/ocr/fill", response_model=None)
def fill(req: FillReq, request: Request) -> dict:
    with document_resources(request) as resources:
        output = project_path(resources, req.out, output=True) if req.out else None
        result = compute(req.form.strip(), req.cfg, req.values, output, req.rects)
        return {"status": 200, "data": relative_outputs(result, resources)}


@router.get("/ocr/blank/{form}.png")
def blank(
    form: str,
    request: Request,
    width: Annotated[int, Query(ge=1)] = DEFAULT_BLANK_WIDTH,
) -> Response:
    with document_resources(request) as resources:
        template = forms().get(form.strip()) or {}
        if not template.get("pdf"):
            raise HTTPException(404, f"模板库没有 {form} 的表样 PDF")
        with pymupdf.open(resources.asset(template["pdf"][0])) as document:
            page = document[0]
            scale = min(width, MAX_BLANK_WIDTH) / page.rect.width
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return Response(
                pixmap.tobytes("png"),
                media_type="image/png",
                headers={"Cache-Control": f"max-age={BLANK_CACHE_SECONDS}"},
            )


@router.get("/ocr/sheet/{form}", response_model=None)
def sheet(form: str, request: Request) -> dict:
    with document_resources(request):
        if not (forms().get(form.strip()) or {}).get("pdf"):
            raise HTTPException(404, f"模板库没有 {form} 的表样 PDF")
        return {"status": 200, "data": grid.sheet(form.strip())}
