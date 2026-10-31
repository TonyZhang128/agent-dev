"""使用 LangChain 官方 create_agent API 构建所有业务 Agent。"""

import asyncio
import json
from copy import deepcopy
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain.agents.structured_output import ProviderStrategy, StructuredOutputError
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AnyMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError
from langsmith import tracing_context
from openai import ContentFilterFinishReasonError, LengthFinishReasonError

from app.agents.middleware import ResponseGuard
from app.errors import InvalidModelOutput
from app.llm import ModelService


def prepared_schema(schema: dict | None, name: str) -> dict | None:
    if schema is None:
        return None
    schema = deepcopy(schema)
    schema["title"] = name
    schema.setdefault("description", f"Structured response for {name}")
    return schema


def system_prompt(prompt: str, schema: dict | None) -> str:
    return (
        prompt
        if schema is None
        else prompt + "\nJSON schema: " + json.dumps(schema, ensure_ascii=False)
    )


def build_agent(
    models: ModelService,
    *,
    name: str,
    prompt: str,
    schema: dict | None = None,
    temperature: float = 0,
    tools: tuple[BaseTool, ...] = (),
):
    strategy = None
    schema = prepared_schema(schema, name)
    if schema is not None:
        strategy = ProviderStrategy(schema=schema, strict=True)
    middleware = [ResponseGuard(allow_tool_calls=bool(tools))]
    if models.fallback_enabled:
        # 主模型调用失败（连接、超时、上游错误）时改用云端模型重试；
        # 重试后仍会执行输出校验。
        middleware.append(
            ModelFallbackMiddleware(models.fallback_chat_model(temperature=temperature))
        )
    return create_agent(
        model=models.chat_model(temperature=temperature),
        tools=list(tools),
        system_prompt=system_prompt(prompt, schema),
        response_format=strategy,
        middleware=middleware,
        checkpointer=None,
        name=name,
    )


async def invoke_agent(
    agent,
    models: ModelService,
    messages: list[AnyMessage],
    *,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        with tracing_context(enabled=models.settings.langsmith_tracing):
            async with asyncio.timeout(models.inference_timeout_seconds):
                return await agent.ainvoke(
                    {"messages": messages},
                    config={
                        "recursion_limit": models.settings.agent_recursion_limit,
                        "metadata": metadata or {},
                    },
                )
    except (
        StructuredOutputError,
        OutputParserException,
        GraphRecursionError,
        ContentFilterFinishReasonError,
        LengthFinishReasonError,
    ) as exc:
        raise InvalidModelOutput("agent could not produce valid output") from exc
