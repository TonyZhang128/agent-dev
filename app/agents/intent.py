import asyncio
import json

from pydantic import BaseModel

from app.agents.base import StructuredAgent
from app.agents.chat import ChatAgent
from app.agents.profiles import IntentProfile
from app.llm import ModelService
from app.schemas.agents import ChatRequest, IntentRequest


class IntentAgent[ResultT: BaseModel](StructuredAgent[IntentRequest, ResultT]):
    """按 IntentProfile 复用同一分类流程，业务端差异只来自配置。"""

    def __init__(
        self,
        models: ModelService,
        profile: IntentProfile,
        chat_agent: ChatAgent | None = None,
    ):
        self.profile = profile
        self.name = profile.agent_name
        self.result_type = profile.classification_type
        if profile.chat_label is None:
            self.chat_agent = None
        else:
            self.chat_agent = chat_agent if chat_agent is not None else ChatAgent(models)
        super().__init__(models, prompt_name=profile.prompt_name)

    def user_content(self, request: IntentRequest) -> str:
        return json.dumps(
            {
                "text": request.text,
                "intents": [item.model_dump() for item in self.profile.intents],
            },
            ensure_ascii=False,
        )

    async def run(self, request: IntentRequest) -> ResultT:
        async with asyncio.timeout(self.models.settings.llm_timeout_seconds):
            classification = await super().run(request)
            data = classification.model_dump()
            if (
                classification.intent == self.profile.fallback_label
                or classification.confidence < self.profile.min_confidence
                or classification.needs_clarification
            ):
                return self.profile.response_type.model_validate(
                    data | {"intent": self.profile.fallback_label, "needs_clarification": True}
                )
            if (
                self.profile.chat_label is not None
                and classification.intent == self.profile.chat_label
            ):
                if self.chat_agent is None:
                    raise RuntimeError(f"{self.profile.name}: chat profile requires a chat agent")
                chat = await self.chat_agent.run(
                    ChatRequest(
                        user_id=request.user_id,
                        session_id=request.session_id,
                        message=request.text,
                        history=request.history,
                    )
                )
                return self.profile.response_type.model_validate(data | {"reason": chat.reply})
            return self.profile.response_type.model_validate(data)
