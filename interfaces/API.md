# 公路工程业务智能体

> 本文件由 OpenAPI 契约自动生成，用于评审，不是独立契约，请勿手工编辑。
> 生成来源：`interfaces/drafts/fastapi.openapi.json`。
> 权威字段以 OpenAPI 为准；正式契约批准前，本文件中的 `pending-review` 操作不能作为实现授权。

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 标题 | 公路工程业务智能体 |
| OpenAPI 版本 | 3.1.0 |
| 接口版本 | `0.1.0` |
| 契约版本 | `0.1.0-review.3` |
| 契约状态 | `draft-pending-review` |
| 服务地址 | http://127.0.0.1:8309 |

公路工程业务智能体与文档加工服务的对外 HTTP 契约。当前文件是从实现归纳的待确认草案：已实现接口的请求和成功响应来自 FastAPI/Pydantic，补充的响应结构及统一错误响应由 scripts/docs/openapi_contract.py 维护。经用户批准前不得视为正式契约，也不得据此绕过接口变更审批。

## 通用错误响应

`400`、`404`、`502`、`503`、`504` 使用 `ErrorDetail`；`422` 使用 `RequestError`。各接口只列状态码和含义，字段结构见下表，不重复展开。

**`ErrorDetail`**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `detail` | string | 是 |  |  | 脱敏后的错误说明，不包含密钥、原始输入、身份、历史或上游错误正文。 |

**`RequestError`**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `detail` | string 或 array<`ValidationErrorItem`> | 是 |  |  | 请求校验失败时为错误数组；输入或上下文超限时为字符串。 |

## 接口索引

| # | 方法与路径 | 摘要 | 状态 |
| --- | --- | --- | --- |
| 1 | `GET /health` | 检查进程存活 | `confirmed` |
| 2 | `GET /ready` | 检查模型就绪 | `confirmed` |
| 3 | `GET /diagnostics` | 检查本地依赖与资源 | `pending-review` |
| 4 | `POST /agents/log-summary` | 总结并生成工作日志 | `confirmed` |
| 5 | `POST /agents/intent/business` | 识别业务页面与最小功能意图 | `confirmed` |
| 6 | `POST /agents/intent/archive` | 识别文件归档系统意图 | `confirmed` |
| 7 | `POST /agents/chat` | 自由对话 | `confirmed` |
| 8 | `POST /ocr/jianbiao` | 识别简表照片（模板核验＋整页 OCR） | `pending-review` |
| 9 | `POST /ocr/daily-logs-new` | 识别监理日记（新版链路） | `pending-review` |

## 接口详情

### 1. `GET /health`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 检查进程存活 |
| 契约状态 | `confirmed` |
| 来源 | AGENTS.md 第四节；README.md；tests/test_routing.py |
| 副作用 | 无 |
| 幂等/重试 | 只读，可安全重试。 |

只检查 API 进程是否存活，不访问模型、模板或数据池。

**响应**

- `200`：进程存活。

**200 响应体**

