import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.agents.business_plan import BusinessPlanAgent
from app.agents.chat import ChatAgent
from app.agents.intent import IntentAgent
from app.agents.log_summary import LogSummaryAgent
from app.config import Settings
from app.errors import ConversationInputTooLarge, InvalidModelOutput
from app.llm import ModelService
from app.schemas import (
    BusinessPlan,
    ChatRequest,
    ChatResponse,
    IntentRequest,
    IntentResult,
    LogSummary,
    LogSummaryRequest,
    PlanRequest,
)

logger = logging.getLogger(__name__)


def create_app(service: ModelService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model_service = service or ModelService(Settings())
        try:
            app.state.business_plan_agent = BusinessPlanAgent(app.state.model_service)
            app.state.log_summary_agent = LogSummaryAgent(app.state.model_service)
            app.state.chat_agent = ChatAgent(app.state.model_service)
            app.state.intent_agent = IntentAgent(app.state.model_service, app.state.chat_agent)
            yield
        finally:
            await app.state.model_service.close()

    app = FastAPI(title="Qwen 业务智能体 API", version="0.3.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Pydantic's input/ctx may contain the entire conversation and identity.
        details = [{key: item[key] for key in ("type", "loc", "msg")} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": details})

    @app.exception_handler(ConversationInputTooLarge)
    async def conversation_too_large(request: Request, exc: ConversationInputTooLarge):
        return JSONResponse(
            status_code=422,
            content={"detail": "请求超过输入上限，或当前输入与系统提示词超出上下文预算"},
        )

    @app.exception_handler(APITimeoutError)
    @app.exception_handler(TimeoutError)
    async def model_timeout(request: Request, exc: APITimeoutError | TimeoutError):
        return JSONResponse(status_code=504, content={"detail": "模型推理超时"})

    @app.exception_handler(APIConnectionError)
    async def model_unavailable(request: Request, exc: APIConnectionError):
        return JSONResponse(
            status_code=503, content={"detail": "模型服务不可达，请检查 Ollama/vLLM"}
        )

    @app.exception_handler(APIStatusError)
    async def model_error(request: Request, exc: APIStatusError):
        logger.warning("Model server returned HTTP %s", exc.status_code)
        return JSONResponse(
            status_code=502, content={"detail": "模型服务返回错误，请检查模型名称和服务日志"}
        )

    @app.exception_handler(InvalidModelOutput)
    async def invalid_output(request: Request, exc: InvalidModelOutput):
        return JSONResponse(status_code=502, content={"detail": "模型未返回完整且符合约定的结果"})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request):
        try:
            available = await request.app.state.model_service.ready()
        except (APIConnectionError, APIStatusError, httpx.HTTPError, ValueError):
            raise HTTPException(503, "模型服务不可达，请检查 Ollama/vLLM") from None
        if not available:
            raise HTTPException(503, "模型未安装或 LLM_MODEL 与服务端模型名称不匹配")
        return {"status": "ready"}

    @app.post(
        "/api/business/plan", response_model=BusinessPlan, tags=["业务规划"], summary="生成业务步骤"
    )
    async def plan(payload: PlanRequest, request: Request):
        return await request.app.state.business_plan_agent.run(payload)

    @app.post(
        "/api/agents/log-summary",
        response_model=LogSummary,
        tags=["智能体"],
        summary="总结并生成工作日志",
    )
    async def log_summary(payload: LogSummaryRequest, request: Request):
        return await request.app.state.log_summary_agent.run(payload)

    @app.post(
        "/api/agents/intent",
        response_model=IntentResult,
        tags=["智能体"],
        summary="识别页面导航或一般交流意图",
    )
    async def intent(payload: IntentRequest, request: Request):
        return await request.app.state.intent_agent.run(payload)

    @app.post("/api/agents/chat", response_model=ChatResponse, tags=["智能体"], summary="自由对话")
    async def chat(payload: ChatRequest, request: Request):
        return await request.app.state.chat_agent.run(payload)

    return app


app = create_app()
