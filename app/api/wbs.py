"""施工图划分初稿，不执行人工确认、审批或落库。"""

from fastapi import APIRouter, Request

from app.api.ocr import document_resources, project_path
from app.ocr import wbs_draft
from app.ocr.schemas import DraftReq

router = APIRouter(prefix="/wbs", tags=["wbs"])


@router.post("/draft")
def wbs_draft_api(req: DraftReq, request: Request):
    with document_resources(request) as resources:
        paths = [project_path(resources, relative) for relative in req.drawings]
        return {"status": 200, "data": wbs_draft.draft(req.prefix, paths, req.basis)}
