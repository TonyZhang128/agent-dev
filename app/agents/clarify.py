"""业务导航的一级意图澄清模式；复用聊天能力，只允许目录内选项。"""

import json
from typing import Any

from langchain_core.messages import AnyMessage

from app.agents.base import BaseAgent
from app.llm import ModelService
from app.schemas.agents import ChatResponse, ClarifyRequest


class ClarificationAgent(BaseAgent[ClarifyRequest, ChatResponse]):
    name = "intent_business_clarify"
    temperature = 0.2

    def __init__(self, model_service: ModelService):
        super().__init__(model_service, prompt_name="intent/business_clarify")

    def messages(self, request: ClarifyRequest) -> list[AnyMessage]:
        content = json.dumps(
            {
                "text": request.message,
                "page": request.page,
                "options": [option.model_dump() for option in request.options],
            },
            ensure_ascii=False,
        )
        return self.conversation_messages(request, content)

    def parse_result(self, state: dict[str, Any]) -> ChatResponse:
        return ChatResponse(
            reply=state["messages"][-1].text.strip(),
            model=self.models.settings.llm_model,
        )
