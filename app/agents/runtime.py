"""Build every business agent with LangChain's supported create_agent API."""

import asyncio
import json
from copy import deepcopy
from typing import Any

from langchain.agents import create_agent
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
    if schema is not None:
        schema = deepcopy(schema)
        schema["title"] = name
        schema.setdefault("description", f"Structured response for {name}")
        prompt += "\nJSON schema: " + json.dumps(schema, ensure_ascii=False)
        strategy = ProviderStrategy(schema=schema, strict=True)
    return create_agent(
        model=models.chat_model(temperature=temperature),
        tools=list(tools),
        system_prompt=prompt,
        response_format=strategy,
        middleware=[ResponseGuard(allow_tool_calls=bool(tools))],
        checkpointer=None,
        name=name,
    )


async def invoke_agent(agent, models: ModelService, messages: list[AnyMessage]) -> dict[str, Any]:
    try:
        with tracing_context(enabled=models.settings.langsmith_tracing):
            async with asyncio.timeout(models.settings.llm_timeout_seconds):
                return await agent.ainvoke(
                    {"messages": messages},
                    config={"recursion_limit": models.settings.agent_recursion_limit},
                )
    except (
        StructuredOutputError,
        OutputParserException,
        GraphRecursionError,
        ContentFilterFinishReasonError,
        LengthFinishReasonError,
    ) as exc:
        raise InvalidModelOutput("agent could not produce valid output") from exc
