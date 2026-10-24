from typing import Any

from langchain_core.messages import AnyMessage

from app.agents.base import BaseAgent
from app.schemas import ChatRequest, ChatResponse


class ChatAgent(BaseAgent[ChatRequest, ChatResponse]):
    name = "chat"
    temperature = 0.7

    def messages(self, request: ChatRequest) -> list[AnyMessage]:
        return self.conversation_messages(request, request.message)

    def parse_result(self, state: dict[str, Any]) -> ChatResponse:
        return ChatResponse(
            reply=state["messages"][-1].text.strip(), model=self.models.settings.llm_model
        )
