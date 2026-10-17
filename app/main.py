import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.agents.chat import ChatAgent
from app.agents.intent import IntentAgent
from app.agents.log_summary import LogSummaryAgent
from app.config import Settings
from app.llm import InvalidModelOutput, ModelService
from app.schemas import (
    BusinessPlan, ChatRequest, ChatResponse, IntentRequest, IntentResult,
    LogSummary, LogSummaryRequest, PlanRequest,
)

logger = logging.getLogger(__name__)


def create_app(service: ModelService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model_service = service or ModelService(Settings())
        app.state.log_summary_agent = LogSummaryAgent(app.state.model_service)
        app.state.intent_agent = IntentAgent(app.state.model_service)
        app.state.chat_agent = ChatAgent(app.state.model_service)
        try:
            yield
        finally:
            await app.state.model_service.close()

    app = FastAPI(title="Qwen 业务智能体 API", version="0.2.0", lifespan=lifespan)

    @app.exception_handler(APITimeoutError)
    async def model_timeout(request: Request, exc: APITimeoutError):
        return JSONResponse(status_code=504, content={"detail": "模型推理超时"})

    @app.exception_handler(APIConnectionError)
    async def model_unavailable(request: Request, exc: APIConnectionError):
        return JSONResponse(status_code=503, content={"detail": "模型服务不可达，请检查 Ollama/vLLM"})

    @app.exception_handler(APIStatusError)
    async def model_error(request: Request, exc: APIStatusError):
        logger.warning("Model server returned HTTP %s", exc.status_code)
        return JSONResponse(status_code=502, content={"detail": "模型服务返回错误，请检查模型名称和服务日志"})

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
        except (APIConnectionError, APIStatusError):
            raise HTTPException(503, "模型服务不可达，请检查 Ollama/vLLM") from None
        if not available:
            raise HTTPException(503, "模型未安装或 LLM_MODEL 与服务端模型名称不匹配")
        return {"status": "ready"}

    @app.post("/api/business/plan", response_model=BusinessPlan, tags=["业务规划"], summary="生成业务步骤")
    async def plan(payload: PlanRequest, request: Request):
        return await request.app.state.model_service.plan(payload.instruction)

    @app.post("/api/agents/log-summary", response_model=LogSummary, tags=["智能体"], summary="总结并生成工作日志")
    async def log_summary(payload: LogSummaryRequest, request: Request):
        return await request.app.state.log_summary_agent.run(payload)

    @app.post("/api/agents/intent", response_model=IntentResult, tags=["智能体"], summary="识别业务意图")
    async def intent(payload: IntentRequest, request: Request):
        return await request.app.state.intent_agent.run(payload)

    @app.post("/api/agents/chat", response_model=ChatResponse, tags=["智能体"], summary="自由对话")
    async def chat(payload: ChatRequest, request: Request):
        return await request.app.state.chat_agent.run(payload)

    return app


app = create_app()
