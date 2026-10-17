import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlanRequest(StrictModel):
    instruction: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def nonblank(self) -> "PlanRequest":
        self.instruction = self.instruction.strip()
        if not self.instruction:
            raise ValueError("instruction must not be blank")
        return self


class BusinessStep(StrictModel):
    step: int = Field(ge=1)
    action: str = Field(min_length=1, max_length=500)
    responsible_role: str = Field(min_length=1, max_length=100)
    condition: str = Field(min_length=1, max_length=300)
    expected_output: str = Field(min_length=1, max_length=300)


class BusinessPlan(StrictModel):
    goal: str = Field(min_length=1, max_length=300)
    steps: list[BusinessStep] = Field(min_length=1, max_length=12)
    assumptions: list[str] = Field(max_length=12)
    questions: list[str] = Field(max_length=12)

    @model_validator(mode="after")
    def ordered_steps(self) -> "BusinessPlan":
        if [item.step for item in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("steps must have consecutive numbers starting at 1")
        return self


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SummaryItem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class LogSummaryRequest(StrictModel):
    """结构化文字或 JSON 对象，序列化后最多 4000 字符。"""

    content: str | dict[str, JsonValue]

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
    date: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    completed_items: list[SummaryItem] = Field(max_length=8)
    pending_items: list[SummaryItem] = Field(max_length=8)
    issues: list[SummaryItem] = Field(max_length=8)


class IntentDefinition(StrictModel):
    label: Label
    description: Description


class IntentRequest(StrictModel):
    text: ShortText
    intents: list[IntentDefinition] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_intents(self) -> "IntentRequest":
        labels = [item.label.casefold() for item in self.intents]
        if len(set(labels)) != len(labels) or "unknown" in labels:
            raise ValueError("intent labels must be unique; unknown is reserved")
        if sum(len(item.label) + len(item.description) for item in self.intents) > 2000:
            raise ValueError("intent definitions must not exceed 2000 characters in total")
        return self


class IntentResult(StrictModel):
    intent: Label
    confidence: float = Field(ge=0, le=1)
    reason: SummaryItem
    needs_clarification: bool


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: ShortText


class ChatRequest(StrictModel):
    message: ShortText
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_history(self) -> "ChatRequest":
        if len(self.history) % 2 or any(
            item.role != ("user" if index % 2 == 0 else "assistant")
            for index, item in enumerate(self.history)
        ):
            raise ValueError("history must contain complete user/assistant turns in order")
        if len(self.message) + sum(len(item.content) for item in self.history) > 4000:
            raise ValueError("message and history must not exceed 4000 characters in total")
        return self


class ChatResponse(StrictModel):
    reply: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    model: str
