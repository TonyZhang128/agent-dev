from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.business_plan import BusinessPlanAgent
from app.agents.chat import ChatAgent
from app.agents.intent import IntentAgent
from app.agents.log_summary import LogSummaryAgent
from app.api.router import api_router
from app.config import Settings
from app.http_errors import register_exception_handlers
from app.llm import ModelService


def create_app(service: ModelService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.model_service = service or ModelService(Settings())
        try:
            app.state.business_plan_agent = BusinessPlanAgent(app.state.model_service)
            app.state.log_summary_agent = LogSummaryAgent(app.state.model_service)
            app.state.chat_agent = ChatAgent(app.state.model_service)
            app.state.intent_agent = IntentAgent(app.state.model_service, app.state.chat_agent)
            yield
        finally:
            await app.state.model_service.close()

    app = FastAPI(title="公路工程业务智能体", version="0.1.0", lifespan=lifespan)

    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
