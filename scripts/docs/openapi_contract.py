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
JOURNAL_CONTRACT_PATH = ROOT / "interfaces/openapi/journal.openapi.json"

JSON_MEDIA_TYPE = "application/json"

VALIDATION_ERROR_ITEM = "ValidationErrorItem"
REQUEST_ERROR = "RequestError"
ERROR_DETAIL = "ErrorDetail"
# 这些既有入口未声明成功 response_model，需要文档补全；其他入口必须保留运行时 Schema。
SCHEMALESS_SUCCESS_PATHS = frozenset({"/health", "/ready", "/diagnostics", "/ocr/jianbiao"})


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
            "configured": {
                "type": "string",
                "enum": ["cpu", "cuda", "unknown"],
                "description": "当前 OCR_DEVICE；应用资源未初始化时为 unknown。",
            },
            "device": {"type": "string", "description": "onnxruntime 报告的实际设备。"},
            "runtime": {"type": "string", "description": "已安装的 ONNX Runtime 发行包及版本。"},
            "note": {"type": "string", "description": "该能力检查的边界说明。"},
            "templates": {"type": "object", "additionalProperties": True},
            "layouts": {"type": "object", "additionalProperties": True},
            "wbs_rules": {"type": "object", "additionalProperties": True},
            "models": {"type": "object", "additionalProperties": True},
            "projects": {"type": "object", "additionalProperties": True},
            "admin": {"type": "object", "additionalProperties": True},
            "assets": {"type": "object", "additionalProperties": True},
            "error": {"type": "string"},
        },
        "description": "按能力分组的检查结果；不同能力的字段不完全相同。",
    },
    "DiagnosticsData": {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok", "warnings", "caps"],
        "properties": {
            "ok": {
                "type": "boolean",
                "description": "全部检查是否通过；warnings 不影响 ok。",
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "非致命问题，例如模型目录为空但可写、表样目录缺失。",
            },
            "caps": {
                "type": "object",
                "additionalProperties": ref("CapabilityStatus"),
                "description": "能力名 → 检查结果。能力名包括 PDF、Excel、图像、文字识别、"
                "模型推理、OpenCV 特征、推理设备和 OCR 资源。",
            },
        },
    },
    "DiagnosticsResponse": _envelope_schema("DiagnosticsData", "本地依赖与资源诊断成功响应。"),
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
    "/diagnostics": {
        "get": _operation(
            description="检查本地运行库、ONNX Runtime 与 OCR_DEVICE 是否一致，以及 OCR 模板、"
            "版面、WBS 规则、模型目录和数据池是否可用。不初始化引擎、不访问网络、不写文件；"
            "data.ok 为 false 时仍返回 HTTP 200。",
            summary="检查本地依赖与资源",
            status="confirmed",
            source="AGENTS.md 第四节；docs/ocr.md；app/ocr/core/deps.py；tests/test_diagnostics.py",
            side_effects="无持久副作用；只做进程内导入、读取模板 JSON 和目录状态。",
            idempotency="只读，可安全重试。",
            responses={
                "200": _json_response(
                    "诊断结果；data.ok 汇总必需检查，warnings 不影响 HTTP 状态。",
                    ref("DiagnosticsResponse"),
                    example={
                        "status": 200,
                        "data": {
                            "ok": True,
                            "warnings": [],
                            "caps": {
                                "推理设备": {
                                    "ok": True,
                                    "configured": "cpu",
                                    "device": "CPU",
                                    "providers": ["CPUExecutionProvider"],
                                },
                                "OCR 资源": {
                                    "ok": True,
                                    "templates": {"ok": True, "forms": 42},
                                    "projects": {"ok": True},
                                },
                            },
                        },
                    },
                )
            },
        )
    },
    "/ocr/jianbiao": {
        "post": _operation(
            description="简表照片识别：先核验表格结构，再做直角方向选择和透视校正，"
            "单次整页 OCR 后把文字框归属到字段；只支持经模板核验的 0°/90°/180°/270°，"
            "检测失败不会退回整图 OCR，空字段、歧义字段和非法数字一律输出 null。"
            "out 非空时在数据池内写出 response.json、diagnostics.json 和 aligned.png。",
            summary="识别简表照片（模板核验＋整页 OCR）",
            status="pending-review",
            source="app/ocr/jianbiao/README.md；tests/test_ocr_jianbiao.py；"
            "tests/fixtures/jianbiao-response.example.json；tests/http-test/demo.http",
            side_effects="out 非空时只在数据池内写出识别结果与诊断文件；不调用语言模型。",
            idempotency="识别结果可能因照片和模型变化而不同；out 写出可安全重复，同名文件被覆盖。",
            request_example={
                "img": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD...",
                "form": "subgrade_spot_check",
                "cfg": {},
                "bound": {},
                "out": "",
                "taskId": "123456789012345678",
            },
            responses={
                "200": _json_response(
                    "固定公共字段和全部 10 行记录；空值、歧义值和无法完整解析的合格率为 null。",
                    ref("JianbiaoResponse"),
                    example={
                        "status": 200,
                        "message": "识别完成",
                        "data": {
                            "taskId": "123456789012345678",
                            "documentType": "subgrade_spot_check",
                            "common": {
                                "projectName": "成乐高速公路扩容建设项目",
                                "documentNo": "JB12-4.5.2-4",
                                "inspectorName": "王璐瑶",
                                "inspectDate": "2026-11-11",
                                "position": "防裂工程土工合成材料处治层（土工格栅）",
                            },
                            "fields": {
                                "records": [
                                    {
                                        "rowIndex": 1,
                                        "checkItem": "压实度",
                                        "standardValue": "≥96%",
                                        "measuredValue": "96.2、96.5、96.8",
                                        "passRate": 100.0,
                                    },
                                    *[
                                        {
                                            "rowIndex": row,
                                            "checkItem": None,
                                            "standardValue": None,
                                            "measuredValue": None,
                                            "passRate": None,
                                        }
                                        for row in range(2, 11)
                                    ],
                                ]
                            },
                        },
                    },
                ),
                "400": _error_response(
                    "路径越界、文件不存在/不是文件、图片无法解码、模板未配置，或未检测到通过"
                    "模板结构核验的简表表格。"
                ),
                "422": REQUEST_ERROR_RESPONSE,
                "503": _error_response("OCR 模型不可用。"),
            },
        )
    },
}

