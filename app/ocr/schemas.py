"""文档加工请求；保留 docsvc 字段和空输出语义。"""

import math
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    path: str = Field(min_length=1)
    form: str = ""


class JianbiaoReq(OCRRequest):
    path: str = Field(min_length=1)
    form: str = Field(min_length=1)
    cfg: dict
    bound: dict = Field(default_factory=dict)
    out: str = ""


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
    drawings: list[str]
    basis: dict | None = None

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
