"""文档加工请求；保留 docsvc 字段和空输出语义。"""

import math
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OCRRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("cfg", check_fields=False)
    @classmethod
    def validate_configuration(cls, value: dict) -> dict:
        """只校验处理链实际消费的字段，其余配置元数据原样保留。"""
        for key, required in (
            ("formulas", ("target", "expr")),
            ("anchors", ("id", "doc", "field", "kind")),
            ("edges", ("id", "type", "to")),
        ):
            items = value.get(key, [])
            if not isinstance(items, list):
                raise ValueError(f"cfg.{key} 必须为对象数组")
            for item in items:
                if not isinstance(item, dict) or any(
                    not isinstance(item.get(name), str) or not item[name].strip()
                    for name in required
                ):
                    raise ValueError(f"cfg.{key} 缺少有效字段：{', '.join(required)}")
                if key == "anchors" and item["kind"] == "PDF_REGION":
                    cls.validate_rectangle(item.get("rect"))
                if key == "anchors" and item["kind"] == "EXCEL_RANGE":
                    address = item.get("range")
                    if not isinstance(address, str) or not re.fullmatch(
                        r"[A-Za-z]{1,3}[1-9]\d{0,6}", address
                    ):
                        raise ValueError("EXCEL_RANGE 必须指定单元格地址，如 A3")
                if key == "edges":
                    field = {"COPY": "from", "TEMPLATE": "template"}.get(item["type"])
                    if field and not isinstance(item.get(field), str):
                        raise ValueError(f"cfg.edges 缺少 {field} 字符串")
        return value

    @staticmethod
    def validate_rectangle(rectangle: object) -> None:
        if not isinstance(rectangle, dict) or any(
            isinstance(rectangle.get(key), bool)
            or not isinstance(rectangle.get(key), (int, float))
            or not math.isfinite(rectangle[key])
            for key in "xywh"
        ):
            raise ValueError("坐标必须包含有限数值 x、y、w、h")
        if rectangle["w"] <= 0 or rectangle["h"] <= 0:
            raise ValueError("坐标宽高必须大于零")


class RecognizeReq(OCRRequest):
    path: str = Field(default="", description="PROJECTS_ROOT 数据池内的照片路径")
    form: str = ""
    img: str = Field(default="", description="base64 编码的图片数据；path 与 img 至少提供一个")

    @model_validator(mode="after")
    def validate_source(self) -> "RecognizeReq":
        self.path = self.path.strip()
        self.img = self.img.strip()
        if not self.path and not self.img:
            raise ValueError("path 与 img 至少提供一个")
        return self


class DailyLogsReq(OCRRequest):
    path: str = Field(default="", description="PROJECTS_ROOT 数据池内的监理日志照片路径")
    img: str = Field(default="", description="base64 编码的图片数据；path 与 img 至少提供一个")

    @model_validator(mode="after")
    def validate_source(self) -> "DailyLogsReq":
        self.path = self.path.strip()
        self.img = self.img.strip()
        if not self.path and not self.img:
            raise ValueError("path 与 img 至少提供一个")
        return self


class JianbiaoReq(OCRRequest):
    path: str = Field(default="", description="PROJECTS_ROOT 数据池内的照片路径")
    img: str = Field(default="", description="base64 编码的图片数据；path 与 img 至少提供一个")
    form: str = Field(min_length=1)
    cfg: dict
    bound: dict = Field(default_factory=dict)
    out: str = ""

    @model_validator(mode="after")
    def validate_source(self) -> "JianbiaoReq":
        self.path = self.path.strip()
        self.img = self.img.strip()
        if not self.path and not self.img:
            raise ValueError("path 与 img 至少提供一个")
        return self


class FillReq(OCRRequest):
    form: str = Field(min_length=1)
    cfg: dict
    values: dict
    out: str = ""
    rects: dict = Field(default_factory=dict)

    @field_validator("rects")
    @classmethod
    def validate_rectangles(cls, value: dict) -> dict:
        for rectangle in value.values():
            cls.validate_rectangle(rectangle)
        return value


class DraftReq(OCRRequest):
    prefix: str = Field(min_length=1)
    drawings: list[str] = Field(
        default_factory=list, description="PROJECTS_ROOT 数据池内的 PDF 路径或目录列表"
    )
    imgs: list[str] = Field(
        default_factory=list,
        description="base64 编码的 PDF 数据列表；drawings 与 imgs 至少提供一个",
    )
    basis: dict | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "DraftReq":
        has_basis = self.basis is not None and (self.basis.get("facts") or self.basis.get("roads"))
        if not self.drawings and not self.imgs and not has_basis:
            raise ValueError("drawings、imgs 与 basis.facts/roads 至少提供一个")
        return self

    @field_validator("basis")
    @classmethod
    def validate_basis(cls, value: dict | None) -> dict | None:
        if value is not None:
            try:
                facts = dict(value.get("facts") or [])
            except (TypeError, ValueError) as exc:
                raise ValueError("basis.facts 必须为键值对数组或对象") from exc
            if "路线起讫" in facts and not isinstance(facts["路线起讫"], str):
                raise ValueError("basis.facts 的路线起讫必须为桩号字符串")
        return value