# 三个操作的说明和示例以已批准契约为准；Schema 始终取实际应用，避免隐藏实现漂移。
for _path, _methods in json.loads(JOURNAL_CONTRACT_PATH.read_text(encoding="utf-8"))[
    "paths"
].items():
    for _method, _approved in _methods.items():
        _metadata = {
            key: copy.deepcopy(item)
            for key, item in _approved.items()
            if key not in {"operationId", "requestBody", "responses", "tags"}
        }
        OPERATIONS[_path] = {
            _method: {
                "operation": _metadata,
                "responses": copy.deepcopy(_approved["responses"]),
                "request_example": copy.deepcopy(
                    _approved.get("requestBody", {})
                    .get("content", {})
                    .get(JSON_MEDIA_TYPE, {})
                    .get("example")
                ),
            }
        }


def _apply_operations(spec: dict[str, Any]) -> None:
    for path, methods in OPERATIONS.items():
        for method, meta in methods.items():
            if meta is None:
                continue
            operation = spec["paths"][path][method]
            operation.update(copy.deepcopy(meta["operation"]))
            for code, response in copy.deepcopy(meta["responses"]).items():
                # 文档增强只能补充成功响应说明，不能覆盖路由实际声明的非空 Schema。
                # 否则 response_model 漂移会被手写 $ref 掩盖，正式子契约检查将误报通过。
                actual_schema = (
                    operation["responses"]
                    .get(code, {})
                    .get("content", {})
                    .get(JSON_MEDIA_TYPE, {})
                    .get("schema")
                )
                if code == "200" and (actual_schema or path not in SCHEMALESS_SUCCESS_PATHS):
                    response["content"][JSON_MEDIA_TYPE]["schema"] = actual_schema or {}
                operation["responses"][code] = response
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


