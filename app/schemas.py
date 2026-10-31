import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class RequestContext(StrictModel):
    """Caller-supplied identity metadata, never a substitute for authentication."""

    user_id: Identifier
    session_id: Identifier


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
IntentLabel = Literal[
    "work_list", "supervision_log", "image_library", "business_management", "chat", "unknown"
]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SummaryItem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class LogSummaryRequest(RequestContext):
    """可变结构的工程表单 OCR JSON 或兼容文字，序列化后最多 4000 字符。"""

    content: str | dict[str, JsonValue] = Field(
        description="工程表单 OCR 识别对象，内部字段和层级可变化；兼容通用日志文字或对象。"
        "非空，按 json.dumps(ensure_ascii=False) 序列化后最多4000字符；顶层不接受数组。"
    )

    @model_validator(mode="after")
    def validate_content(self) -> "LogSummaryRequest":
        if isinstance(self.content, str):
            self.content = self.content.strip()
            text = self.content
        else:
            text = json.dumps(self.content, ensure_ascii=False, allow_nan=False)
        if not self.content or not text.strip():
            raise ValueError("content must not be empty")
        if len(text) > 4000:
            raise ValueError("content must not exceed 4000 characters after serialization")
        return self


class LogSummary(StrictModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    date: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None = Field(
        description="原样摘录输入date、日志日期或检测日期；检测日期优先于计划日期。"
        "例如检测日期2024年10月26日则输出2024年10月26日；只有计划日期时为null。"
    )
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ] = Field(
        description="可纳入当日日志的客观中文段落，保留施工标段、部位、指标、全部原始实测值及单位；"
        "禁止换算，例如弯沉0.1、0.2、0.3（单位0.01mm）必须保持这三个数值；不推断合格结论。"
    )
    completed_items: list[SummaryItem] = Field(
        max_length=8,
        description="仅输入明确写出已完成的事项；只有表格、测量数据或检测日期时必须为[]，"
        "不能添加完成检测或完成记录填写。",
    )
    pending_items: list[SummaryItem] = Field(
        max_length=8,
        description="仅输入明确的待办或进行中事项；空值及未记录合格率不产生待办，无则[]。",
    )
    issues: list[SummaryItem] = Field(
        max_length=8,
        description="输入原表明确的不合格结论、问题、风险或矛盾，必须保留；"
        "例如结论为宽度不合格则列出宽度不合格；未填合格率不属于质量问题，无则[]。",
    )


class IntentDefinition(StrictModel):
    """Internal description of a fixed intent; callers cannot supply candidates."""

    label: IntentLabel
    description: Description


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


class IntentRequest(ConversationRequest):
    text: ShortText = Field(description="待识别的页面导航或一般交流内容")
    intents: list[JsonValue] = Field(
        default_factory=list,
        max_length=0,
        description="仅为兼容保留，必须省略或为[]；不支持自定义分类，始终使用固定五类意图",
    )


class IntentResult(StrictModel):
    intent: IntentLabel
    confidence: float = Field(ge=0, le=1)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    needs_clarification: bool

    @model_validator(mode="after")
    def validate_reason_length(self) -> "IntentResult":
        if self.intent != "chat" and len(self.reason) > 300:
            raise ValueError("non-chat reason must not exceed 300 characters")
        return self


class IntentClassification(IntentResult):
    """Internal classifier output; the chat reply is generated in a separate call."""

    reason: SummaryItem


class ChatRequest(ConversationRequest):
    message: ShortText


class ChatResponse(StrictModel):
    reply: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    model: str
