"""从当前 FastAPI 应用生成对外 OpenAPI 草案，并补充代码无法自动表达的响应与错误。

正式契约不得由本模块直接写入 `interfaces/openapi/`。导出脚本只生成待确认草案；
用户批准后由人工提升为正式契约。校验脚本只比较，不改写任何契约文件。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.main import create_app
from app.schemas.agents import BusinessIntentResult

ROOT = Path(__file__).resolve().parents[2]
DRAFT_PATH = ROOT / "interfaces/drafts/fastapi.openapi.json"
OFFICIAL_PATH = ROOT / "interfaces/openapi/fastapi.openapi.json"

JSON_MEDIA_TYPE = "application/json"

VALIDATION_ERROR_ITEM = "ValidationErrorItem"
REQUEST_ERROR = "RequestError"
ERROR_DETAIL = "ErrorDetail"


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _json_response(
    description: str,
    schema: dict[str, Any] | None = None,
    *,
    example: Any = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {"description": description}
    if schema is not None:
        media: dict[str, Any] = {"schema": schema}
        if example is not None:
            media["example"] = example
        response["content"] = {JSON_MEDIA_TYPE: media}
    return response


def _error_response(description: str) -> dict[str, Any]:
    return _json_response(description, ref(ERROR_DETAIL))


REQUEST_ERROR_RESPONSE = _json_response(
    "请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。",
    ref(REQUEST_ERROR),
)


def _envelope_schema(data_schema: str, description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "data"],
        "properties": {
            "status": {
                "type": "integer",
                "const": 200,
                "description": "业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。",
            },
            "data": ref(data_schema),
        },
        "description": description,
    }


SCHEMAS: dict[str, dict[str, Any]] = {
    "ValidationErrorItem": {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "loc", "msg"],
        "properties": {
            "type": {"type": "string", "description": "Pydantic 错误类型。"},
            "loc": {
                "type": "array",
                "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                "description": "错误位置，例如 body、history、0、role。",
            },
            "msg": {"type": "string", "description": "可公开的错误说明。"},
        },
        "description": "校验错误项。实际响应省略 input 与 ctx，避免回显原始身份、历史和输入。",
    },
    "RequestError": {
        "type": "object",
        "additionalProperties": False,
        "required": ["detail"],
        "properties": {
            "detail": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": ref(VALIDATION_ERROR_ITEM)},
                ],
                "description": "请求校验失败时为错误数组；输入或上下文超限时为字符串。",
            }
        },
        "description": "422 统一错误响应。",
    },
    "ErrorDetail": {
        "type": "object",
        "additionalProperties": False,
        "required": ["detail"],
        "properties": {
            "detail": {
                "type": "string",
                "description": "脱敏后的错误说明，不包含密钥、原始输入、身份、历史或上游错误正文。",
            }
        },
        "description": "非校验类错误响应。",
    },
    "HealthResponse": {
        "type": "object",
        "additionalProperties": False,
        "required": ["status"],
        "properties": {
            "status": {"type": "string", "const": "ok", "description": "进程存活标记。"}
        },
    },
    "ReadyResponse": {
        "type": "object",
        "additionalProperties": False,
        "required": ["status"],
        "properties": {
            "status": {
                "type": "string",
                "const": "ready",
                "description": "配置模型已出现在上游模型列表。",
            }
        },
    },
    "DependencyStatus": {
        "type": "object",
        "additionalProperties": True,
        "required": ["name", "ok"],
        "properties": {
            "name": {"type": "string"},
            "ok": {"type": "boolean"},
            "version": {"type": "string"},
            "error": {"type": "string"},
        },
        "description": "单个依赖的导入检查结果。",
    },
    "CapabilityStatus": {
        "type": "object",
        "additionalProperties": True,
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "deps": {"type": "array", "items": ref("DependencyStatus")},
            "SIFT": {"type": "boolean"},
            "ORB": {"type": "boolean"},
            "providers": {"type": "array", "items": {"type": "string"}},
            "error": {"type": "string"},
        },
        "description": "按能力分组的依赖检查结果；不同能力的字段不完全相同。",
    },
    "HealthDepsData": {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok", "caps"],
        "properties": {
            "ok": {"type": "boolean", "description": "全部依赖是否可用。"},
            "caps": {
                "type": "object",
                "additionalProperties": ref("CapabilityStatus"),
                "description": "能力名 → 检查结果。能力名包括 PDF、Excel、图像、文字识别、"
                "模型推理、OpenCV 特征和推理设备。",
            },
        },
    },
    "HealthDepsResponse": _envelope_schema("HealthDepsData", "依赖自检成功响应。"),
    "ImageSize": {
        "type": "object",
        "additionalProperties": False,
        "required": ["width", "height"],
        "properties": {
            "width": {"type": "integer", "minimum": 1},
            "height": {"type": "integer", "minimum": 1},
        },
        "description": "输入图片的像素尺寸。",
    },
    "AlignInfo": {
        "type": "object",
        "additionalProperties": False,
        "required": ["anchors", "how"],
        "properties": {
            "anchors": {"type": "integer", "minimum": 0, "description": "匹配到的表样锚点数。"},
            "how": {
                "type": "string",
                "enum": ["anchors", "mismatch", "none"],
                "description": "anchors 表示按模板坐标取值；mismatch 表示照片与表样对不上；"
                "none 表示没有可用模板坐标。",
            },
            "ax": {"type": "number", "description": "表样 x 比例到照片像素的缩放系数。"},
            "bx": {"type": "number", "description": "表样 x 比例到照片像素的偏移。"},
            "ay": {"type": "number", "description": "表样 y 比例到照片像素的缩放系数。"},
            "by": {"type": "number", "description": "表样 y 比例到照片像素的偏移。"},
        },
    },
    "RecognizeDetailItem": {
        "type": "object",
        "additionalProperties": False,
        "required": ["field", "value", "how", "conf", "boxes"],
        "properties": {
            "field": {"type": "string"},
            "value": {"type": "string"},
            "how": {
                "type": "string",
                "enum": ["inline", "rect", "right"],
                "description": "inline 为栏目名同行；rect 为模板坐标内；right 为栏目名右侧。",
            },
            "conf": {"type": "number", "minimum": 0, "maximum": 1},
            "boxes": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "description": "来源文字框 [x0, y0, x1, y1]。",
            },
        },
    },
    "OcrLine": {
        "type": "object",
        "additionalProperties": False,
        "required": ["s", "box", "conf"],
        "properties": {
            "s": {"type": "string", "description": "原始 OCR 文字。"},
            "box": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 4,
                "maxItems": 4,
                "description": "文字框 [x0, y0, x1, y1]。",
            },
            "conf": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
    "RecognizeData": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "form",
            "formName",
            "layout",
            "fields",
            "keys",
            "detail",
            "warning",
            "align",
            "image",
            "lines",
            "ms",
        ],
        "properties": {
            "form": {"type": "string", "description": "请求中的表号；未指定时为空字符串。"},
            "formName": {"type": "string", "description": "模板库中的表名；未知表号时为空字符串。"},
            "layout": {"type": "boolean", "description": "是否加载到表样版面坐标。"},
            "fields": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "栏目字段 → 识别值；未识别到的栏目不出现。",
            },
            "keys": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "第二册关键项目合格率等字段；仅按模板坐标对齐时产生。",
            },
            "detail": {"type": "array", "items": ref("RecognizeDetailItem")},
            "warning": {
                "type": "string",
                "description": "表号缺失、模板缺失或照片与表样不匹配时的提示；空字符串表示无提示。",
            },
            "align": ref("AlignInfo"),
            "image": ref("ImageSize"),
            "lines": {"type": "array", "items": ref("OcrLine")},
            "ms": {"type": "integer", "minimum": 0, "description": "本次识别耗时，毫秒。"},
        },
        "description": "普通照片/简表照片识别草稿；200 不代表每个字段都准确。",
    },
    "RecognizeResponse": _envelope_schema("RecognizeData", "普通照片识别成功响应。"),
    "Frame": {
        "type": "object",
        "additionalProperties": False,
        "required": ["how", "quad"],
        "properties": {
            "how": {
                "type": "string",
                "enum": ["contour", "contour+table", "whole", "whole+table"],
                "description": "外框定位方式；whole 表示未找到轮廓，按整张照片校正。",
            },
            "quad": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 4,
                "maxItems": 4,
                "description": "照片坐标系中的四角 [[x, y], ...]。",
            },
        },
    },
    "DailyLogsDetailItem": {
        "type": "object",
        "additionalProperties": False,
        "required": ["field", "label", "value", "conf", "rect"],
        "properties": {
            "field": {"type": "string"},
            "label": {"type": "string"},
            "value": {"type": "string"},
            "conf": {"type": "number", "minimum": 0, "maximum": 1},
            "rect": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": "校正后页面中的识别区域 [x0, y0, x1, y1]。",
            },
        },
    },
    "DailyLogsRecognized": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "project": {"type": "string"},
            "number": {"type": "string"},
            "supervision_org": {"type": "string"},
            "recorder": {"type": "string"},
            "date": {"type": "string", "description": "归一为 yyyy-mm-dd；识别不到时省略。"},
            "reviewer": {"type": "string"},
            "weather": {"type": "string"},
            "construction": {"type": "string"},
            "supervision_work": {"type": "string"},
            "issues": {"type": "string"},
        },
        "description": "JLB13 监理日志固定栏目；未识别到的栏目可能省略。",
    },
    "DailyLogsData": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "form",
            "formName",
            "frame",
            "recognized",
            "detail",
            "processed",
            "warning",
            "image",
            "ms",
        ],
        "properties": {
            "form": {"type": "string", "const": "JLB13"},
            "formName": {"type": "string", "const": "监理日志"},
            "frame": ref("Frame"),
            "recognized": ref("DailyLogsRecognized"),
            "detail": {"type": "array", "items": ref("DailyLogsDetailItem")},
            "processed": {
                "type": "object",
                "additionalProperties": True,
                "description": "监理日志后处理占位，当前固定为 {}。",
            },
            "warning": {
                "type": "string",
                "description": "未检测到表格外框等定位提示；空字符串表示无提示。",
            },
            "image": ref("ImageSize"),
            "ms": {"type": "integer", "minimum": 0},
        },
        "description": "JLB13 监理日志识别草稿；调用方应优先使用 recognized 和 detail。",
    },
    "DailyLogsResponse": _envelope_schema("DailyLogsData", "监理日志识别成功响应。"),
    "CellDetailItem": {
        "type": "object",
        "additionalProperties": False,
        "required": ["field", "label", "value", "conf", "rect"],
        "properties": {
            "field": {"type": "string"},
            "label": {"type": "string"},
            "value": {"type": "string"},
            "conf": {"type": "number", "minimum": 0, "maximum": 1},
            "rect": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
            },
        },
    },
    "RatioRect": {
        "type": "object",
        "additionalProperties": False,
        "required": ["x", "y", "w", "h"],
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "w": {"type": "number", "exclusiveMinimum": 0},
            "h": {"type": "number", "exclusiveMinimum": 0},
        },
        "description": "页面比例坐标；与简表 cells 的 [x, y, w, h] 数组语义相同但表示不同。",
    },
    "AnchoredCell": {
        "type": "object",
        "additionalProperties": False,
        "required": ["anchor", "field", "behavior", "rect", "value", "src"],
        "properties": {
            "anchor": {
                "type": "string",
                "description": "配置锚点 ID；模板或网格补位时为空字符串。",
            },
            "field": {"type": "string"},
            "behavior": {"type": "string"},
            "rect": ref("RatioRect"),
            "value": {"type": "string"},
            "src": {
                "type": "string",
                "description": "取值来源，例如 TEMPLATE、COPY、field、layout、grid。",
            },
        },
    },
    "StringMap": {
        "type": "object",
        "additionalProperties": {"type": "string"},
    },
    "JianbiaoData": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "jianbiao",
            "jianbiaoName",
            "frame",
            "recognized",
            "detail",
            "target",
            "targetName",
            "values",
            "errors",
            "anchors",
            "pdf",
            "xlsx",
            "xlsxSkipped",
            "ms",
        ],
        "properties": {
            "jianbiao": {"type": "string", "description": "匹配到的简表编号。"},
            "jianbiaoName": {"type": "string"},
            "frame": ref("Frame"),
            "recognized": ref("StringMap"),
            "detail": {"type": "array", "items": ref("CellDetailItem")},
            "target": {"type": "string", "description": "目标表号。"},
            "targetName": {"type": "string"},
            "values": ref("StringMap"),
            "errors": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "单条公式失败原因；调用方必须检查，失败字段不会写入计算值。",
            },
            "anchors": {"type": "array", "items": ref("AnchoredCell")},
            "pdf": {
                "type": "string",
                "description": "相对 PROJECTS_ROOT 的 PDF 路径；未写文件时为空字符串。",
            },
            "xlsx": {
                "type": "string",
                "description": "相对 PROJECTS_ROOT 的 Excel 路径；未写文件时为空字符串。",
            },
            "xlsxSkipped": {"type": "array", "items": {"type": "string"}},
            "ms": {"type": "integer", "minimum": 0},
        },
    },
    "JianbiaoResponse": _envelope_schema("JianbiaoData", "简表识别与填表成功响应。"),
    "FillData": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "target",
            "targetName",
            "values",
            "errors",
            "anchors",
            "pdf",
            "xlsx",
            "xlsxSkipped",
        ],
        "properties": {
            "target": {"type": "string"},
            "targetName": {"type": "string"},
            "values": ref("StringMap"),
            "errors": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "单条公式失败原因；调用方必须检查。",
            },
            "anchors": {"type": "array", "items": ref("AnchoredCell")},
            "pdf": {"type": "string"},
            "xlsx": {"type": "string"},
            "xlsxSkipped": {"type": "array", "items": {"type": "string"}},
        },
    },
    "FillResponse": _envelope_schema("FillData", "公式/引用计算与填表成功响应。"),
    "SheetCell": {
        "type": "object",
        "additionalProperties": False,
        "required": ["field", "name", "rect", "behavior", "kind"],
        "properties": {
            "field": {"type": "string", "description": "字段 ID 或格子键。"},
            "name": {"type": "string"},
            "rect": ref("RatioRect"),
            "behavior": {"type": "string"},
            "kind": {"type": "string", "enum": ["layout", "grid"]},
        },
    },
    "SheetCellList": {
        "type": "array",
        "items": ref("SheetCell"),
        "description": "表样上可填的版面栏与其余空格子。",
    },
    "SheetResponse": _envelope_schema("SheetCellList", "表样栏目成功响应。"),
    "WbsSource": {
        "type": "object",
        "additionalProperties": False,
        "required": ["page", "text"],
        "properties": {
            "page": {"type": ["integer", "null"], "description": "来源页码；无法定位时为 null。"},
            "text": {"type": "string", "description": "识别依据原文。"},
        },
    },
    "WbsNode": {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "children"],
        "properties": {
            "code": {"type": "string"},
            "title": {"type": "string"},
            "src": {
                "type": "array",
                "items": ref("WbsSource"),
                "description": "识别依据；仅部分单位工程节点带该字段。",
            },
            "children": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/WbsNode"},
            },
        },
        "description": "单位/分部/分项/子分项递归节点；叶子节点的 children 为 []。",
    },
    "WbsDrawing": {
        "type": "object",
        "additionalProperties": False,
        "required": ["file", "src", "kind", "name", "volume", "chainage"],
        "properties": {
            "file": {"type": "string"},
            "src": {"type": "array", "items": ref("WbsSource")},
            "kind": {"type": "string", "enum": ["bridge", "tunnel", "road"]},
            "name": {"type": "string"},
            "volume": {"type": "string"},
            "chainage": {
                "type": ["array", "null"],
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": "起止桩号（米）；未识别时为 null。",
            },
            "piers": {"type": "array", "items": {"type": "integer"}},
            "abutments": {"type": "array", "items": {"type": "integer"}},
            "spans": {"type": "integer"},
            "split": {"type": "boolean"},
            "girder": {"type": "string"},
            "precast": {"type": "boolean"},
            "partial": {"type": "boolean"},
        },
        "description": "单份施工图的识别摘要；桥梁字段只在 bridge 类型出现。",
    },
    "WbsCount": {
        "type": "object",
        "additionalProperties": False,
        "required": ["units", "parts", "items", "subs"],
        "properties": {
            "units": {"type": "integer", "minimum": 0},
            "parts": {"type": "integer", "minimum": 0},
            "items": {"type": "integer", "minimum": 0},
            "subs": {"type": "integer", "minimum": 0},
        },
    },
    "WbsDraftData": {
        "type": "object",
        "additionalProperties": False,
        "required": ["units", "count", "drawings"],
        "properties": {
            "units": {"type": "array", "items": ref("WbsNode")},
            "count": ref("WbsCount"),
            "drawings": {"type": "array", "items": ref("WbsDrawing")},
        },
    },
    "WbsDraftResponse": _envelope_schema("WbsDraftData", "施工图划分初稿成功响应。"),
}


def _operation(
    *,
    description: str,
    status: str,
    source: str,
    side_effects: str,
    idempotency: str,
    responses: dict[str, Any] | None = None,
    request_example: Any = None,
    summary: str | None = None,
) -> dict[str, Any]:
    operation = {
        "description": description,
        "x-contract-status": status,
        "x-contract-source": source,
        "x-side-effects": side_effects,
        "x-idempotency": idempotency,
    }
    if summary is not None:
        operation["summary"] = summary
    return {
        "operation": operation,
        "responses": responses or {},
        "request_example": request_example,
    }


OPERATIONS: dict[str, dict[str, dict[str, Any]]] = {
    "/health": {
        "get": _operation(
            description="只检查 API 进程是否存活，不访问模型、模板或数据池。",
            summary="检查进程存活",
            status="confirmed",
            source="AGENTS.md 第四节；README.md；tests/test_routing.py",
            side_effects="无",
            idempotency="只读，可安全重试。",
            responses={
                "200": _json_response(
                    "进程存活。",
                    ref("HealthResponse"),
                    example={"status": "ok"},
                )
            },
        )
    },
    "/ready": {
        "get": _operation(
            description="读取上游模型列表，检查配置的 LLM_MODEL 是否存在；不执行推理。",
            summary="检查模型就绪",
            status="confirmed",
            source="AGENTS.md 第四节；docs/agents-api.md；tests/test_routing.py",
            side_effects="无；只发起模型列表请求。",
            idempotency="只读，可安全重试。",
            responses={
                "200": _json_response(
                    "配置模型可用。",
                    ref("ReadyResponse"),
                    example={"status": "ready"},
                ),
                "503": _error_response("模型服务不可达，或模型未安装、名称不匹配。"),
            },
        )
    },
    "/agents/log-summary": {
        "post": _operation(
            description="接收工程表单 OCR 后的文字或 JSON 对象，生成可纳入当日日志的结构化结果。"
            "同步调用模型，不执行 OCR、不写数据库、不保存会话。",
            status="confirmed",
            source="AGENTS.md 第四节；docs/agents-api.md；interfaces/log_summary/；"
            "tests/test_log_summary_interface.py",
            side_effects="无外部业务写入。",
            idempotency="同一输入可能生成不同措辞；重试前应确认业务是否接受。",
            request_example={
                "user_id": "example-user",
                "session_id": "example-session",
                "content": {
                    "项目名称": "示例高速公路项目",
                    "fields": [
                        {"key": "压实度(%)", "measured": [95.2, 94.8, 96.1], "pass_rate": 100}
                    ],
                },
            },
            responses={
                "200": _json_response(
                    "固定六字段成功响应。",
                    ref("LogSummary"),
                    example={
                        "title": "土方路基抽检记录",
                        "date": None,
                        "summary": "泸定至石棉高速公路工程项目TJ9施工标段、JL2监理标段"
                        "K86+300至K86+660土方路基抽检表记录：压实度实测值为95.2%、94.8%、96.1%，"
                        "记录合格率100%；弯沉实测值为0.1、0.2、0.3（单位0.01mm），"
                        "宽度实测值为1000、1005、1010mm，后两项未记录合格率。",
                        "completed_items": [],
                        "pending_items": [],
                        "issues": [],
                    },
                ),
                "422": REQUEST_ERROR_RESPONSE,
                "502": _error_response("上游模型错误、输出截断或未通过 Pydantic 校验。"),
                "503": _error_response("模型服务不可达。"),
                "504": _error_response("模型推理超时。"),
            },
        ),
    },
    "/agents/intent/business": {
        "post": _operation(
            description="识别业务页面和能够完成任务的最小二级功能。目录来自业务功能 JSON，"
            "只识别到一级意图时调用 Chat 澄清；不执行页面跳转。",
            status="confirmed",
            source="用户确认的 intent-business 改造方案；interfaces/intent/；"
            "docs/agents-api.md；tests/test_intent_business.py",
            side_effects="无页面跳转；一级意图或一般交流可能额外调用一次模型。",
            idempotency="同一输入可能生成不同澄清文案、置信度和目录版本之外的文案；"
            "重试前应确认业务是否接受。",
            request_example={
                "user_id": "example-user",
                "session_id": "example-session",
                "message": "我要填写今天的监理日志。",
                "current_page": "workbench",
                "history": [],
            },
            responses={
                "200": _json_response(
                    "层级意图结果；clarify 的 message 为澄清文案，options 为目录内合法功能。",
                    ref("BusinessIntentResult"),
                    example={
                        "status": "resolved",
                        "page": "supervision_diary",
                        "action": "fill_supervision_log",
                        "confidence": 0.95,
                        "message": None,
                        "options": None,
                        "catalog_version": "b158b448e3cf4d0a",
                    },
                ),
                "422": REQUEST_ERROR_RESPONSE,
                "502": _error_response("上游模型错误、输出不合法，或返回目录之外的页面/功能编码。"),
                "503": _error_response("模型服务不可达。"),
                "504": _error_response("分类、聊天或澄清推理超时。"),
            },
        )
    },
    "/agents/intent/archive": {
        "post": _operation(
            description="文件归档系统的意图识别；使用独立 profile，固定 A、B、C、D 占位分类"
            "加 unknown 兜底，没有 chat 分流。",
            status="confirmed",
            source="AGENTS.md 第四节；docs/agents-api.md；interfaces/intent/archive/；"
            "tests/test_intent_archive.py",
            side_effects="无外部业务写入。",
            idempotency="同一输入可能生成不同理由；重试前应确认业务是否接受。",
            request_example={
                "user_id": "example-user",
                "session_id": "example-session",
                "history": [],
                "text": "把这份文件归档",
            },
            responses={
                "200": _json_response(
                    "四字段归档意图结果。",
                    ref("ArchiveIntentResult"),
                    example={
                        "intent": "A",
                        "confidence": 0.95,
                        "reason": "用户要求归档当前文件。",
                        "needs_clarification": False,
                    },
                ),
                "422": REQUEST_ERROR_RESPONSE,
                "502": _error_response(
                    "上游模型错误、输出不合法，或返回 A–D、unknown 之外的标签。"
                ),
                "503": _error_response("模型服务不可达。"),
                "504": _error_response("模型推理超时。"),
            },
        )
    },
    "/agents/chat": {
        "post": _operation(
            description="自由对话；调用方传入当前用户当前会话的完整历史，服务不保存服务端会话。"
            "返回完整回答，不使用流式响应。",
            status="confirmed",
            source="AGENTS.md 第四节；docs/agents-api.md；docs/sessions.md；tests/test_agents.py",
            side_effects="无外部业务写入。",
            idempotency="同一输入可能生成不同回答；重试前应确认业务是否接受。",
            request_example={
                "user_id": "example-user",
                "session_id": "example-session",
                "history": [],
                "message": "你好，帮我解释一下什么是业务智能体。",
            },
            responses={
                "200": _json_response(
                    "回答与模型名称。",
                    ref("ChatResponse"),
                    example={
                        "reply": "业务智能体是能够理解业务需求，并结合规则或工具处理任务的程序……",
                        "model": "qwen3.5:9b-q4_K_M",
                    },
                ),
                "422": REQUEST_ERROR_RESPONSE,
                "502": _error_response("上游模型错误、输出为空或未通过响应检查。"),
                "503": _error_response("模型服务不可达。"),
                "504": _error_response("模型推理超时。"),
            },
        )
    },
    "/health/deps": {
        "get": _operation(
            description="检查 OCR、PDF、Excel、图像库能否导入，并报告 OpenCV 特征与 ONNX 推理设备。"
            "只证明依赖可导入，不代表模板齐全或识别准确。",
            summary="检查文档处理依赖",
            status="pending-review",
            source="AGENTS.md 第四节；docs/ocr.md；app/ocr/deps.py；tests/test_ocr.py",
            side_effects="无；只做进程内导入检查。",
            idempotency="只读，可安全重试。",
            responses={
                "200": _json_response(
                    "依赖检查结果。",
                    ref("HealthDepsResponse"),
                    example={
                        "status": 200,
                        "data": {
                            "ok": True,
                            "caps": {
                                "PDF(渲染 / 文字层 / 写字 / 拆页)": {
                                    "ok": True,
                                    "deps": [{"name": "PyMuPDF", "ok": True, "version": "1.26.0"}],
                                },
                                "推理设备": {"ok": True, "providers": ["CPUExecutionProvider"]},
                            },
                        },
                    },
                )
            },
        )
    },
    "/ocr/recognize": {
        "post": _operation(
            description="识别普通照片或已知表号照片。path 与 img 至少提供一个，同时提供时优先 img；"
            "未指定 form 时只按栏目文字取值。返回识别草稿，200 不代表字段全部准确。",
            summary="识别普通照片或简表照片",
            status="pending-review",
            source="AGENTS.md 第四节；docs/ocr.md；docs/ocr.md#http-接口；"
            "app/api/ocr.py；tests/test_ocr_recognize.py",
            side_effects="只读取数据池照片，不写文件。",
            idempotency="识别结果可能因模型、照片和模板变化而不同；只读调用可重试。",
            request_example={
                "path": "projects/现场照片.jpg",
                "form": "JB12-4.2.2",
            },
            responses={
                "200": _json_response(
                    "识别草稿。",
                    ref("RecognizeResponse"),
                    example={
                        "status": 200,
                        "data": {
                            "form": "JB12-4.2.2",
                            "formName": "土方路基抽检记录表",
                            "layout": True,
                            "fields": {"fld_supervisor": "四川公路工程咨询监理有限公司"},
                            "keys": {},
                            "detail": [
                                {
                                    "field": "fld_supervisor",
                                    "value": "四川公路工程咨询监理有限公司",
                                    "how": "rect",
                                    "conf": 0.98,
                                    "boxes": [[10, 10, 300, 40]],
                                }
                            ],
                            "warning": "",
                            "align": {
                                "ax": 800,
                                "bx": 0,
                                "ay": 600,
                                "by": 0,
                                "anchors": 4,
                                "how": "anchors",
                            },
                            "image": {"width": 600, "height": 400},
                            "lines": [
                                {
                                    "s": "监理单位：测试公司",
                                    "box": [10, 10, 300, 40],
                                    "conf": 0.99,
                                }
                            ],
                            "ms": 123,
                        },
                    },
                ),
                "400": _error_response(
                    "路径越界、文件不存在/不是文件、图片无法解码或文档处理失败。"
                ),
                "422": REQUEST_ERROR_RESPONSE,
                "503": _error_response("模板资源或 OCR 模型不可用。"),
            },
        )
    },
    "/ocr/daily-logs": {
        "post": _operation(
            description="识别 JLB13 监理日志照片，固定栏目输出 recognized 和 detail。"
            "path 与 img 至少提供一个，同时提供时优先 img。processed 当前固定为 {}。",
            summary="识别 JLB13 监理日志",
            status="pending-review",
            source="AGENTS.md 第四节；docs/ocr.md；app/ocr/daily_logs.py；"
            "tests/test_ocr_daily_logs.py",
            side_effects="只读取数据池照片，不写 PDF/Excel。",
            idempotency="识别结果可能因模型和照片变化而不同；只读调用可重试。",
            request_example={"path": "projects/监理日志照片.jpg"},
            responses={
                "200": _json_response(
                    "监理日志识别草稿。",
                    ref("DailyLogsResponse"),
                    example={
                        "status": 200,
                        "data": {
                            "form": "JLB13",
                            "formName": "监理日志",
                            "frame": {
                                "how": "contour",
                                "quad": [[0, 0], [599, 0], [599, 848], [0, 848]],
                            },
                            "recognized": {
                                "project": "测试高速公路项目",
                                "date": "2026-10-03",
                                "weather": "晴",
                                "issues": "无",
                            },
                            "detail": [],
                            "processed": {},
                            "warning": "",
                            "image": {"width": 600, "height": 849},
                            "ms": 123,
                        },
                    },
                ),
                "400": _error_response(
                    "路径越界、文件不存在/不是文件、图片无法解码或文档处理失败。"
                ),
                "422": REQUEST_ERROR_RESPONSE,
                "503": _error_response("OCR 模型不可用。"),
            },
        )
    },
    "/ocr/jianbiao": {
        "post": _operation(
            description="现场简表照片：轮廓定位、逐格识别，再按 cfg 公式/引用计算目标表并回填。"
            "out 为空只计算，不写 PDF/Excel/校正图。",
            summary="识别简表并回填目标表",
            status="pending-review",
            source="AGENTS.md 第四节；docs/ocr.md；app/ocr/jianbiao.py；tests/test_ocr.py",
            side_effects="out 非空时在 PROJECTS_ROOT 内写同名 .pdf、.xlsx 和 .warp.jpg。",
            idempotency="相同 out 重试会覆盖输出文件；调用前应确认是否允许覆盖。",
            request_example={
                "path": "projects/简表照片.jpg",
                "form": "JB12-4.2.2",
                "cfg": {},
                "bound": {},
                "out": "",
            },
            responses={
                "200": _json_response(
                    "识别、计算与输出路径。",
                    ref("JianbiaoResponse"),
                    example={
                        "status": 200,
                        "data": {
                            "jianbiao": "SIMPLE",
                            "jianbiaoName": "测试简表",
                            "frame": {
                                "how": "contour",
                                "quad": [[0, 0], [599, 0], [599, 848], [0, 848]],
                            },
                            "recognized": {"fld_1": "96.5"},
                            "detail": [],
                            "target": "JB12-4.2.2",
                            "targetName": "土方路基抽检记录表",
                            "values": {"fld_1": "96.5"},
                            "errors": {},
                            "anchors": [],
                            "pdf": "",
                            "xlsx": "",
                            "xlsxSkipped": [],
                            "ms": 123,
                        },
                    },
                ),
                "400": _error_response(
                    "路径越界、文件不存在、简表版面缺失、图片处理失败或公式循环引用。"
                ),
                "422": REQUEST_ERROR_RESPONSE,
                "503": _error_response("模板资源或 OCR 模型不可用。"),
            },
        )
    },
    "/ocr/fill": {
        "post": _operation(
            description="不识别照片，按配置公式/引用计算 values 并回填目标表；"
            "out 为空只计算，不写文件。计算公式字段以公式结果为准，传入的旧值不算数。",
            summary="按公式/引用计算并回填目标表",
            status="pending-review",
            source="AGENTS.md 第四节；docs/ocr.md；app/ocr/jianbiao.py；tests/test_ocr.py",
            side_effects="out 非空时在 PROJECTS_ROOT 内写同名 .pdf、.xlsx。",
            idempotency="相同 out 重试会覆盖输出文件；调用前应确认是否允许覆盖。",
            request_example={
                "form": "JB12-4.2.2",
                "cfg": {"formulas": [{"target": "rate", "expr": "PASS_RATE(94, @{v1}, @{v2})"}]},
                "values": {"v1": "96.1", "v2": "93.2"},
                "out": "",
            },
            responses={
                "200": _json_response(
                    "计算值、错误、锚点与输出路径。",
                    ref("FillResponse"),
                    example={
                        "status": 200,
                        "data": {
                            "target": "JB12-4.2.2",
                            "targetName": "土方路基抽检记录表",
                            "values": {"fld_rate": "50"},
                            "errors": {},
                            "anchors": [],
                            "pdf": "",
                            "xlsx": "",
                            "xlsxSkipped": [],
                        },
                    },
                ),
                "400": _error_response("路径越界、输出不是 PDF、公式循环引用或文档处理失败。"),
                "422": REQUEST_ERROR_RESPONSE,
                "503": _error_response("模板资源不可用。"),
            },
        )
    },
    "/ocr/blank/{form}.png": {
        "get": _operation(
            description="渲染模板表样第 1 页为 PNG；width 为期望像素宽度，实际按不超过 2400 渲染。"
            "响应是原始 image/png，不是 {status, data} 包装。",
            summary="渲染空白表样 PNG",
            status="pending-review",
            source="AGENTS.md 第四节；docs/ocr.md；app/api/ocr.py；tests/test_ocr.py",
            side_effects="无；只读取模板资源。",
            idempotency="只读，可安全重试。",
            responses={
                "200": {
                    "description": "表样第 1 页 PNG。",
                    "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
                },
                "400": _error_response("模板资源路径越界、PDF 不存在或文档渲染失败。"),
                "404": _error_response("模板库没有该表号的表样 PDF。"),
                "422": REQUEST_ERROR_RESPONSE,
                "503": _error_response("模板资源不可用。"),
            },
        )
    },
    "/ocr/sheet/{form}": {
        "get": _operation(
            description="返回表样上可填的版面栏（fld_*）和其余空格子（g*），供业务端定位与回填。",
            summary="查询表样栏目与格子",
            status="pending-review",
            source="AGENTS.md 第四节；docs/ocr.md；app/ocr/grid.py；tests/test_ocr.py",
            side_effects="无；只读取模板资源。",
            idempotency="只读，可安全重试。",
            responses={
                "200": _json_response(
                    "栏目与格子列表。",
                    ref("SheetResponse"),
                    example={
                        "status": 200,
                        "data": [
                            {
                                "field": "fld_supervisor",
                                "name": "监理单位",
                                "rect": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1},
                                "behavior": "INPUT",
                                "kind": "layout",
                            }
                        ],
                    },
                ),
                "400": _error_response("模板资源路径越界或表样读取失败。"),
                "404": _error_response("模板库没有该表号的表样 PDF。"),
                "503": _error_response("模板资源不可用。"),
            },
        )
    },
    "/wbs/draft": {
        "post": _operation(
            description="读取施工图 PDF（或 _N.pdf 单页拆分目录）和可选工可依据，生成单位/分部/分项划分初稿。"
            "不执行人工确认、审批或落库；当前不生成隧道划分。",
            summary="生成施工图 WBS 划分初稿",
            status="pending-review",
            source="AGENTS.md 第四节；docs/ocr.md；app/ocr/wbs_draft.py；tests/test_ocr.py",
            side_effects="只读取数据池文件，不写文件。",
            idempotency="同一输入结果稳定；只读调用可重试。",
            request_example={
                "prefix": "S210",
                "drawings": ["projects/drawings/plan.pdf"],
                "basis": {"facts": [["路线起讫", "K0+000~K4+000"]]},
            },
            responses={
                "200": _json_response(
                    "划分初稿与识别依据。",
                    ref("WbsDraftResponse"),
                    example={
                        "status": 200,
                        "data": {
                            "units": [
                                {
                                    "code": "S210-LJ01",
                                    "title": "K0+000-K4+000路基工程",
                                    "children": [],
                                }
                            ],
                            "count": {"units": 1, "parts": 0, "items": 0, "subs": 0},
                            "drawings": [],
                        },
                    },
                ),
                "400": _error_response("路径越界、施工图不是 PDF 或文档处理失败。"),
                "422": REQUEST_ERROR_RESPONSE,
                "503": _error_response("WBS 规则模板或 PDF 处理资源不可用。"),
            },
        )
    },
}


def _apply_operations(spec: dict[str, Any]) -> None:
    for path, methods in OPERATIONS.items():
        for method, meta in methods.items():
            if meta is None:
                continue
            operation = spec["paths"][path][method]
            operation.update(copy.deepcopy(meta["operation"]))
            operation["responses"].update(copy.deepcopy(meta["responses"]))
            if meta.get("request_example") is not None:
                media = operation.setdefault("requestBody", {}).setdefault("content", {})
                media.setdefault(JSON_MEDIA_TYPE, {})["example"] = copy.deepcopy(
                    meta["request_example"]
                )
            if "422" in operation["responses"]:
                operation["responses"]["422"] = copy.deepcopy(REQUEST_ERROR_RESPONSE)


COMPONENT_PROPERTY_DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("ChatMessage", "role"): "消息角色，只允许 user 或 assistant。",
    ("ChatMessage", "content"): "消息正文，去除首尾空白后不能为空。",
    ("ChatResponse", "reply"): "完整聊天回答，不使用流式响应。",
    ("ChatResponse", "model"): "本次调用实际使用的模型名称。",
    ("RecognizeReq", "path"): "PROJECTS_ROOT 数据池内的照片路径；与 img 至少提供一个。",
    ("RecognizeReq", "form"): "表号；省略或空字符串时只按栏目文字取值。",
    ("DailyLogsReq", "path"): "PROJECTS_ROOT 数据池内的监理日志照片路径；与 img 至少提供一个。",
    ("JianbiaoReq", "path"): "PROJECTS_ROOT 数据池内的简表照片路径。",
    ("JianbiaoReq", "form"): "目标表号，同时用于查找简表版面。",
    ("JianbiaoReq", "cfg"): "配置平台的字段、锚点、引用和公式元数据。",
    ("JianbiaoReq", "bound"): "项目资料带入值；照片识别值优先。",
    ("JianbiaoReq", "out"): "输出 PDF 相对路径；为空不写 PDF/Excel/校正图。",
    ("FillReq", "form"): "目标表号。",
    ("FillReq", "cfg"): "配置平台的字段、锚点、引用和公式元数据。",
    ("FillReq", "values"): "待计算和回填的字段值；公式目标字段以计算结果为准。",
    ("FillReq", "out"): "输出 PDF 相对路径；为空只计算，不写文件。",
    ("FillReq", "rects"): "本张表调整后的字段坐标 {x,y,w,h}。",
    ("DraftReq", "prefix"): "合同段编码前缀，例如 S210。",
    ("DraftReq", "drawings"): "施工图 PDF 或 _N.pdf 单页拆分目录的数据池相对路径。",
    ("DraftReq", "basis"): "工可依据，可包含 facts 键值对数组或对象。",
    ("RecognizeData", "detail"): "每个字段的取值方式、置信度和来源文字框。",
    ("RecognizeData", "lines"): "原始 OCR 文字框。",
    ("DailyLogsData", "detail"): "每个固定栏目的识别值、置信度和区域。",
    ("JianbiaoData", "detail"): "简表每个格子的识别值、置信度和区域。",
    ("SheetCell", "behavior"): "填写行为，例如 INPUT。",
}


def _apply_component_descriptions(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    for (schema_name, property_name), description in COMPONENT_PROPERTY_DESCRIPTIONS.items():
        properties = schemas.get(schema_name, {}).get("properties", {})
        if property_name in properties:
            properties[property_name].setdefault("description", description)


def _apply_parameters(spec: dict[str, Any]) -> None:
    parameters = spec["paths"]["/ocr/blank/{form}.png"]["get"].get("parameters", [])
    for parameter in parameters:
        if parameter["name"] == "form":
            parameter["description"] = "模板表号。"
        elif parameter["name"] == "width":
            parameter["description"] = "期望渲染宽度（像素），最小 1；超过 2400 时按 2400 渲染。"
    parameters = spec["paths"]["/ocr/sheet/{form}"]["get"].get("parameters", [])
    for parameter in parameters:
        if parameter["name"] == "form":
            parameter["description"] = "模板表号。"


def build_contract() -> dict[str, Any]:
    """返回当前应用对应的完整 OpenAPI 草案；每次调用重新生成，不使用缓存。"""
    spec = copy.deepcopy(create_app().openapi())
    spec["info"]["description"] = (
        "公路工程业务智能体与文档加工服务的对外 HTTP 契约。当前文件是从实现归纳的"
        "待确认草案：已实现接口的请求和成功响应来自 FastAPI/Pydantic，OCR、WBS 的"
        "响应体及统一错误响应由 scripts/docs/openapi_contract.py 补充。"
        "经用户批准前不得视为正式契约，也不得据此绕过接口变更审批。"
    )
    spec["info"]["x-contract-status"] = "draft-pending-review"
    spec["info"]["x-contract-version"] = "0.1.0-review.1"
    spec["info"]["x-review-status"] = "first-version-submitted"
    spec["info"]["x-contract-authority"] = (
        "interfaces/openapi/ 中的正式契约（批准后）优先于本草案和运行时自动生成结果。"
    )
    spec["servers"] = [
        {"url": "http://127.0.0.1:8309", "description": "本机开发默认地址"},
    ]
    spec["tags"] = [
        {"name": "智能体", "description": "日志总结、意图识别与自由对话；同步模型调用。"},
        {"name": "ocr", "description": "照片、监理日志、简表、填表与表样；CPU 处理同步执行。"},
        {"name": "wbs", "description": "施工图划分初稿；不执行审批或落库。"},
    ]
    spec.setdefault("components", {}).setdefault("schemas", {}).update(copy.deepcopy(SCHEMAS))
    # 业务意图使用自包含的 $defs；与已发布 JSON Schema 保持逐字一致。
    spec["components"]["schemas"]["BusinessIntentResult"] = BusinessIntentResult.model_json_schema()
    _apply_component_descriptions(spec)
    _apply_parameters(spec)
    _apply_operations(spec)
    return spec


def contract_json() -> str:
    """稳定的 JSON 文本；用于导出和校验。"""
    return json.dumps(build_contract(), ensure_ascii=False, indent=2, sort_keys=False) + "\n"