def _schema_refs(node: Any) -> set[str]:
    """递归收集 $ref 指向的 components.schemas 名称。"""
    names: set[str] = set()
    pending = [node]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            reference = item.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
                names.add(reference.rsplit("/", 1)[-1])
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return names


def _prune_unused_schemas(spec: dict[str, Any]) -> None:
    """删除没有任何路径或组件引用的模型，避免契约保留已移除接口的 Schema。"""
    schemas = spec["components"]["schemas"]
    reachable: set[str] = set()
    pending = [spec["paths"]]
    while pending:
        for name in _schema_refs(pending.pop()):
            if name not in reachable:
                reachable.add(name)
                pending.append(schemas.get(name, {}))
    for name in list(schemas):
        if name not in reachable:
            del schemas[name]


def _raise_defs_to_components(node: Any) -> None:
    """把 TypeAdapter 的 #/$defs/X 引用改写为 #/components/schemas/X。"""
    if isinstance(node, dict):
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            node["$ref"] = f"#/components/schemas/{reference.rsplit('/', 1)[-1]}"
        for value in node.values():
            _raise_defs_to_components(value)
    elif isinstance(node, list):
        for item in node:
            _raise_defs_to_components(item)


def build_contract(*, official: bool = False) -> dict[str, Any]:
    """从实现生成比较投影；正式模式使用已批准元信息，不读取或改写正式文件。"""
    spec = copy.deepcopy(create_app().openapi())
    spec["info"]["description"] = (
        "公路工程智能算法服务的对外 HTTP 契约。当前文件是从实现归纳的"
        "待确认草案：已实现接口的请求和成功响应来自 FastAPI/Pydantic，补充的响应结构"
        "及统一错误响应由 scripts/docs/openapi_contract.py 维护。"
        "经用户批准前不得视为正式契约，也不得据此绕过接口变更审批。"
    )
    spec["info"]["x-contract-status"] = "draft-pending-review"
    spec["info"]["x-contract-version"] = "0.1.0-review.3"
    spec["info"]["x-review-status"] = "revised-pending-review"
    spec["info"]["x-contract-authority"] = (
        "interfaces/openapi/ 中的正式契约（批准后）优先于本草案和运行时自动生成结果。"
    )
    if official:
        # 仅固定本次已批准的元信息；路径、字段与约束继续由实际应用生成以检测漂移。
        spec["info"].update(
            {
                "description": "公路工程智能算法服务的对外 HTTP 契约。用户于 2026-11-12 批准当前 10 个操作的完整基线，包括诊断接口、现有响应包装和统一错误语义。接口变更仍须用户明确批准；运行时自动生成结果不得覆盖正式契约。",
                "x-contract-status": "confirmed",
                "x-contract-version": "0.1.0",
                "x-review-status": "approved",
                "x-contract-authority": "interfaces/openapi/ 中用户已批准的正式契约优先于草案和运行时自动生成结果。",
            }
        )
    spec["servers"] = [
        {"url": "http://127.0.0.1:8309", "description": "本机开发默认地址"},
    ]
    spec["tags"] = [
        {"name": "智能体", "description": "日志总结、意图识别与自由对话；同步模型调用。"},
        {"name": "ocr", "description": "新版监理日志与简表照片识别；CPU 处理同步执行。"},
    ]
    spec.setdefault("components", {}).setdefault("schemas", {}).update(copy.deepcopy(SCHEMAS))
    # 业务意图使用自包含的 $defs；与已发布 JSON Schema 保持逐字一致。
    spec["components"]["schemas"]["BusinessIntentResult"] = BusinessIntentResult.model_json_schema()
    # 简表成功响应的结构化 TypedDict 直接来自实现，草案随代码同步；
    # TypeAdapter 把嵌套 TypedDict 放进 $defs，需提升为 components 引用。
    from pydantic import TypeAdapter

    from app.ocr.jianbiao.output import JianbiaoResponse

    jianbiao_schema = TypeAdapter(JianbiaoResponse).json_schema()
    for name, subschema in jianbiao_schema.pop("$defs", {}).items():
        _raise_defs_to_components(subschema)
        spec["components"]["schemas"][name] = subschema
    _raise_defs_to_components(jianbiao_schema)
    spec["components"]["schemas"]["JianbiaoResponse"] = jianbiao_schema
    _apply_component_descriptions(spec)
    _apply_operations(spec)
    _prune_unused_schemas(spec)
    return spec


