from fastapi import APIRouter, Request

from app.schemas.agents import (
    ArchiveIntentResult,
    BusinessIntentRequest,
    BusinessIntentResult,
    ChatRequest,
    ChatResponse,
    IntentRequest,
    LogSummary,
    LogSummaryRequest,
)

router = APIRouter(prefix="/agents", tags=["智能体"])


@router.post("/log-summary", response_model=LogSummary, summary="总结并生成工作日志")
async def log_summary(payload: LogSummaryRequest, request: Request):
    return await request.app.state.log_summary_agent.run(payload)


@router.post(
    "/intent/business",
    response_model=BusinessIntentResult,
    summary="识别业务页面与最小功能意图",
)
async def business_intent(payload: BusinessIntentRequest, request: Request):
    return await request.app.state.business_intent_agent.run(payload)


@router.post(
    "/intent/archive",
    response_model=ArchiveIntentResult,
    summary="识别文件归档系统意图",
)
async def archive_intent(payload: IntentRequest, request: Request):
    return await request.app.state.archive_intent_agent.run(payload)


@router.post("/chat", response_model=ChatResponse, summary="自由对话")
async def chat(payload: ChatRequest, request: Request):
    return await request.app.state.chat_agent.run(payload)
