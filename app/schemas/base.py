"""跨业务共用的严格模型、身份上下文与会话基础类型。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class RequestContext(StrictModel):
    """调用方提供的身份元数据，不能替代身份认证。"""

    user_id: Identifier
    session_id: Identifier


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ConversationRequest(RequestContext):
    history: list[ChatMessage] = Field(description="当前用户当前会话的完整历史，首轮为[]")

    @model_validator(mode="after")
    def validate_history(self) -> "ConversationRequest":
        if len(self.history) % 2 or any(
            item.role != ("user" if index % 2 == 0 else "assistant")
            for index, item in enumerate(self.history)
        ):
            raise ValueError("history must contain complete user/assistant turns in order")
        return self
