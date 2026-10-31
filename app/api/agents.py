from fastapi import APIRouter, Request

from app.schemas import (
    ChatRequest,
    ChatResponse,
    IntentRequest,
    IntentResult,
    LogSummary,
    LogSummaryRequest,
)

router = APIRouter(prefix="/api/agents", tags=["智能体"])


@router.post("/log-summary", response_model=LogSummary, summary="总结并生成工作日志")
async def log_summary(payload: LogSummaryRequest, request: Request):
    return await request.app.state.log_summary_agent.run(payload)


@router.post("/intent", response_model=IntentResult, summary="识别页面导航或一般交流意图")
async def intent(payload: IntentRequest, request: Request):
    return await request.app.state.intent_agent.run(payload)


@router.post("/chat", response_model=ChatResponse, summary="自由对话")
async def chat(payload: ChatRequest, request: Request):
    return await request.app.state.chat_agent.run(payload)