```json
{
  "status": "ok"
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `ok` | 是 |  |  | 进程存活标记。 |

Schema：`HealthResponse`

### 2. `GET /ready`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 检查模型就绪 |
| 契约状态 | `confirmed` |
| 来源 | AGENTS.md 第四节；docs/agents-api.md；tests/test_routing.py |
| 副作用 | 无；只发起模型列表请求。 |
| 幂等/重试 | 只读，可安全重试。 |

读取上游模型列表，检查配置的 LLM_MODEL 是否存在；不执行推理。

**响应**

- `200`：配置模型可用。
- `503`：模型服务不可达，或模型未安装、名称不匹配。

**200 响应体**

```json
{
  "status": "ready"
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `ready` | 是 |  |  | 配置模型已出现在上游模型列表。 |

Schema：`ReadyResponse`

### 3. `GET /diagnostics`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 检查本地依赖与资源 |
| 契约状态 | `pending-review` |
| 来源 | AGENTS.md 第四节；docs/ocr.md；app/ocr/core/deps.py；tests/test_diagnostics.py |
| 副作用 | 无持久副作用；只做进程内导入、读取模板 JSON 和目录状态。 |
| 幂等/重试 | 只读，可安全重试。 |

检查本地运行库、ONNX Runtime 与 OCR_DEVICE 是否一致，以及 OCR 模板、版面、WBS 规则、模型目录和数据池是否可用。不初始化引擎、不访问网络、不写文件；data.ok 为 false 时仍返回 HTTP 200。

**响应**

- `200`：诊断结果；data.ok 汇总必需检查，warnings 不影响 HTTP 状态。

**200 响应体**

```json
{
  "status": 200,
  "data": {
    "ok": true,
    "warnings": [],
    "caps": {
      "推理设备": {
        "ok": true,
        "configured": "cpu",
        "device": "CPU",
        "providers": [
          "CPUExecutionProvider"
        ]
      },
      "OCR 资源": {
        "ok": true,
        "templates": {
          "ok": true,
          "forms": 42
        },
        "projects": {
          "ok": true
        }
      }
    }
  }
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `DiagnosticsData` | 是 |  |  |  |

**`data` 字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ok` | boolean | 是 |  |  | 全部检查是否通过；warnings 不影响 ok。 |
| `warnings` | array<string> | 是 |  |  | 非致命问题，例如模型目录为空但可写、表样目录缺失。 |
| `caps` | object | 是 |  |  | 能力名 → 检查结果。能力名包括 PDF、Excel、图像、文字识别、模型推理、OpenCV 特征、推理设备和 OCR 资源。 |

Schema：`DiagnosticsResponse`

### 4. `POST /agents/log-summary`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 总结并生成工作日志 |
| 契约状态 | `confirmed` |
| 来源 | AGENTS.md 第四节；docs/agents-api.md；interfaces/log_summary/；tests/test_log_summary_interface.py |
| 副作用 | 无外部业务写入。 |
| 幂等/重试 | 同一输入可能生成不同措辞；重试前应确认业务是否接受。 |

接收工程表单 OCR 后的文字或 JSON 对象，生成可纳入当日日志的结构化结果。同步调用模型，不执行 OCR、不写数据库、不保存会话。

**请求体**

```json
{
  "user_id": "example-user",
  "session_id": "example-session",
  "content": {
    "项目名称": "示例高速公路项目",
    "fields": [
      {
        "key": "压实度(%)",
        "measured": [
          95.2,
          94.8,
          96.1
        ],
        "pass_rate": 100
      }
    ]
  }
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `content` | string 或 object | 是 |  |  | 工程表单 OCR 识别对象，内部字段和层级可变化；兼容通用日志文字或对象。非空，按 json.dumps(ensure_ascii=False) 序列化后最多4000字符；顶层不接受数组。 |

Schema：`LogSummaryRequest`

**响应**

- `200`：固定六字段成功响应。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `502`：上游模型错误、输出截断或未通过 Pydantic 校验。
- `503`：模型服务不可达。
- `504`：模型推理超时。

**200 响应体**

```json
{
  "title": "土方路基抽检记录",
  "date": null,
  "summary": "泸定至石棉高速公路工程项目TJ9施工标段、JL2监理标段K86+300至K86+660土方路基抽检表记录：压实度实测值为95.2%、94.8%、96.1%，记录合格率100%；弯沉实测值为0.1、0.2、0.3（单位0.01mm），宽度实测值为1000、1005、1010mm，后两项未记录合格率。",
  "completed_items": [],
  "pending_items": [],
  "issues": []
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `title` | string | 是 |  | minLength=1，maxLength=100 |  |
| `date` | string 或 null | 是 |  |  | 原样摘录输入date、日志日期或检测日期；检测日期优先于计划日期。例如检测日期2024年10月26日则输出2024年10月26日；只有计划日期时为null。 |
| `summary` | string | 是 |  | minLength=1，maxLength=1000 | 可纳入当日日志的客观中文段落，保留施工标段、部位、指标、全部原始实测值及单位；禁止换算，例如弯沉0.1、0.2、0.3（单位0.01mm）必须保持这三个数值；不推断合格结论。 |
| `completed_items` | array<string> | 是 |  | maxItems=8 | 仅输入明确写出已完成的事项；只有表格、测量数据或检测日期时必须为[]，不能添加完成检测或完成记录填写。 |
| `pending_items` | array<string> | 是 |  | maxItems=8 | 仅输入明确的待办或进行中事项；空值及未记录合格率不产生待办，无则[]。 |
| `issues` | array<string> | 是 |  | maxItems=8 | 输入原表明确的不合格结论、问题、风险或矛盾，必须保留；例如结论为宽度不合格则列出宽度不合格；未填合格率不属于质量问题，无则[]。 |

Schema：`LogSummary`

### 5. `POST /agents/intent/business`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 识别业务页面与最小功能意图 |
| 契约状态 | `confirmed` |
| 来源 | 用户确认的 intent-business 改造方案；interfaces/intent/；docs/agents-api.md；tests/test_intent_business.py |
| 副作用 | 无页面跳转；一级意图或一般交流可能额外调用一次模型。 |
| 幂等/重试 | 同一输入可能生成不同澄清文案、置信度和目录版本之外的文案；重试前应确认业务是否接受。 |

识别业务页面和能够完成任务的最小二级功能。目录来自业务功能 JSON，只识别到一级意图时调用 Chat 澄清；不执行页面跳转。

**请求体**

```json
{
  "user_id": "example-user",
  "session_id": "example-session",
  "message": "我要填写今天的监理日志。",
  "current_page": "workbench",
  "history": []
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `history` | array<`ChatMessage`> | 否 |  |  | 当前用户当前会话的完整历史，首轮为[]；可省略 |
| `message` | string | 是 |  | minLength=1，maxLength=2000 |  |
| `current_page` | enum（`supervision_diary`、`work_list`、`image_library`、`recognition_platform`、`business_management`、`workbench`） | 是 |  |  | 调用方当前实际页面编码 |
| `last_navigation` | `BusinessNavigationContext` 或 null | 否 |  |  |  |
| `pending_clarification` | `PendingClarification` 或 null | 否 |  |  |  |
| `request_id` | string 或 null | 否 |  |  | 调用方幂等标识；本服务不持久化，仅供调用方关联 |

Schema：`BusinessIntentRequest`

**响应**

- `200`：层级意图结果；clarify 的 message 为澄清文案，options 为目录内合法功能。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `502`：上游模型错误、输出不合法，或返回目录之外的页面/功能编码。
- `503`：模型服务不可达。
- `504`：分类、聊天或澄清推理超时。

**200 响应体**

```json
{
  "status": "resolved",
  "page": "supervision_diary",
  "action": "fill_supervision_log",
  "confidence": 0.95,
  "message": null,
  "options": null,
  "catalog_version": "b158b448e3cf4d0a"
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | enum（`resolved`、`clarify`、`chat`、`unknown`） | 是 |  |  |  |
| `page` | enum（`supervision_diary`、`work_list`、`image_library`、`recognition_platform`、`business_management`、`workbench`） 或 null | 是 |  |  |  |
| `action` | enum（`fill_supervision_log`、`fill_monthly_report`、`assign_monthly_report`、`view_supervision_log`、`fill_inspection_record`、`fill_standby_record`、`fill_environmental_log`、`fill_safety_log`、`approve_log`、`view_work_tasks`、`create_work_task`、`add_form`、`delete_supervision_form`、`view_approval_workflow`、`view_image_library`、`delete_image`、`create_album`、`delete_album`、`navigate_to_recognition`、`recognize_photo`、`add_personnel_configuration`、`delete_project_member`、`view_wbs`、`add_subproject`、`add_child_subproject`、`delete_subproject`、`delete_child_subproject`、`assign_wbs_personnel`、`navigate_to_work`、`view_today_tasks`、`view_pending_approvals`） 或 null | 是 |  |  |  |
| `confidence` | number | 是 |  | minimum=0，maximum=1 |  |
| `message` | string 或 null | 是 |  |  |  |
| `options` | array<`BusinessIntentOption`> 或 null | 是 |  |  |  |
| `catalog_version` | string | 是 |  | minLength=1，maxLength=64 |  |

Schema：`BusinessIntentResult`

### 6. `POST /agents/intent/archive`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 识别文件归档系统意图 |
| 契约状态 | `confirmed` |
| 来源 | AGENTS.md 第四节；docs/agents-api.md；interfaces/intent/archive/；tests/test_intent_archive.py |
| 副作用 | 无外部业务写入。 |
| 幂等/重试 | 同一输入可能生成不同理由；重试前应确认业务是否接受。 |

文件归档系统的意图识别；使用独立 profile，固定 A、B、C、D 占位分类加 unknown 兜底，没有 chat 分流。

**请求体**

```json
{
  "user_id": "example-user",
  "session_id": "example-session",
  "history": [],
  "text": "把这份文件归档"
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `history` | array<`ChatMessage`> | 是 |  |  | 当前用户当前会话的完整历史，首轮为[] |
| `text` | string | 是 |  | minLength=1，maxLength=2000 | 待识别的归档业务内容 |
| `intents` | array<`JsonValue`> | 否 |  | maxItems=0 | 仅为兼容保留，必须省略或为[]；不支持调用方自定义分类 |

Schema：`IntentRequest`

**响应**

- `200`：四字段归档意图结果。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `502`：上游模型错误、输出不合法，或返回 A–D、unknown 之外的标签。
- `503`：模型服务不可达。
- `504`：模型推理超时。

**200 响应体**

```json
{
  "intent": "A",
  "confidence": 0.95,
  "reason": "用户要求归档当前文件。",
  "needs_clarification": false
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `intent` | enum（`A`、`B`、`C`、`D`、`unknown`） | 是 |  |  |  |
| `confidence` | number | 是 |  | minimum=0.0，maximum=1.0 |  |
| `reason` | string | 是 |  | minLength=1，maxLength=300 |  |
| `needs_clarification` | boolean | 是 |  |  |  |

Schema：`ArchiveIntentResult`

### 7. `POST /agents/chat`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 自由对话 |
| 契约状态 | `confirmed` |
| 来源 | AGENTS.md 第四节；docs/agents-api.md；docs/sessions.md；tests/test_agents.py |
| 副作用 | 无外部业务写入。 |
| 幂等/重试 | 同一输入可能生成不同回答；重试前应确认业务是否接受。 |

自由对话；调用方传入当前用户当前会话的完整历史，服务不保存服务端会话。返回完整回答，不使用流式响应。

**请求体**

```json
{
  "user_id": "example-user",
  "session_id": "example-session",
  "history": [],
  "message": "你好，帮我解释一下什么是业务智能体。"
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `history` | array<`ChatMessage`> | 是 |  |  | 当前用户当前会话的完整历史，首轮为[] |
| `message` | string | 是 |  | minLength=1，maxLength=2000 |  |

Schema：`ChatRequest`

**响应**

- `200`：回答与模型名称。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `502`：上游模型错误、输出为空或未通过响应检查。
- `503`：模型服务不可达。
- `504`：模型推理超时。

**200 响应体**

```json
{
  "reply": "业务智能体是能够理解业务需求，并结合规则或工具处理任务的程序……",
  "model": "qwen3.5:9b-q4_K_M"
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `reply` | string | 是 |  | minLength=1 | 完整聊天回答，不使用流式响应。 |
| `model` | string | 是 |  |  | 本次调用实际使用的模型名称。 |

Schema：`ChatResponse`

### 8. `POST /ocr/jianbiao`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 识别简表照片（模板核验＋整页 OCR） |
| 契约状态 | `pending-review` |
| 来源 | app/ocr/jianbiao/README.md；tests/test_ocr_jianbiao.py；tests/fixtures/jianbiao-response.example.json；tests/http-test/demo.http |
| 副作用 | out 非空时只在数据池内写出识别结果与诊断文件；不调用语言模型。 |
| 幂等/重试 | 识别结果可能因照片和模型变化而不同；out 写出可安全重复，同名文件被覆盖。 |

简表照片识别：先核验表格结构，再做直角方向选择和透视校正，单次整页 OCR 后把文字框归属到字段；只支持经模板核验的 0°/90°/180°/270°，检测失败不会退回整图 OCR，空字段、歧义字段和非法数字一律输出 null。out 非空时在数据池内写出 response.json、diagnostics.json 和 aligned.png。

**请求体**

```json
{
  "img": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD...",
  "form": "subgrade_spot_check",
  "cfg": {},
  "bound": {},
  "out": "",
  "taskId": "123456789012345678"
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的简表照片路径 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |
| `form` | string | 是 |  | minLength=1，maxLength=128 | 简表模板 ID 或兼容别名，如 subgrade_spot_check（JB12-4.5.2-4） |
| `cfg` | object | 否 |  |  | 预留识别配置，当前版本不使用 |
| `bound` | object | 否 |  |  | 预留识别范围，当前版本不使用 |
| `out` | string | 否 | `""` |  | 数据池内输出目录；非空时写出 response.json、diagnostics.json 和 aligned.png，空则不写文件 |
| `taskId` | string | 否 | `""` | maxLength=128 | 业务任务 ID，仅原样回显到 data.taskId；不传则为 null |

Schema：`JianbiaoReq`

**响应**

- `200`：固定公共字段和全部 10 行记录；空值、歧义值和无法完整解析的合格率为 null。
- `400`：路径越界、文件不存在/不是文件、图片无法解码、模板未配置，或未检测到通过模板结构核验的简表表格。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `503`：OCR 模型不可用。

**200 响应体**

```json
{
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
      "position": "防裂工程土工合成材料处治层（土工格栅）"
    },
    "fields": {
      "records": [
        {
          "rowIndex": 1,
          "checkItem": "压实度",
          "standardValue": "≥96%",
          "measuredValue": "96.2、96.5、96.8",
          "passRate": 100.0
        },
        {
          "rowIndex": 2,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        },
        {
          "rowIndex": 3,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        },
        {
          "rowIndex": 4,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        },
        {
          "rowIndex": 5,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        },
        {
          "rowIndex": 6,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        },
        {
          "rowIndex": 7,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        },
        {
          "rowIndex": 8,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        },
        {
          "rowIndex": 9,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        },
        {
          "rowIndex": 10,
          "checkItem": null,
          "standardValue": null,
          "measuredValue": null,
          "passRate": null
        }
      ]
    }
  }
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | integer | 是 |  |  |  |
| `message` | string | 是 |  |  |  |
| `data` | `JianbiaoPayload` | 是 |  |  |  |

**`data` 字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `taskId` | string 或 null | 是 |  |  |  |
| `documentType` | string | 是 |  |  |  |
| `common` | `JianbiaoCommon` | 是 |  |  |  |
| `fields` | `JianbiaoFields` | 是 |  |  |  |

Schema：`JianbiaoResponse`

### 9. `POST /ocr/daily-logs-new`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 识别监理日记（新版链路） |
| 契约状态 | `pending-review` |
| 来源 | interfaces/journal/response.schema.json（成功响应已确认）；interfaces/journal/main-work-processing.md（生成语义已确认）；docs/journal-mainwork-split.md；tests/test_ocr_journal.py；tests/test_agents_main_work.py |
| 副作用 | 只读取数据池照片，不写 PDF/Excel。 |
| 幂等/重试 | 识别结果可能因模型和照片变化而不同；只读调用可重试。 |

新版监理日志识别：按 PDF 构建的模板对齐完整表格，整页一次 OCR 后匹配表内外字段；不进行字段级补充识别。mainWork先合并OCR文字，再按施工情况、旁站情况、巡视情况关键词提取；规则无法完整可靠覆盖时，由Agent基于全文生成construction、witness、patrol。允许整理表达、合并断句和去标题，但保留全部业务事实与关键数据，不摘要、不补充事实；原文没有的类别为 null。成功响应严格遵守已确认的后端格式，顶层只有 status、message、data，业务字段直接位于 data，不返回内部识别详情。mainWork 无法可靠拆分时返回 502。

**请求体**

```json
{
  "path": "projects/监理日志照片.jpg",
  "taskId": "123456789012345678"
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的监理日志照片路径 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |
| `taskId` | string | 否 | `""` | maxLength=128 | 业务任务 ID，仅原样回显到 processed.taskId；不传则为 null |

Schema：`JournalReq`

**响应**

- `200`：监理日志业务字段；成功响应结构已由用户确认，不含额外信息。
- `400`：路径越界、文件不存在/不是文件、图片无法解码、未检测到通过模板结构核验的监理日志表格，或文档处理失败。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `502`：mainWork无法可靠处理：关键词规则无法完整提取，且Agent不可用、超时或生成结果未通过结构/关键数据检查。
- `503`：OCR 模型不可用。

**200 响应体**

```json
{
  "status": 200,
  "message": "识别完成",
  "data": {
    "taskId": "123456789012345678",
    "documentType": "supervision_diary",
    "common": {
      "projectName": "测试高速公路项目",
      "documentNo": null,
      "supervisionOrg": null,
      "recorderName": null,
      "recorderPosition": "专业监理工程师",
      "weather": null,
      "logDate": "2026-10-03",
      "reviewerName": null
    },
    "fields": {
      "mainWork": {
        "construction": "K3+280段路基填筑",
        "witness": "旁站路基碾压",
        "patrol": "巡视挡土墙砌筑"
      },
      "issues": null,
      "nextDayPlan": null
    }
  }
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  |  |
| `message` | const `识别完成` | 是 |  |  |  |
| `data` | object | 是 |  |  |  |

**`data` 字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `taskId` | string / null | 是 |  |  |  |
| `documentType` | const `supervision_diary` | 是 |  |  |  |
| `common` | object | 是 |  |  |  |
| `fields` | object | 是 |  |  |  |

Schema：`JournalResponse`

## Schema 附录

以下是草案中引用的全部组件 Schema。

### `ArchiveIntentResult`

文件归档系统的意图识别结果；当前无聊天分流，理由始终简短。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `intent` | enum（`A`、`B`、`C`、`D`、`unknown`） | 是 |  |  |  |
| `confidence` | number | 是 |  | minimum=0.0，maximum=1.0 |  |
| `reason` | string | 是 |  | minLength=1，maxLength=300 |  |
| `needs_clarification` | boolean | 是 |  |  |  |

### `BusinessIntentRequest`

无状态业务意图请求；会话上下文由调用方传入。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `history` | array<`ChatMessage`> | 否 |  |  | 当前用户当前会话的完整历史，首轮为[]；可省略 |
| `message` | string | 是 |  | minLength=1，maxLength=2000 |  |
| `current_page` | enum（`supervision_diary`、`work_list`、`image_library`、`recognition_platform`、`business_management`、`workbench`） | 是 |  |  | 调用方当前实际页面编码 |
| `last_navigation` | `BusinessNavigationContext` 或 null | 否 |  |  |  |
| `pending_clarification` | `PendingClarification` 或 null | 否 |  |  |  |
| `request_id` | string 或 null | 否 |  |  | 调用方幂等标识；本服务不持久化，仅供调用方关联 |

### `BusinessIntentResult`

业务意图识别响应；status 区分跳转、澄清、聊天和未知。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | enum（`resolved`、`clarify`、`chat`、`unknown`） | 是 |  |  |  |
| `page` | enum（`supervision_diary`、`work_list`、`image_library`、`recognition_platform`、`business_management`、`workbench`） 或 null | 是 |  |  |  |
| `action` | enum（`fill_supervision_log`、`fill_monthly_report`、`assign_monthly_report`、`view_supervision_log`、`fill_inspection_record`、`fill_standby_record`、`fill_environmental_log`、`fill_safety_log`、`approve_log`、`view_work_tasks`、`create_work_task`、`add_form`、`delete_supervision_form`、`view_approval_workflow`、`view_image_library`、`delete_image`、`create_album`、`delete_album`、`navigate_to_recognition`、`recognize_photo`、`add_personnel_configuration`、`delete_project_member`、`view_wbs`、`add_subproject`、`add_child_subproject`、`delete_subproject`、`delete_child_subproject`、`assign_wbs_personnel`、`navigate_to_work`、`view_today_tasks`、`view_pending_approvals`） 或 null | 是 |  |  |  |
| `confidence` | number | 是 |  | minimum=0，maximum=1 |  |
| `message` | string 或 null | 是 |  |  |  |
| `options` | array<`BusinessIntentOption`> 或 null | 是 |  |  |  |
| `catalog_version` | string | 是 |  | minLength=1，maxLength=64 |  |

### `BusinessNavigationContext`

调用方最近一次返回过的导航目标；只作为纠错上下文。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | enum（`supervision_diary`、`work_list`、`image_library`、`recognition_platform`、`business_management`、`workbench`） | 是 |  |  |  |
| `action` | enum（`fill_supervision_log`、`fill_monthly_report`、`assign_monthly_report`、`view_supervision_log`、`fill_inspection_record`、`fill_standby_record`、`fill_environmental_log`、`fill_safety_log`、`approve_log`、`view_work_tasks`、`create_work_task`、`add_form`、`delete_supervision_form`、`view_approval_workflow`、`view_image_library`、`delete_image`、`create_album`、`delete_album`、`navigate_to_recognition`、`recognize_photo`、`add_personnel_configuration`、`delete_project_member`、`view_wbs`、`add_subproject`、`add_child_subproject`、`delete_subproject`、`delete_child_subproject`、`assign_wbs_personnel`、`navigate_to_work`、`view_today_tasks`、`view_pending_approvals`） 或 null | 否 |  |  |  |

### `ChatMessage`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `role` | enum（`user`、`assistant`） | 是 |  |  | 消息角色，只允许 user 或 assistant。 |
| `content` | string | 是 |  | minLength=1 | 消息正文，去除首尾空白后不能为空。 |

### `ChatRequest`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `history` | array<`ChatMessage`> | 是 |  |  | 当前用户当前会话的完整历史，首轮为[] |
| `message` | string | 是 |  | minLength=1，maxLength=2000 |  |

### `ChatResponse`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `reply` | string | 是 |  | minLength=1 | 完整聊天回答，不使用流式响应。 |
| `model` | string | 是 |  |  | 本次调用实际使用的模型名称。 |

### `IntentRequest`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `history` | array<`ChatMessage`> | 是 |  |  | 当前用户当前会话的完整历史，首轮为[] |
| `text` | string | 是 |  | minLength=1，maxLength=2000 | 待识别的归档业务内容 |
| `intents` | array<`JsonValue`> | 否 |  | maxItems=0 | 仅为兼容保留，必须省略或为[]；不支持调用方自定义分类 |

### `JianbiaoReq`

简表照片识别请求；form 取模板 ID 或兼容别名，out 非空时在数据池内写出结果文件。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的简表照片路径 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |
| `form` | string | 是 |  | minLength=1，maxLength=128 | 简表模板 ID 或兼容别名，如 subgrade_spot_check（JB12-4.5.2-4） |
| `cfg` | object | 否 |  |  | 预留识别配置，当前版本不使用 |
| `bound` | object | 否 |  |  | 预留识别范围，当前版本不使用 |
| `out` | string | 否 | `""` |  | 数据池内输出目录；非空时写出 response.json、diagnostics.json 和 aligned.png，空则不写文件 |
| `taskId` | string | 否 | `""` | maxLength=128 | 业务任务 ID，仅原样回显到 data.taskId；不传则为 null |

### `JournalReq`

新版监理日志识别请求；与旧接口字段一致，实现链独立。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的监理日志照片路径 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |
| `taskId` | string | 否 | `""` | maxLength=128 | 业务任务 ID，仅原样回显到 processed.taskId；不传则为 null |

### `JsonValue`

类型：any

### `LogSummary`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `title` | string | 是 |  | minLength=1，maxLength=100 |  |
| `date` | string 或 null | 是 |  |  | 原样摘录输入date、日志日期或检测日期；检测日期优先于计划日期。例如检测日期2024年10月26日则输出2024年10月26日；只有计划日期时为null。 |
| `summary` | string | 是 |  | minLength=1，maxLength=1000 | 可纳入当日日志的客观中文段落，保留施工标段、部位、指标、全部原始实测值及单位；禁止换算，例如弯沉0.1、0.2、0.3（单位0.01mm）必须保持这三个数值；不推断合格结论。 |
| `completed_items` | array<string> | 是 |  | maxItems=8 | 仅输入明确写出已完成的事项；只有表格、测量数据或检测日期时必须为[]，不能添加完成检测或完成记录填写。 |
| `pending_items` | array<string> | 是 |  | maxItems=8 | 仅输入明确的待办或进行中事项；空值及未记录合格率不产生待办，无则[]。 |
| `issues` | array<string> | 是 |  | maxItems=8 | 输入原表明确的不合格结论、问题、风险或矛盾，必须保留；例如结论为宽度不合格则列出宽度不合格；未填合格率不属于质量问题，无则[]。 |

### `LogSummaryRequest`

可变结构的工程表单 OCR JSON 或兼容文字，序列化后最多 4000 字符。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `content` | string 或 object | 是 |  |  | 工程表单 OCR 识别对象，内部字段和层级可变化；兼容通用日志文字或对象。非空，按 json.dumps(ensure_ascii=False) 序列化后最多4000字符；顶层不接受数组。 |

### `PendingClarification`

调用方保存的一级意图澄清状态；attempts 是已完成的澄清轮数。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | enum（`supervision_diary`、`work_list`、`image_library`、`recognition_platform`、`business_management`、`workbench`） | 是 |  |  |  |
| `attempts` | integer | 是 |  | minimum=0.0，maximum=10.0 |  |

### `ValidationErrorItem`

校验错误项。实际响应省略 input 与 ctx，避免回显原始身份、历史和输入。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `type` | string | 是 |  |  | Pydantic 错误类型。 |
| `loc` | array<string 或 integer> | 是 |  |  | 错误位置，例如 body、history、0、role。 |
| `msg` | string | 是 |  |  | 可公开的错误说明。 |

### `RequestError`

422 统一错误响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `detail` | string 或 array<`ValidationErrorItem`> | 是 |  |  | 请求校验失败时为错误数组；输入或上下文超限时为字符串。 |

### `ErrorDetail`

非校验类错误响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `detail` | string | 是 |  |  | 脱敏后的错误说明，不包含密钥、原始输入、身份、历史或上游错误正文。 |

### `HealthResponse`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `ok` | 是 |  |  | 进程存活标记。 |

### `ReadyResponse`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `ready` | 是 |  |  | 配置模型已出现在上游模型列表。 |

### `DependencyStatus`

单个依赖的导入检查结果。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `name` | string | 是 |  |  |  |
| `ok` | boolean | 是 |  |  |  |
| `version` | string | 否 |  |  |  |
| `error` | string | 否 |  |  |  |

### `CapabilityStatus`

按能力分组的检查结果；不同能力的字段不完全相同。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ok` | boolean | 是 |  |  |  |
| `deps` | array<`DependencyStatus`> | 否 |  |  |  |
| `SIFT` | boolean | 否 |  |  |  |
| `ORB` | boolean | 否 |  |  |  |
| `providers` | array<string> | 否 |  |  |  |
| `configured` | enum（`cpu`、`cuda`、`unknown`） | 否 |  |  | 当前 OCR_DEVICE；应用资源未初始化时为 unknown。 |
| `device` | string | 否 |  |  | onnxruntime 报告的实际设备。 |
| `runtime` | string | 否 |  |  | 已安装的 ONNX Runtime 发行包及版本。 |
| `note` | string | 否 |  |  | 该能力检查的边界说明。 |
| `templates` | object | 否 |  |  |  |
| `layouts` | object | 否 |  |  |  |
| `wbs_rules` | object | 否 |  |  |  |
| `models` | object | 否 |  |  |  |
| `projects` | object | 否 |  |  |  |
| `admin` | object | 否 |  |  |  |
| `assets` | object | 否 |  |  |  |
| `error` | string | 否 |  |  |  |

### `DiagnosticsData`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ok` | boolean | 是 |  |  | 全部检查是否通过；warnings 不影响 ok。 |
| `warnings` | array<string> | 是 |  |  | 非致命问题，例如模型目录为空但可写、表样目录缺失。 |
| `caps` | object | 是 |  |  | 能力名 → 检查结果。能力名包括 PDF、Excel、图像、文字识别、模型推理、OpenCV 特征、推理设备和 OCR 资源。 |

### `DiagnosticsResponse`

本地依赖与资源诊断成功响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `DiagnosticsData` | 是 |  |  |  |

### `JournalResponse`

用户于 2026-11-06 确认的 POST /ocr/daily-logs-new 成功响应；以 app/ocr/resources/daily-logs-output.json 为结构依据。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  |  |
| `message` | const `识别完成` | 是 |  |  |  |
| `data` | object | 是 |  |  |  |

### `JianbiaoCommon`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `projectName` | string 或 null | 是 |  |  |  |
| `documentNo` | string 或 null | 是 |  |  |  |
| `inspectorName` | string 或 null | 是 |  |  |  |
| `inspectDate` | string 或 null | 是 |  |  |  |
| `position` | string 或 null | 是 |  |  |  |

### `JianbiaoFields`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `records` | array<`SpotCheckRecord`> | 是 |  |  |  |

### `JianbiaoPayload`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `taskId` | string 或 null | 是 |  |  |  |
| `documentType` | string | 是 |  |  |  |
| `common` | `JianbiaoCommon` | 是 |  |  |  |
| `fields` | `JianbiaoFields` | 是 |  |  |  |

### `SpotCheckRecord`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `rowIndex` | integer | 是 |  |  |  |
| `checkItem` | string 或 null | 是 |  |  |  |
| `standardValue` | string 或 null | 是 |  |  |  |
| `measuredValue` | string 或 null | 是 |  |  |  |
| `passRate` | number 或 null | 是 |  |  |  |

### `JianbiaoResponse`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | integer | 是 |  |  |  |
| `message` | string | 是 |  |  |  |
| `data` | `JianbiaoPayload` | 是 |  |  |  |
