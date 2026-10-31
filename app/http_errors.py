"""HTTP error mapping; business and model errors remain independent of FastAPI."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.errors import ConversationInputTooLarge, InvalidModelOutput

# Preserve the established channel for deployments that filter HTTP error logs.
logger = logging.getLogger("app.main")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's input/ctx may contain the entire conversation and identity.
        details = [{key: item[key] for key in ("type", "loc", "msg")} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": details})

    @app.exception_handler(ConversationInputTooLarge)
    async def conversation_too_large(
        request: Request, exc: ConversationInputTooLarge
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "请求超过输入上限，或当前输入与系统提示词超出上下文预算"},
        )

    @app.exception_handler(APITimeoutError)
    @app.exception_handler(TimeoutError)
    async def model_timeout(request: Request, exc: APITimeoutError | TimeoutError) -> JSONResponse:
        return JSONResponse(status_code=504, content={"detail": "模型推理超时"})

    @app.exception_handler(APIConnectionError)
    async def model_unavailable(request: Request, exc: APIConnectionError) -> JSONResponse:
        return JSONResponse(
            status_code=503, content={"detail": "模型服务不可达，请检查 Ollama/vLLM"}
        )

    @app.exception_handler(APIStatusError)
    async def model_error(request: Request, exc: APIStatusError) -> JSONResponse:
        logger.warning("Model server returned HTTP %s", exc.status_code)
        return JSONResponse(
            status_code=502, content={"detail": "模型服务返回错误，请检查模型名称和服务日志"}
        )

    @app.exception_handler(InvalidModelOutput)
    async def invalid_output(request: Request, exc: InvalidModelOutput) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": "模型未返回完整且符合约定的结果"})
