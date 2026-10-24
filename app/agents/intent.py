import asyncio
import json

from app.agents.base import StructuredAgent
from app.agents.chat import ChatAgent
from app.llm import ModelService
from app.schemas import (
    ChatRequest,
    IntentClassification,
    IntentDefinition,
    IntentRequest,
    IntentResult,
)

DEFAULT_INTENTS = (
    IntentDefinition(label="work_list", description="工作列表：查看工作任务、待办事项或工作清单"),
    IntentDefinition(
        label="supervision_log", description="监理日志页面：查看、填写或管理监理日志、监理日记"
    ),
    IntentDefinition(
        label="image_library", description="图片库：查看、查找或管理现场照片、图片、相册"
    ),
    IntentDefinition(
        label="business_management", description="业务管理页面：进入业务管理、办理业务"
    ),
    IntentDefinition(label="chat", description="问候、闲聊或一般交流"),
)


class IntentAgent(StructuredAgent[IntentRequest, IntentResult]):
    name = "intent"
    result_type = IntentClassification

    def __init__(self, models: ModelService, chat_agent: ChatAgent | None = None):
        super().__init__(models)
        self.chat_agent = chat_agent if chat_agent is not None else ChatAgent(models)

    def user_content(self, request: IntentRequest) -> str:
        return json.dumps(
            {"text": request.text, "intents": [item.model_dump() for item in DEFAULT_INTENTS]},
            ensure_ascii=False,
        )

    async def run(self, request: IntentRequest) -> IntentResult:
        async with asyncio.timeout(self.models.settings.llm_timeout_seconds):
            result = await super().run(request)
            if result.intent == "unknown" or result.confidence < 0.65 or result.needs_clarification:
                return IntentResult(
                    **(result.model_dump() | {"intent": "unknown", "needs_clarification": True})
                )
            if result.intent == "chat":
                chat = await self.chat_agent.run(
                    ChatRequest(
                        user_id=request.user_id,
                        session_id=request.session_id,
                        message=request.text,
                        history=request.history,
                    )
                )
                return IntentResult(**(result.model_dump() | {"reason": chat.reply}))
            return result
