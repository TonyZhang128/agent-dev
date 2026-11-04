"""日志总结、意图识别与聊天业务的请求、响应和校验。"""

import json
from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints, model_validator

from app.schemas.base import (
    ChatMessage,
    ConversationRequest,
    Identifier,
    RequestContext,
    StrictModel,
)
from app.schemas.intent_catalog_generated import (
    PAGE_BY_ACTION,
    BusinessActionLabel,
    BusinessPageLabel,
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ArchiveIntentLabel = Literal["A", "B", "C", "D", "unknown"]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SummaryItem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
IntentReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]
MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CatalogVersion = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]


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
    """服务端维护的意图描述；允许的标签集合由具体 IntentProfile 限定。"""

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    description: Description


class IntentRequest(ConversationRequest):
    text: ShortText = Field(description="待识别的归档业务内容")
    intents: list[JsonValue] = Field(
        default_factory=list,
        max_length=0,
        description="仅为兼容保留，必须省略或为[]；不支持调用方自定义分类",
    )


class BusinessNavigationContext(StrictModel):
    """调用方最近一次返回过的导航目标；只作为纠错上下文。"""

    page: BusinessPageLabel
    action: BusinessActionLabel | None = None

    @model_validator(mode="after")
    def validate_action_belongs_to_page(self) -> "BusinessNavigationContext":
        if self.action is not None and PAGE_BY_ACTION.get(self.action) != self.page:
            raise ValueError("action does not belong to page")
        return self


class PendingClarification(StrictModel):
    """调用方保存的一级意图澄清状态；attempts 是已完成的澄清轮数。"""

    page: BusinessPageLabel
    attempts: int = Field(ge=0, le=10)


class BusinessIntentRequest(ConversationRequest):
    """无状态业务意图请求；会话上下文由调用方传入。"""

    history: list[ChatMessage] = Field(
        default_factory=list,
        description="当前用户当前会话的完整历史，首轮为[]；可省略",
    )
    message: ShortText
    current_page: BusinessPageLabel = Field(description="调用方当前实际页面编码")
    last_navigation: BusinessNavigationContext | None = None
    pending_clarification: PendingClarification | None = None
    request_id: Identifier | None = Field(
        default=None,
        description="调用方幂等标识；本服务不持久化，仅供调用方关联",
    )


class BusinessIntentOption(StrictModel):
    """澄清时可选的合法二级功能。"""

    page: BusinessPageLabel
    action: BusinessActionLabel
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_action_belongs_to_page(self) -> "BusinessIntentOption":
        if PAGE_BY_ACTION.get(self.action) != self.page:
            raise ValueError("action does not belong to page")
        return self


class BusinessIntentClassification(StrictModel):
    """业务意图分类器的内部输出；最终状态由服务端归一。"""

    kind: Literal["navigate", "chat", "unknown"]
    page: BusinessPageLabel | None = None
    action: BusinessActionLabel | None = None
    confidence: float = Field(ge=0, le=1)
    reason: IntentReason
    needs_clarification: bool = False

    @model_validator(mode="after")
    def validate_hierarchy(self) -> "BusinessIntentClassification":
        if self.kind != "navigate":
            if self.page is not None or self.action is not None:
                raise ValueError("only navigate may carry page or action")
            return self
        if self.page is None:
            raise ValueError("navigate requires page")
        if self.action is not None and PAGE_BY_ACTION.get(self.action) != self.page:
            raise ValueError("action does not belong to page")
        return self


class BusinessIntentResult(StrictModel):
    """业务意图识别响应；status 区分跳转、澄清、聊天和未知。"""

    status: Literal["resolved", "clarify", "chat", "unknown"]
    page: BusinessPageLabel | None
    action: BusinessActionLabel | None
    confidence: float = Field(ge=0, le=1)
    message: MessageText | None
    options: list[BusinessIntentOption] | None = Field(max_length=20)
    catalog_version: CatalogVersion

    @model_validator(mode="after")
    def validate_status_shape(self) -> "BusinessIntentResult":
        if self.status == "resolved":
            if self.page is None or self.action is None:
                raise ValueError("resolved requires page and action")
            if PAGE_BY_ACTION.get(self.action) != self.page:
                raise ValueError("action does not belong to page")
            if self.message is not None or self.options is not None:
                raise ValueError("resolved must not carry message or options")
            return self
        if self.status == "clarify":
            if self.page is None or self.action is not None:
                raise ValueError("clarify requires page without action")
            if self.message is None:
                raise ValueError("clarify requires a message")
            if not self.options or any(option.page != self.page for option in self.options):
                raise ValueError("clarify options must belong to page")
            return self
        if self.page is not None or self.action is not None:
            raise ValueError(f"{self.status} must not carry page or action")
        if self.message is None:
            raise ValueError(f"{self.status} requires a message")
        if self.options is not None:
            raise ValueError(f"{self.status} must not carry options")
        return self


class ClarifyRequest(ConversationRequest):
    """Chat 澄清模式的内部请求；候选由服务端目录生成。"""

    message: ShortText
    page: BusinessPageLabel
    options: list[BusinessIntentOption] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_options_belong_to_page(self) -> "ClarifyRequest":
        if any(option.page != self.page for option in self.options):
            raise ValueError("clarify options must belong to page")
        return self


class ArchiveIntentResult(StrictModel):
    """文件归档系统的意图识别结果；当前无聊天分流，理由始终简短。"""

    intent: ArchiveIntentLabel
    confidence: float = Field(ge=0, le=1)
    reason: IntentReason
    needs_clarification: bool


class ArchiveIntentClassification(ArchiveIntentResult):
    """归档意图分类器的内部输出；当前与最终响应字段一致。"""


class ChatRequest(ConversationRequest):
    message: ShortText


class ChatResponse(StrictModel):
    reply: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    model: str
