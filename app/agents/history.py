"""Pure request-local history selection; no sessions, storage, or mutable agent state."""

import json

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from app.config import Settings
from app.errors import ConversationInputTooLarge
from app.schemas import ChatMessage


def message_budget(text: str) -> int:
    # Conservative byte-based estimate, NOT an exact model tokenizer. Include framing.
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
    # Reserve for native response-format instructions as well as the schema in the prompt.
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
    # Retain a contiguous suffix of complete user/assistant turns. Never cut message text.
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
