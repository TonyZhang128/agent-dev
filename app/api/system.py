import httpx
from fastapi import APIRouter, HTTPException, Request
from openai import APIConnectionError, APIStatusError

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request):
    try:
        available = await request.app.state.model_service.ready()
    except (APIConnectionError, APIStatusError, httpx.HTTPError, ValueError):
        raise HTTPException(503, "模型服务不可达，请检查 Ollama/vLLM") from None
    if not available:
        raise HTTPException(503, "模型未安装或 LLM_MODEL 与服务端模型名称不匹配")
    return {"status": "ready"}
