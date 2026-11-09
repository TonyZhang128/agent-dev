from fastapi import APIRouter

from app.api import agents, ocr, system

api_router = APIRouter()
api_router.include_router(system.router)  # 系统检查
api_router.include_router(agents.router)  # 智能体功能
api_router.include_router(ocr.router)  # OCR功能
# api_router.include_router(wbs.router)  # 施工图划分功能
