"""监理日志（现场版）的页面版式与识别参数。

字段 rect 为整页比例坐标，按样例照片的表格外框、行列线和栏目文字标定：
表格外框约 (0.112, 0.227)-(0.886, 0.888)；横向分为标签列、左值区、右标签列、
右值区；纵向按 supervision_org、recorder/weather、position/date、mainWork、
issues、next_day_plan 六段。换表样版本时只需要重新标定本文件，不涉及识别算法。

"当日主要监理工作情况"的 construction / witness / patrol 三个子栏在样例表上是
同一个 mainWork 单元格，用印刷小标题分隔。识别链只读取整格文字；接口层再按可靠
标题或模型分类把原文拆分到三个子栏，拆分逻辑不改变本文件的识别参数。
"""

from app.ocr.journal.types import FieldSpec

FORM_CODE = "JLB13"
FORM_NAME = "监理日志"
DOCUMENT_TYPE = "supervision_diary"

# A4 竖版表样；页面比例坐标按此纵横比换算像素。
PAGE_ASPECT = 841.9 / 595.3

# 表格外框在整页中的比例位置：定位到表格四边形后，用这四个角把照片锚回整页。
TABLE_RECT = (0.112, 0.227, 0.886, 0.888)

# 输入与校正画布：按表格实际像素宽度保留文字密度，再限制上下限和最大边。
INPUT_MAX_SIDE = 6000
CANVAS_MIN_WIDTH = 1200
CANVAS_MAX_WIDTH = 2000
CANVAS_MAX_SIDE = 2600

# 定位：候选四边形至少占照片面积的比例；内部线像素占比高于该值视为表格而非纸张。
MIN_QUAD_AREA_RATIO = 0.15
TABLE_LINE_DENSITY = 0.006

# 框归属：中心点优先，覆盖率兜底；前两名接近时标记歧义。
MATCH_COVERAGE_MIN = 0.5
MATCH_CENTER_MARGIN = 0.002
MATCH_AMBIGUITY_MARGIN = 0.2

# 歧义/漏框字段的补充识别上限；常见路径仍然只有一次整页 OCR。
MAX_FALLBACK_FIELDS = 3
FALLBACK_MARGIN = 0.01

FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="project",
        label="公路工程项目",
        rect=(0.300, 0.116, 0.280, 0.060),
        aliases=("项目名称", "工程项目"),
    ),
    FieldSpec(
        key="number",
        label="编号",
        rect=(0.772, 0.203, 0.114, 0.031),
    ),
    FieldSpec(
        key="supervision_org",
        label="监理机构",
        rect=(0.246, 0.229, 0.640, 0.057),
        aliases=("监理单位",),
    ),
    FieldSpec(
        key="recorder",
        label="记录人",
        rect=(0.246, 0.287, 0.324, 0.052),
    ),
    FieldSpec(
        key="weather",
        label="天气",
        rect=(0.728, 0.287, 0.158, 0.052),
        aliases=("天气情况",),
    ),
    FieldSpec(
        key="position",
        label="岗位",
        rect=(0.246, 0.339, 0.324, 0.059),
    ),
    FieldSpec(
        key="date",
        label="记录时间",
        rect=(0.728, 0.339, 0.158, 0.059),
        kind="date",
        aliases=("日期",),
    ),
    FieldSpec(
        key="reviewer",
        label="审核人",
        rect=(0.752, 0.888, 0.138, 0.030),
    ),
    FieldSpec(
        key="mainWork",
        label="当日主要监理工作情况",
        rect=(0.246, 0.398, 0.640, 0.223),
    ),
    FieldSpec(
        key="issues",
        label="发现的问题及处理结果",
        rect=(0.246, 0.621, 0.640, 0.147),
        aliases=("发现的问题", "问题及处理情况", "问题及处理结果"),
    ),
    FieldSpec(
        key="next_day_plan",
        label="次日工作计划和管控重点",
        rect=(0.246, 0.768, 0.640, 0.120),
        aliases=("次日工作计划",),
    ),
)
