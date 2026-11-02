from fastapi import APIRouter

from app.api import agents, ocr, system, wbs

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(agents.router)
api_router.include_router(ocr.router)
api_router.include_router(wbs.router)
