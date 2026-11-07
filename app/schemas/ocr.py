"""文档加工请求；保留 docsvc 字段和空输出语义。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JournalReq(BaseModel):
    """新版监理日志识别请求；与旧接口字段一致，实现链独立。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str = Field(default="", description="PROJECTS_ROOT 数据池内的监理日志照片路径")
    img: str = Field(default="", description="base64 编码的图片数据；path 与 img 至少提供一个")
    task_id: str = Field(
        default="",
        alias="taskId",
        title="TaskId",
        max_length=128,
        description="业务任务 ID，仅原样回显到 processed.taskId；不传则为 null",
    )

    @model_validator(mode="after")
    def validate_source(self) -> "JournalReq":
        self.path = self.path.strip()
        self.img = self.img.strip()
        self.task_id = self.task_id.strip()
        if not self.path and not self.img:
            raise ValueError("path 与 img 至少提供一个")
        return self


class MainWorkCategory(StrEnum):
    """mainWork 原文单元的业务类别；unknown 只在内部使用，不进入 HTTP 响应。"""

    construction = "construction"
    witness = "witness"
    patrol = "patrol"
    unknown = "unknown"


class MainWorkUnit(BaseModel):
    """拆分的最小单位；text 必须来自 source_text，start/end 相对 source_text。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str = Field(pattern=r"^u\d+$")
    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    is_heading: bool = False
    heading_category: MainWorkCategory | None = None

    @model_validator(mode="after")
    def validate_span(self) -> "MainWorkUnit":
        if self.end <= self.start:
            raise ValueError("end 必须大于 start")
        if self.heading_category is not None and not self.is_heading:
            raise ValueError("只有标题单元可以带 heading_category")
        return self


class MainWorkSplitRequest(BaseModel):
    """模型输入；start/end 是内部坐标，不发送给模型。"""

    model_config = ConfigDict(extra="forbid")

    units: tuple[MainWorkUnit, ...] = Field(min_length=1)


class MainWorkAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str = Field(pattern=r"^u\d+$")
    category: MainWorkCategory


class MainWorkSplitPlan(BaseModel):
    """模型输出：每个原文单元必须出现且只出现一次。"""

    model_config = ConfigDict(extra="forbid")

    assignments: list[MainWorkAssignment] = Field(min_length=1)


class MainWorkValues(BaseModel):
    """拆分后的三个业务字段；原文没有该类内容时为 null。"""

    model_config = ConfigDict(extra="forbid")

    construction: str | None = None
    witness: str | None = None
    patrol: str | None = None