def contract_json() -> str:
    """稳定的 JSON 文本；用于导出和校验。"""
    return json.dumps(build_contract(), ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _validation_shape(schema: Any) -> Any:
    """忽略 Schema 展示注解，保留全部校验规则及业务属性名。"""
    if isinstance(schema, list):
        return [_validation_shape(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    annotations = {"title", "description", "examples", "example"}
    normalized = {}
    for key, item in schema.items():
        if key in annotations:
            continue
        if key in {"properties", "$defs", "patternProperties"}:
            normalized[key] = {name: _validation_shape(prop) for name, prop in item.items()}
        elif key == "required" and isinstance(item, list):
            normalized[key] = sorted(item)
        else:
            normalized[key] = _validation_shape(item)
    return normalized


def _resolve_schema_refs(
    node: Any, schemas: dict[str, Any], seen: frozenset[str] = frozenset()
) -> Any:
    """展开组件引用，使共享类型别名与内联 Schema 按相同校验规则比较。"""
    if isinstance(node, list):
        return [_resolve_schema_refs(item, schemas, seen) for item in node]
    if not isinstance(node, dict):
        return node
    reference = node.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
        name = reference.rsplit("/", 1)[-1]
        if name not in seen and name in schemas:
            expanded = {
                **schemas[name],
                **{key: item for key, item in node.items() if key != "$ref"},
            }
            return _resolve_schema_refs(expanded, schemas, seen | {name})
    return {key: _resolve_schema_refs(item, schemas, seen) for key, item in node.items()}


def _operation_shape(operation: dict[str, Any], schemas: dict[str, Any]) -> dict[str, Any]:
    """对正式子契约比较调用行为，文案由完整评审文档另行保护。"""
    return _validation_shape(
        _resolve_schema_refs(
            {
                "operationId": operation.get("operationId"),
                "parameters": _validation_shape(operation.get("parameters", [])),
                "requestBody": _validation_shape(operation.get("requestBody", {})),
                "responses": _validation_shape(operation.get("responses", {})),
                "security": operation.get("security", []),
            },
            schemas,
        )
    )


def approved_journal_differences(spec: dict[str, Any]) -> list[str]:
    """独立比较已批准的三个操作及可达 Schema，不从实现覆盖正式子契约。"""
    approved = json.loads(JOURNAL_CONTRACT_PATH.read_text(encoding="utf-8"))
    expected_schemas = approved["components"]["schemas"]
    actual_schemas = spec["components"]["schemas"]
    differences = []
    for path, methods in approved["paths"].items():
        for method, operation in methods.items():
            actual = spec["paths"].get(path, {}).get(method)
            if actual is None or _operation_shape(actual, actual_schemas) != _operation_shape(
                operation, expected_schemas
            ):
                differences.append(f"正式子契约操作不一致：{method.upper()} {path}")
    for name, schema in expected_schemas.items():
        actual = actual_schemas.get(name)
        expected_shape = _validation_shape(_resolve_schema_refs(schema, expected_schemas))
        actual_shape = _validation_shape(_resolve_schema_refs(actual, actual_schemas))
        if actual is None or actual_shape != expected_shape:
            differences.append(f"正式子契约 Schema 不一致：{name}")
    return differences
