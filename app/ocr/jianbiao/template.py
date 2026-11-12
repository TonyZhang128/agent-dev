"""简表 schema2 模板及行组字段展开。"""

import json
import math
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type Rect = tuple[float, float, float, float]
type Point = tuple[float, float]

GEOMETRY_TOLERANCE = 1e-6
ASPECT_MIN_FACTOR = 0.65
ASPECT_MAX_FACTOR = 1.5


def _check_rectangle(rect: Rect) -> Rect:
    if not all(math.isfinite(coordinate) for coordinate in rect) or rect[2] <= 0 or rect[3] <= 0:
        raise ValueError("简表区域坐标必须有限且宽高为正")
    return rect


class TemplateLine(BaseModel):
    """相对表格外框的归一化分隔线。"""

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


class TemplateField(BaseModel):
    """一个可填写区域及其在简表中的业务字段 ID。"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    key: str
    label: str = ""
    aliases: tuple[str, ...] = ()
    kind: Literal["text", "date", "number"] = "text"
    rect_in_table: Rect
    label_rect_in_table: Rect | None = None
    inside_table: bool = True

    @field_validator("rect_in_table", "label_rect_in_table")
    @classmethod
    def check_rectangle(cls, rect: Rect | None) -> Rect | None:
        return None if rect is None else _check_rectangle(rect)


class RecordColumn(BaseModel):
    """记录区中一列的标签和整列范围。"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    key: str
    label: str
    aliases: tuple[str, ...] = ()
    kind: Literal["text", "date", "number"] = "text"
    label_rect_in_table: Rect
    column_rect_in_table: Rect

    @field_validator("label_rect_in_table", "column_rect_in_table")
    @classmethod
    def check_rectangle(cls, rect: Rect) -> Rect:
        return _check_rectangle(rect)


class RowGroup(BaseModel):
    """一条记录及四个单元格的表格相对坐标。"""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    record_index: int = Field(ge=1)
    rect_in_table: Rect
    cells: dict[str, Rect]

    @field_validator("rect_in_table")
    @classmethod
    def check_rectangle(cls, rect: Rect) -> Rect:
        return _check_rectangle(rect)

    @field_validator("cells")
    @classmethod
    def check_cells(cls, cells: dict[str, Rect]) -> dict[str, Rect]:
        for rect in cells.values():
            _check_rectangle(rect)
        return cells


class CoordinateSystem(BaseModel):
    """模板坐标的自描述信息；运行时只接受表格左上角归一化坐标。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    origin: Literal["table_top_left"]
    x_axis: Literal["right"]
    y_axis: Literal["down"]
    rect_format: Literal["[x, y, width, height]"]
    unit: str
    note: str


class JianbiaoTemplate(BaseModel):
    """schema2 原始配置；fields 属性向几何与识别层提供展开后的45个值区。"""

    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, populate_by_name=True
    )

    schema_version: Literal[2] = 2
    template_id: str
    template_name: str
    template_version: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page_size: Point
    source_table_bounds: Rect
    table_aspect: float = Field(gt=0, description="来源表格宽度／高度")
    lines: tuple[TemplateLine, ...]
    common_fields: tuple[TemplateField, ...] = Field(alias="fields")
    record_columns: tuple[RecordColumn, ...]
    row_groups: tuple[RowGroup, ...]
    coordinate_system: CoordinateSystem

    @model_validator(mode="after")
    def check_geometry_and_records(self) -> Self:
        left, top, right, bottom = self.source_table_bounds
        if left < 0 or top < 0 or right <= left or bottom <= top:
            raise ValueError("简表来源表格区域无效")
        if right > self.source_page_size[0] or bottom > self.source_page_size[1]:
            raise ValueError("简表来源表格区域越过页面")
        if not math.isclose(
            self.table_aspect,
            (right - left) / (bottom - top),
            rel_tol=GEOMETRY_TOLERANCE,
        ):
            raise ValueError("table_aspect 必须是来源表格宽度／高度")
        common_keys = [field.key for field in self.common_fields]
        column_keys = [column.key for column in self.record_columns]
        if len(common_keys) != len(set(common_keys)) or len(column_keys) != len(set(column_keys)):
            raise ValueError("简表公共字段和记录列键必须各自唯一")
        if set(common_keys) & set(column_keys):
            raise ValueError("简表公共字段和记录列键不能重复")
        row_indices = [row.record_index for row in self.row_groups]
        if row_indices != list(range(1, len(row_indices) + 1)):
            raise ValueError("记录行必须从1开始连续编号")
        for row in self.row_groups:
            if set(row.cells) != set(column_keys):
                raise ValueError("每个记录行必须包含全部且唯一的记录列")
        return self

    @property
    def height_aspect(self) -> float:
        """透视校正使用的高度／宽度；原始文件明确保存其倒数。"""
        return 1 / self.table_aspect

    @property
    def aspect_range(self) -> tuple[float, float]:
        """允许现场透视造成有限纵横比变化，不接受任意四边形。"""
        return (
            self.height_aspect * ASPECT_MIN_FACTOR,
            self.height_aspect * ASPECT_MAX_FACTOR,
        )

    @property
    def fields(self) -> tuple[TemplateField, ...]:
        """把 record_columns × row_groups 展开为字段匹配使用的独立值区。"""
        record_fields: list[TemplateField] = []
        for row in self.row_groups:
            for column in self.record_columns:
                indexed_labels = tuple(
                    f"{label}{row.record_index}" for label in (column.label, *column.aliases)
                )
                record_fields.append(
                    TemplateField(
                        key=f"{column.key}_{row.record_index}",
                        label=f"{column.label}{row.record_index}",
                        aliases=indexed_labels,
                        kind=column.kind,
                        rect_in_table=row.cells[column.key],
                    )
                )
        return (*self.common_fields, *record_fields)


def load_template(template_id: str) -> JianbiaoTemplate:
    """按受控目录加载模板；旧业务编号可作为同一文件的兼容别名。"""
    root = Path(__file__).with_name("templates")
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    filename = catalog.get(template_id)
    if not isinstance(filename, str):
        raise ValueError(f"未配置简表模板：{template_id}")
    template = JianbiaoTemplate.model_validate_json((root / filename).read_bytes())
    if catalog.get(template.template_id) != filename:
        raise ValueError("简表模板目录与模板 ID 不一致")
    return template
