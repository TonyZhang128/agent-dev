"""纯请求局部的历史选择；不涉及会话、存储或可变 Agent 状态。"""

import json

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from app.config import Settings
from app.errors import ConversationInputTooLarge
from app.schemas import ChatMessage


def message_budget(text: str) -> int:
    # 保守的字节估算，不是精确的模型分词器；同时计入消息封装开销。
    return len(text.encode("utf-8")) + 16


def trim_history(
    history: list[ChatMessage],
    current: str,
    *,
    system_prompt: str,
    schema: dict | None,
    settings: Settings,
) -> list[AnyMessage]:
    if (
        len(current) + sum(len(item.content) for item in history)
        > settings.conversation_max_input_characters
    ):
        raise ConversationInputTooLarge
    fixed = message_budget(system_prompt) + message_budget(current)
    # 为原生响应格式指令和提示词中的 Schema 预留预算。
    if schema is not None:
        fixed += message_budget(json.dumps(schema, ensure_ascii=False))
    available = (
        settings.llm_context_tokens
        - settings.llm_max_tokens
        - settings.llm_context_margin_tokens
        - fixed
    )
    if available < 0:
        raise ConversationInputTooLarge
    start = len(history)
    # 只保留完整 user/assistant 回合组成的连续后缀，绝不截断消息正文。
    for index in range(len(history) - 2, -1, -2):
        cost = message_budget(history[index].content) + message_budget(history[index + 1].content)
        if cost > available:
            break
        available -= cost
        start = index
    messages: list[AnyMessage] = [
        (HumanMessage if item.role == "user" else AIMessage)(content=item.content)
        for item in history[start:]
    ]
    messages.append(HumanMessage(content=current))
    return messages
