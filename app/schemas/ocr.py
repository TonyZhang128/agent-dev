"""文档加工请求；保留 docsvc 字段和空输出语义。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator


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


class MainWorkRequest(BaseModel):
    """Agent输入合并后的完整mainWork，不再输入碎片ID和预判类别。"""

    model_config = ConfigDict(extra="forbid")
    main_work: str = Field(
        min_length=1, description="按阅读顺序合并的全部OCR文字，换行不是强制业务边界"
    )


class MainWorkValues(BaseModel):
    """三个字段必须明确返回；不存在的类别为null，内容必须依据原文。"""

    model_config = ConfigDict(extra="forbid")
    construction: str | None = Field(
        description="施工部位、工序和进展；保留全部事实与关键数据，不摘要"
    )
    witness: str | None = Field(
        description="旁站活动、过程和检测记录；保留全部事实与关键数据，不摘要"
    )
    patrol: str | None = Field(
        description="巡视检查、现场观察及质量安全状态；保留全部事实与关键数据，不摘要"
    )

    @field_validator("construction", "witness", "patrol")
    @classmethod
    def trim_content(cls, text: str | None) -> str | None:
        return text.strip() or None if text is not None else None


class JournalProcessRequest(BaseModel):
    """独立文本处理请求；允许空文本，不引入会话或图片依赖。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    main_work: str


type JournalPoint = tuple[FiniteFloat, FiniteFloat]
type JournalPolygon = tuple[JournalPoint, JournalPoint, JournalPoint, JournalPoint]
type RecognitionConfidence = Annotated[FiniteFloat, Field(ge=0, le=1)]
type JournalFieldKey = Literal[
    "project",
    "number",
    "supervision_org",
    "recorder",
    "weather",
    "position",
    "date",
    "reviewer",
    "main_work",
    "issues",
    "next_day_plan",
]


class JournalOutput(BaseModel):
    """识别结果拒绝额外字段，不向 HTTP 暴露内部图像和矩阵。"""

    model_config = ConfigDict(extra="forbid")


class JournalImageInfo(JournalOutput):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinateSpace: Literal["exif_corrected_original"]


class JournalOCRBox(JournalOutput):
    id: str
    text: str
    confidence: RecognitionConfidence
    polygon: JournalPolygon


class JournalOCRField(JournalOutput):
    key: JournalFieldKey
    label: str
    text: str | None
    confidence: RecognitionConfidence
    polygon: JournalPolygon
    boxIds: list[str]
    ambiguous: bool
    visibleFraction: RecognitionConfidence


class JournalRecognitionData(JournalOutput):
    taskId: str | None
    documentType: Literal["supervision_diary"]
    image: JournalImageInfo
    tablePolygon: JournalPolygon
    boxes: list[JournalOCRBox]
    fields: list[JournalOCRField]


class JournalRecognitionResponse(JournalOutput):
    status: Literal[200]
    message: Literal["识别完成"]
    data: JournalRecognitionData
