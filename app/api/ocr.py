"""现场照片、简表与填表接口；CPU 操作由同步路由在线程池执行。"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import cv2
import pymupdf
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.ocr import deps, form_ocr, grid, jianbiao
from app.ocr.resources import (
    OCRModelError,
    OCRResourceError,
    OCRResources,
    forms,
    use_resources,
)
from app.ocr.schemas import FillReq, JianbiaoReq, RecognizeReq

router = APIRouter(tags=["ocr"])


@contextmanager
def document_resources(request: Request) -> Iterator[OCRResources]:
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
    for key in ("pdf", "xlsx"):
        if result.get(key):
            result[key] = Path(result[key]).resolve().relative_to(resources.projects).as_posix()
    return result


@router.get("/health/deps")
def health_deps():
    capabilities = deps.check()
    return {
        "status": 200,
        "data": {"ok": all(item["ok"] for item in capabilities.values()), "caps": capabilities},
    }


@router.post("/ocr/recognize")
def recognize(req: RecognizeReq, request: Request):
    with document_resources(request) as resources:
        path = project_path(resources, req.path)
        if not path.is_file():
            raise HTTPException(400, "照片必须为数据池内的文件")
        started = time.monotonic()
        result = form_ocr.recognize(path, req.form.strip())
        result["ms"] = round((time.monotonic() - started) * 1000)
        return {"status": 200, "data": result}


@router.post("/ocr/jianbiao")
def jianbiao_fill(req: JianbiaoReq, request: Request):
    with document_resources(request) as resources:
        path = project_path(resources, req.path)
        if not path.is_file():
            raise HTTPException(400, "照片必须为数据池内的文件")
        output = project_path(resources, req.out, output=True) if req.out else None
        started = time.monotonic()
        result = jianbiao.run(path, req.form.strip(), req.cfg, req.bound, output)
        result["ms"] = round((time.monotonic() - started) * 1000)
        return {"status": 200, "data": relative_outputs(result, resources)}


@router.post("/ocr/fill")
def fill(req: FillReq, request: Request):
    with document_resources(request) as resources:
        output = project_path(resources, req.out, output=True) if req.out else None
        result = jianbiao.compute(req.form.strip(), req.cfg, req.values, output, req.rects)
        return {"status": 200, "data": relative_outputs(result, resources)}


@router.get("/ocr/blank/{form}.png")
def blank(form: str, request: Request, width: Annotated[int, Query(ge=1)] = 1400):
    with document_resources(request) as resources:
        template = forms().get(form.strip()) or {}
        if not template.get("pdf"):
            raise HTTPException(404, f"模板库没有 {form} 的表样 PDF")
        with pymupdf.open(resources.asset(template["pdf"][0])) as document:
            page = document[0]
            scale = min(width, 2400) / page.rect.width
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return Response(
                pixmap.tobytes("png"),
                media_type="image/png",
                headers={"Cache-Control": "max-age=3600"},
            )


@router.get("/ocr/sheet/{form}")
def sheet(form: str, request: Request):
    with document_resources(request):
        if not (forms().get(form.strip()) or {}).get("pdf"):
            raise HTTPException(404, f"模板库没有 {form} 的表样 PDF")
        return {"status": 200, "data": grid.sheet(form.strip())}
