from fastapi import APIRouter

from app.api import agents, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(agents.router)
