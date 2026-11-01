"""意图识别能力在不同业务端的固定分类、提示词与输出模型。"""

from dataclasses import dataclass
from typing import get_args

from pydantic import BaseModel

from app.schemas.agents import (
    ArchiveIntentClassification,
    ArchiveIntentResult,
    IntentClassification,
    IntentDefinition,
    IntentResult,
)


def _labels(model: type[BaseModel]) -> tuple[str, ...]:
    """读取响应模型 intent 字段的 Literal 枚举，避免配置与契约各维护一份。"""
    annotation = model.model_fields["intent"].annotation
    labels = tuple(label for label in get_args(annotation) if isinstance(label, str))
    if not labels:
        raise TypeError(f"{model.__name__}.intent must be a string Literal")
    return labels


@dataclass(frozen=True)
class IntentProfile:
    """一个业务端的意图识别配置；实现共享，差异只在这里声明。"""

    name: str
    agent_name: str
    prompt_name: str
    intents: tuple[IntentDefinition, ...]
    classification_type: type[BaseModel]
    response_type: type[BaseModel]
    chat_label: str | None = None
    fallback_label: str = "unknown"
    # 修改该阈值时，同步更新对应提示词中关于 0.65 的说明。
    min_confidence: float = 0.65

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"profile name must be a Python identifier: {self.name!r}")
        if not self.agent_name.isidentifier():
            raise ValueError(f"agent name must be a Python identifier: {self.agent_name!r}")
        if not all(part.isidentifier() for part in self.prompt_name.split("/")):
            raise ValueError(f"invalid prompt name: {self.prompt_name!r}")

        labels = [item.label for item in self.intents]
        if not labels:
            raise ValueError(f"{self.name}: at least one intent is required")
        if len(set(labels)) != len(labels):
            raise ValueError(f"{self.name}: intent labels must be unique")
        if self.fallback_label in labels:
            raise ValueError(f"{self.name}: fallback label must not be a regular intent")
        if self.chat_label is not None and self.chat_label not in labels:
            raise ValueError(f"{self.name}: chat label must be one of the profile intents")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError(f"{self.name}: min_confidence must be within [0, 1]")

        expected = set(labels) | {self.fallback_label}
        for model in (self.classification_type, self.response_type):
            actual = set(_labels(model))
            if actual != expected:
                raise ValueError(
                    f"{self.name}: {model.__name__} has missing labels "
                    f"{sorted(expected - actual)} and extra labels {sorted(actual - expected)}"
                )

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(item.label for item in self.intents) + (self.fallback_label,)


BUSINESS_INTENTS = (
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

# TODO(archive): 补齐 A/B/C/D 的真实业务含义与例句后，再启用真实模型语义验收。
ARCHIVE_INTENTS = (
    IntentDefinition(label="A", description="待补充：文件归档系统的 A 类业务"),
    IntentDefinition(label="B", description="待补充：文件归档系统的 B 类业务"),
    IntentDefinition(label="C", description="待补充：文件归档系统的 C 类业务"),
    IntentDefinition(label="D", description="待补充：文件归档系统的 D 类业务"),
)

BUSINESS_INTENT_PROFILE = IntentProfile(
    name="business",
    agent_name="intent",
    prompt_name="intent/business",
    intents=BUSINESS_INTENTS,
    classification_type=IntentClassification,
    response_type=IntentResult,
    chat_label="chat",
)

ARCHIVE_INTENT_PROFILE = IntentProfile(
    name="archive",
    agent_name="intent_archive",
    prompt_name="intent/archive",
    intents=ARCHIVE_INTENTS,
    classification_type=ArchiveIntentClassification,
    response_type=ArchiveIntentResult,
)

INTENT_PROFILES = {
    profile.name: profile for profile in (BUSINESS_INTENT_PROFILE, ARCHIVE_INTENT_PROFILE)
}
