"""表格归一化模板；PDF 页面信息仅用于离线来源追溯和覆盖图。"""

import math
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ocr.core.resources import resource_cache
from app.ocr.journal.models import FieldLayout

type Rect = tuple[float, float, float, float]
type Point = tuple[float, float]

FIELD_KEYS = (
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
)
GEOMETRY_TOLERANCE = 1e-6


def bounds_to_table(rect: Rect, table_bounds: Rect) -> Rect:
    """PDF x0/y0/x1/y1 → table相对u/v/w/h，允许表外区域。"""
    left, top, right, bottom = table_bounds
    width, height = right - left, bottom - top
    return (
        (rect[0] - left) / width,
        (rect[1] - top) / height,
        (rect[2] - rect[0]) / width,
        (rect[3] - rect[1]) / height,
    )


def table_to_pdf_bounds(rect: Rect, table_bounds: Rect) -> Rect:
    """仅供离线覆盖图：table u/v/w/h → 来源PDF坐标。"""
    left, top, right, bottom = table_bounds
    u, v, width, height = rect
    return (
        left + u * (right - left),
        top + v * (bottom - top),
        left + (u + width) * (right - left),
        top + (v + height) * (bottom - top),
    )


class TemplateField(BaseModel):
    """标签和值区均为table归一化u/v/w/h，不是页面比例。"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    kind: Literal["text", "date"] = "text"
    rect_in_table: Rect
    label_rect_in_table: Rect
    inside_table: bool = True

    @field_validator("rect_in_table", "label_rect_in_table")
    @classmethod
    def check_rectangle(cls, rect: Rect) -> Rect:
        if (
            not all(math.isfinite(coordinate) for coordinate in rect)
            or rect[2] <= 0
            or rect[3] <= 0
        ):
            raise ValueError("表格相对区域坐标必须有限且宽高为正")
        return rect


class TemplateLine(BaseModel):
    """table归一化分隔线：position是法向坐标，start/end是沿线坐标。"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    axis: Literal["horizontal", "vertical"]
    position: float
    start: float
    end: float

    @model_validator(mode="after")
    def check_extent(self) -> Self:
        if self.end <= self.start:
            raise ValueError("分隔线长度必须为正")
        return self


class JournalTemplate(BaseModel):
    """运行时只消费table相对字段、分隔线和纵横比。"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal[2] = 2
    template_id: Literal["supervision_diary"] = "supervision_diary"
    template_version: Literal[2] = 2
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page_size: Point
    source_table_bounds: Rect
    table_aspect: float = Field(gt=0)
    lines: tuple[TemplateLine, ...]
    fields: tuple[TemplateField, ...]

    @model_validator(mode="after")
    def check_geometry(self) -> Self:
        left, top, right, bottom = self.source_table_bounds
        if left < 0 or top < 0 or right <= left or bottom <= top:
            raise ValueError("PDF表格来源区域无效")
        if right > self.source_page_size[0] or bottom > self.source_page_size[1]:
            raise ValueError("PDF表格来源区域越过页面")
        if not math.isclose(
            self.table_aspect, (bottom - top) / (right - left), rel_tol=GEOMETRY_TOLERANCE
        ):
            raise ValueError("table纵横比与来源几何不一致")
        keys = [field.key for field in self.fields]
        if len(keys) != len(FIELD_KEYS) or set(keys) != set(FIELD_KEYS):
            raise ValueError("模板必须包含全部且唯一的11个字段")
        for field in self.fields:
            if field.inside_table:
                u, v, width, height = field.rect_in_table
                if (
                    min(u, v) < -GEOMETRY_TOLERANCE
                    or max(u + width, v + height) > 1 + GEOMETRY_TOLERANCE
                ):
                    raise ValueError("表内值区必须位于table内")
        return self

    def field_layouts(self) -> tuple[FieldLayout, ...]:
        """直接传递table几何，不读取来源页面尺寸来重新标定字段。"""
        return tuple(
            FieldLayout(
                key=field.key,
                label=field.label,
                kind=field.kind,
                aliases=field.aliases,
                rect_in_table=field.rect_in_table,
                label_rect_in_table=field.label_rect_in_table,
            )
            for field in self.fields
        )


@resource_cache(maxsize=1)
def load_template() -> JournalTemplate:
    """只加载新版产物，不保留页面比例模板兼容分支。"""
    snapshot = Path(__file__).with_name("templates") / "journal.json"
    return JournalTemplate.model_validate_json(snapshot.read_bytes())
