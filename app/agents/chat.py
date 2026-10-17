from app.llm import ModelService
from app.schemas import ChatRequest, ChatResponse


class ChatAgent:
    def __init__(self, model: ModelService):
        self.model = model

    async def run(self, request: ChatRequest) -> ChatResponse:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是友好、可靠的中文对话助手，可以自然聊天、回答问题和讨论想法。"
                    "根据用户语言作答，默认中文，回答简洁清楚；不确定的事情坦诚说明。"
                    "你没有执行外部业务操作的工具，不声称已操作业务系统。"
                    "结合本次提供的历史对话理解上下文，不声称记得未提供的历史。"
                ),
            },
            *[item.model_dump() for item in request.history],
            {"role": "user", "content": request.message},
        ]
        reply = await self.model.generate_text(messages)
        return ChatResponse(reply=reply, model=self.model.settings.llm_model)
