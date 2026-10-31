from fastapi import APIRouter

from app.api import agents, business, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(business.router)
api_router.include_router(agents.router)
