from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.chat import ChatAgent
from app.agents.intent import IntentAgent
from app.agents.log_summary import LogSummaryAgent
from app.api.router import api_router
from app.config import Settings
from app.http_errors import register_exception_handlers
from app.llm import ModelService
from app.ocr.resources import OCRResources


def create_app(service: ModelService | None = None, *, settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        config = settings or (service.settings if service else Settings())
        app.state.model_service = service or ModelService(config)
        try:
            app.state.ocr_resources = OCRResources(config)
            app.state.log_summary_agent = LogSummaryAgent(app.state.model_service)
            app.state.chat_agent = ChatAgent(app.state.model_service)
            app.state.intent_agent = IntentAgent(app.state.model_service, app.state.chat_agent)
            yield
        finally:
            try:
                await app.state.model_service.close()
            finally:
                resources = getattr(app.state, "ocr_resources", None)
                if resources is not None:
                    resources.close()

    app = FastAPI(title="公路工程业务智能体", version="0.1.0", lifespan=lifespan)

    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
