"""文档加工请求；保留 docsvc 字段和空输出语义。"""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    ValidationInfo,
    field_validator,
    model_validator,
)


class JianbiaoReq(BaseModel):
    """简表照片识别请求；form 取模板 ID 或兼容别名，out 非空时在数据池内写出结果文件。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str = Field(default="", description="PROJECTS_ROOT 数据池内的简表照片路径")
    img: str = Field(default="", description="base64 编码的图片数据；path 与 img 至少提供一个")
    form: str = Field(
        min_length=1,
        max_length=128,
        description="简表模板 ID 或兼容别名，如 subgrade_spot_check（JB12-4.5.2-4）",
    )
    cfg: dict[str, Any] = Field(default_factory=dict, description="预留识别配置，当前版本不使用")
    bound: dict[str, Any] = Field(default_factory=dict, description="预留识别范围，当前版本不使用")
    out: str = Field(
        default="",
        description="数据池内输出目录；非空时写出 response.json、diagnostics.json 和"
        " aligned.png，空则不写文件",
    )
    task_id: str = Field(
        default="",
        alias="taskId",
        title="TaskId",
        max_length=128,
        description="业务任务 ID，仅原样回显到 data.taskId；不传则为 null",
    )

    @model_validator(mode="after")
    def validate_source(self) -> "JianbiaoReq":
        self.path = self.path.strip()
        self.img = self.img.strip()
        self.form = self.form.strip()
        self.out = self.out.strip()
        self.task_id = self.task_id.strip()
        if not self.path and not self.img:
            raise ValueError("path 与 img 至少提供一个")
        return self


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


class JournalProcessRequest(JournalRecognitionData):
    """接收完整识别结果；同一栏目必须恰好出现一次，避免静默丢失或覆盖。"""

    fields: list[JournalOCRField] = Field(min_length=11, max_length=11)

    @model_validator(mode="after")
    def validate_fields(self) -> "JournalProcessRequest":
        expected = {
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
        }
        if {field.key for field in self.fields} != expected:
            raise ValueError("识别结果必须完整包含 11 个不同栏目")
        return self


class JournalTextRequest(JournalOutput):
    """只将工作原文传入模型，其他栏目在业务层透传。"""

    content: str = Field(min_length=1)


class JournalRecord(JournalOutput):
    """规范化生成文本；不用于需要原样返回的识别字段。"""

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def trim_text(cls, text: object, info: ValidationInfo) -> object:
        if info.field_name == "content":
            return text
        return text.strip() or None if isinstance(text, str) else text


class JournalPatrol(JournalRecord):
    inspectionScope: str | None = Field(description="巡视范围；无依据时为 null")
    mainConstruction: str | None = Field(description="巡视所见主要施工情况")
    qualitySafetyEnvironment: str | None = Field(description="已记录的质量、安全、环保情况")
    problemsAndActions: str | None = Field(description="发现的问题及处理意见，不编造整改动作")


class JournalWitness(JournalRecord):
    supervisionProject: str | None = Field(description="旁站项目或明确未开展旁站的记录")
    constructionProcess: str | None = Field(description="旁站施工过程简述")
    supervisionWork: str | None = Field(description="实际旁站工作，不编造检查和取样")
    mainDataRecords: str | None = Field(description="原文中的主要数据、指标及单位")
    problemsAndResults: str | None = Field(description="发现的问题及处理结果，不推测完成状态")


class JournalWorkValues(JournalRecord):
    construction: str | None = Field(description="主要施工情况，保留关键事实与数据")
    patrol: JournalPatrol
    witness: JournalWitness


class JournalWork(JournalWorkValues):
    content: str


class JournalCommon(JournalOutput):
    projectName: str | None
    documentNo: str | None
    supervisionOrg: str | None
    recorderName: str | None
    recorderPosition: str | None
    weather: str | None
    logDate: str | None
    reviewerName: str | None


class JournalFields(JournalOutput):
    mainWork: JournalWork
    issues: str | None
    nextDayPlan: str | None


class JournalData(JournalOutput):
    common: JournalCommon
    fields: JournalFields


class JournalResponseData(JournalOutput):
    jsonData: JournalData


class JournalResponse(JournalOutput):
    code: Literal[200]
    message: Literal["success"]
    data: JournalResponseData
