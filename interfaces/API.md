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
| 契约版本 | `0.1.0-review.2` |
| 契约状态 | `draft-pending-review` |
| 服务地址 | http://127.0.0.1:8309 |

公路工程业务智能体与文档加工服务的对外 HTTP 契约。当前文件是从实现归纳的待确认草案：已实现接口的请求和成功响应来自 FastAPI/Pydantic，OCR、WBS 的响应体及统一错误响应由 scripts/docs/openapi_contract.py 补充。经用户批准前不得视为正式契约，也不得据此绕过接口变更审批。

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
| 8 | `POST /ocr/recognize` | 识别普通照片或简表照片 | `pending-review` |
| 9 | `POST /ocr/daily-logs` | 识别监理日记（JLB13） | `pending-review` |
| 10 | `POST /ocr/daily-logs-new` | 识别监理日记（新版链路） | `pending-review` |
| 11 | `POST /ocr/jianbiao` | 识别简表并回填目标表 | `pending-review` |
| 12 | `POST /ocr/fill` | 按公式/引用计算并回填目标表 | `pending-review` |
| 13 | `GET /ocr/blank/{form}.png` | 渲染空白表样 PNG | `pending-review` |
| 14 | `GET /ocr/sheet/{form}` | 查询表样栏目与格子 | `pending-review` |
| 15 | `POST /wbs/draft` | 生成施工图 WBS 划分初稿 | `pending-review` |

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

### 8. `POST /ocr/recognize`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 识别普通照片或简表照片 |
| 契约状态 | `pending-review` |
| 来源 | AGENTS.md 第四节；docs/ocr.md；docs/ocr.md#http-接口；app/api/ocr.py；tests/test_ocr_recognize.py |
| 副作用 | 只读取数据池照片，不写文件。 |
| 幂等/重试 | 识别结果可能因模型、照片和模板变化而不同；只读调用可重试。 |

识别普通照片或已知表号照片。path 与 img 至少提供一个，同时提供时优先 img；未指定 form 时只按栏目文字取值。返回识别草稿，200 不代表字段全部准确。

**请求体**

```json
{
  "path": "projects/现场照片.jpg",
  "form": "JB12-4.2.2"
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的照片路径 |
| `form` | string | 否 | `""` |  | 表号；省略或空字符串时只按栏目文字取值。 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |

Schema：`RecognizeReq`

**响应**

- `200`：识别草稿。
- `400`：路径越界、文件不存在/不是文件、图片无法解码或文档处理失败。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `503`：模板资源或 OCR 模型不可用。

**200 响应体**

```json
{
  "status": 200,
  "data": {
    "form": "JB12-4.2.2",
    "formName": "土方路基抽检记录表",
    "layout": true,
    "fields": {
      "fld_supervisor": "四川公路工程咨询监理有限公司"
    },
    "keys": {},
    "detail": [
      {
        "field": "fld_supervisor",
        "value": "四川公路工程咨询监理有限公司",
        "how": "rect",
        "conf": 0.98,
        "boxes": [
          [
            10,
            10,
            300,
            40
          ]
        ]
      }
    ],
    "warning": "",
    "align": {
      "ax": 800,
      "bx": 0,
      "ay": 600,
      "by": 0,
      "anchors": 4,
      "how": "anchors"
    },
    "image": {
      "width": 600,
      "height": 400
    },
    "lines": [
      {
        "s": "监理单位：测试公司",
        "box": [
          10,
          10,
          300,
          40
        ],
        "conf": 0.99
      }
    ],
    "ms": 123
  }
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `RecognizeData` | 是 |  |  | 普通照片/简表照片识别草稿；200 不代表每个字段都准确。 |

**`data` 字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `form` | string | 是 |  |  | 请求中的表号；未指定时为空字符串。 |
| `formName` | string | 是 |  |  | 模板库中的表名；未知表号时为空字符串。 |
| `layout` | boolean | 是 |  |  | 是否加载到表样版面坐标。 |
| `fields` | object | 是 |  |  | 栏目字段 → 识别值；未识别到的栏目不出现。 |
| `keys` | object | 是 |  |  | 第二册关键项目合格率等字段；仅按模板坐标对齐时产生。 |
| `detail` | array<`RecognizeDetailItem`> | 是 |  |  | 每个字段的取值方式、置信度和来源文字框。 |
| `warning` | string | 是 |  |  | 表号缺失、模板缺失或照片与表样不匹配时的提示；空字符串表示无提示。 |
| `align` | `AlignInfo` | 是 |  |  |  |
| `image` | `ImageSize` | 是 |  |  | 输入图片的像素尺寸。 |
| `lines` | array<`OcrLine`> | 是 |  |  | 原始 OCR 文字框。 |
| `ms` | integer | 是 |  | minimum=0 | 本次识别耗时，毫秒。 |

Schema：`RecognizeResponse`

### 9. `POST /ocr/daily-logs`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 识别监理日记（JLB13） |
| 契约状态 | `pending-review` |
| 来源 | AGENTS.md 第四节；docs/ocr.md；app/ocr/daily_logs.py；tests/test_ocr_daily_logs.py |
| 副作用 | 只读取数据池照片，不写 PDF/Excel。 |
| 幂等/重试 | 识别结果可能因模型和照片变化而不同；只读调用可重试。 |

识别监理日记照片，固定栏目输出 recognized、detail 和业务结构 processed。path 与 img 至少提供一个，同时提供时优先 img；taskId 原样回显到 processed.taskId，服务不生成任务 ID。

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

Schema：`DailyLogsReq`

**响应**

- `200`：监理日志识别草稿。
- `400`：路径越界、文件不存在/不是文件、图片无法解码或文档处理失败。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `503`：OCR 模型不可用。

**200 响应体**

```json
{
  "status": 200,
  "data": {
    "form": "JLB13",
    "formName": "监理日志",
    "frame": {
      "how": "contour",
      "quad": [
        [
          0,
          0
        ],
        [
          599,
          0
        ],
        [
          599,
          848
        ],
        [
          0,
          848
        ]
      ]
    },
    "recognized": {
      "project": "测试高速公路项目",
      "position": "专业监理工程师",
      "date": "2026-10-03",
      "weather": "晴",
      "construction": "路基填筑",
      "witness": "旁站检查 2 次",
      "patrol": "巡视检查",
      "issues": "无",
      "next_day_plan": "继续填筑"
    },
    "detail": [],
    "processed": {
      "taskId": "123456789012345678",
      "documentType": "supervision_diary",
      "common": {
        "projectName": "测试高速公路项目",
        "documentNo": null,
        "supervisionOrg": null,
        "recorderName": null,
        "recorderPosition": "专业监理工程师",
        "weather": "晴",
        "logDate": "2026-10-03",
        "reviewerName": null
      },
      "fields": {
        "mainWork": {
          "construction": "路基填筑",
          "witness": "旁站检查 2 次",
          "patrol": "巡视检查"
        },
        "issues": "无",
        "nextDayPlan": "继续填筑"
      }
    },
    "warning": "",
    "image": {
      "width": 600,
      "height": 849
    },
    "ms": 123
  }
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `DailyLogsData` | 是 |  |  | 监理日记识别草稿；recognized 为原始栏目，processed 为业务结构。 |

**`data` 字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `form` | const `JLB13` | 是 |  |  |  |
| `formName` | const `监理日志` | 是 |  |  |  |
| `frame` | `Frame` | 是 |  |  |  |
| `recognized` | `DailyLogsRecognized` | 是 |  |  | 监理日记固定栏目；未识别到的栏目可能省略。 |
| `detail` | array<`DailyLogsDetailItem`> | 是 |  |  | 每个固定栏目的识别值、置信度和区域。 |
| `processed` | `DailyLogsProcessed` | 是 |  |  | 监理日记业务结构；由 OCR 栏目文本映射，缺失栏目为 null。 |
| `warning` | string | 是 |  |  | 未检测到表格外框等定位提示；空字符串表示无提示。 |
| `image` | `ImageSize` | 是 |  |  | 输入图片的像素尺寸。 |
| `ms` | integer | 是 |  | minimum=0 |  |

Schema：`DailyLogsResponse`

### 10. `POST /ocr/daily-logs-new`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 识别监理日记（新版链路） |
| 契约状态 | `pending-review` |
| 来源 | interfaces/journal/response.schema.json（成功响应已确认）；app/ocr/resources/daily-logs-output.json；tests/test_ocr_journal.py |
| 副作用 | 只读取数据池照片，不写 PDF/Excel。 |
| 幂等/重试 | 识别结果可能因模型和照片变化而不同；只读调用可重试。 |

新版监理日志识别：定位表格、整页 OCR 后匹配栏目；歧义或漏框字段最多补充识别 3 次。成功响应严格遵守已确认的后端格式，顶层只有 status、message、data，业务字段直接位于 data，不返回内部识别详情。construction / witness / patrol 同属 mainWork 单元格，当前暂时回填同一整段值。

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
- `400`：路径越界、文件不存在/不是文件、图片无法解码或文档处理失败。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
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
        "construction": "主要施工情况路基填筑旁站情况旁站检查巡视情况巡视检查",
        "witness": "主要施工情况路基填筑旁站情况旁站检查巡视情况巡视检查",
        "patrol": "主要施工情况路基填筑旁站情况旁站检查巡视情况巡视检查"
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

### 11. `POST /ocr/jianbiao`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 识别简表并回填目标表 |
| 契约状态 | `pending-review` |
| 来源 | AGENTS.md 第四节；docs/ocr.md；app/ocr/jianbiao.py；tests/test_ocr.py |
| 副作用 | out 非空时在 PROJECTS_ROOT 内写同名 .pdf、.xlsx 和 .warp.jpg。 |
| 幂等/重试 | 相同 out 重试会覆盖输出文件；调用前应确认是否允许覆盖。 |

现场简表照片：轮廓定位、逐格识别，再按 cfg 公式/引用计算目标表并回填。out 为空只计算，不写 PDF/Excel/校正图。

**请求体**

```json
{
  "path": "projects/简表照片.jpg",
  "form": "JB12-4.2.2",
  "cfg": {},
  "bound": {},
  "out": ""
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的照片路径 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |
| `form` | string | 是 |  | minLength=1 | 目标表号，同时用于查找简表版面。 |
| `cfg` | object | 是 |  |  | 配置平台的字段、锚点、引用和公式元数据。 |
| `bound` | object | 否 |  |  | 项目资料带入值；照片识别值优先。 |
| `out` | string | 否 | `""` |  | 输出 PDF 相对路径；为空不写 PDF/Excel/校正图。 |

Schema：`JianbiaoReq`

**响应**

- `200`：识别、计算与输出路径。
- `400`：路径越界、文件不存在、简表版面缺失、图片处理失败或公式循环引用。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `503`：模板资源或 OCR 模型不可用。

**200 响应体**

```json
{
  "status": 200,
  "data": {
    "jianbiao": "SIMPLE",
    "jianbiaoName": "测试简表",
    "frame": {
      "how": "contour",
      "quad": [
        [
          0,
          0
        ],
        [
          599,
          0
        ],
        [
          599,
          848
        ],
        [
          0,
          848
        ]
      ]
    },
    "recognized": {
      "fld_1": "96.5"
    },
    "detail": [],
    "target": "JB12-4.2.2",
    "targetName": "土方路基抽检记录表",
    "values": {
      "fld_1": "96.5"
    },
    "errors": {},
    "anchors": [],
    "pdf": "",
    "xlsx": "",
    "xlsxSkipped": [],
    "ms": 123
  }
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `JianbiaoData` | 是 |  |  |  |

**`data` 字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `jianbiao` | string | 是 |  |  | 匹配到的简表编号。 |
| `jianbiaoName` | string | 是 |  |  |  |
| `frame` | `Frame` | 是 |  |  |  |
| `recognized` | `StringMap` | 是 |  |  |  |
| `detail` | array<`CellDetailItem`> | 是 |  |  | 简表每个格子的识别值、置信度和区域。 |
| `target` | string | 是 |  |  | 目标表号。 |
| `targetName` | string | 是 |  |  |  |
| `values` | `StringMap` | 是 |  |  |  |
| `errors` | object | 是 |  |  | 单条公式失败原因；调用方必须检查，失败字段不会写入计算值。 |
| `anchors` | array<`AnchoredCell`> | 是 |  |  |  |
| `pdf` | string | 是 |  |  | 相对 PROJECTS_ROOT 的 PDF 路径；未写文件时为空字符串。 |
| `xlsx` | string | 是 |  |  | 相对 PROJECTS_ROOT 的 Excel 路径；未写文件时为空字符串。 |
| `xlsxSkipped` | array<string> | 是 |  |  |  |
| `ms` | integer | 是 |  | minimum=0 |  |

Schema：`JianbiaoResponse`

### 12. `POST /ocr/fill`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 按公式/引用计算并回填目标表 |
| 契约状态 | `pending-review` |
| 来源 | AGENTS.md 第四节；docs/ocr.md；app/ocr/jianbiao.py；tests/test_ocr.py |
| 副作用 | out 非空时在 PROJECTS_ROOT 内写同名 .pdf、.xlsx。 |
| 幂等/重试 | 相同 out 重试会覆盖输出文件；调用前应确认是否允许覆盖。 |

不识别照片，按配置公式/引用计算 values 并回填目标表；out 为空只计算，不写文件。计算公式字段以公式结果为准，传入的旧值不算数。

**请求体**

```json
{
  "form": "JB12-4.2.2",
  "cfg": {
    "formulas": [
      {
        "target": "rate",
        "expr": "PASS_RATE(94, @{v1}, @{v2})"
      }
    ]
  },
  "values": {
    "v1": "96.1",
    "v2": "93.2"
  },
  "out": ""
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `form` | string | 是 |  | minLength=1 | 目标表号。 |
| `cfg` | object | 是 |  |  | 配置平台的字段、锚点、引用和公式元数据。 |
| `values` | object | 是 |  |  | 待计算和回填的字段值；公式目标字段以计算结果为准。 |
| `out` | string | 否 | `""` |  | 输出 PDF 相对路径；为空只计算，不写文件。 |
| `rects` | object | 否 |  |  | 本张表调整后的字段坐标 {x,y,w,h}。 |

Schema：`FillReq`

**响应**

- `200`：计算值、错误、锚点与输出路径。
- `400`：路径越界、输出不是 PDF、公式循环引用或文档处理失败。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `503`：模板资源不可用。

**200 响应体**

```json
{
  "status": 200,
  "data": {
    "target": "JB12-4.2.2",
    "targetName": "土方路基抽检记录表",
    "values": {
      "fld_rate": "50"
    },
    "errors": {},
    "anchors": [],
    "pdf": "",
    "xlsx": "",
    "xlsxSkipped": []
  }
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `FillData` | 是 |  |  |  |

**`data` 字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `target` | string | 是 |  |  |  |
| `targetName` | string | 是 |  |  |  |
| `values` | `StringMap` | 是 |  |  |  |
| `errors` | object | 是 |  |  | 单条公式失败原因；调用方必须检查。 |
| `anchors` | array<`AnchoredCell`> | 是 |  |  |  |
| `pdf` | string | 是 |  |  |  |
| `xlsx` | string | 是 |  |  |  |
| `xlsxSkipped` | array<string> | 是 |  |  |  |

Schema：`FillResponse`

### 13. `GET /ocr/blank/{form}.png`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 渲染空白表样 PNG |
| 契约状态 | `pending-review` |
| 来源 | AGENTS.md 第四节；docs/ocr.md；app/api/ocr.py；tests/test_ocr.py |
| 副作用 | 无；只读取模板资源。 |
| 幂等/重试 | 只读，可安全重试。 |

渲染模板表样第 1 页为 PNG；width 为期望像素宽度，实际按不超过 2400 渲染。响应是原始 image/png，不是 {status, data} 包装。

**请求参数**

| 位置 | 名称 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| path | `form` | string | 是 |  | 模板表号。 |
| query | `width` | integer | 否 | minimum=1 | 期望渲染宽度（像素），最小 1；超过 2400 时按 2400 渲染。 |

**响应**

- `200`：表样第 1 页 PNG。
- `400`：模板资源路径越界、PDF 不存在或文档渲染失败。
- `404`：模板库没有该表号的表样 PDF。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `503`：模板资源不可用。

**200 `image/png`**

### 14. `GET /ocr/sheet/{form}`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 查询表样栏目与格子 |
| 契约状态 | `pending-review` |
| 来源 | AGENTS.md 第四节；docs/ocr.md；app/ocr/grid.py；tests/test_ocr.py |
| 副作用 | 无；只读取模板资源。 |
| 幂等/重试 | 只读，可安全重试。 |

返回表样上可填的版面栏（fld_*）和其余空格子（g*），供业务端定位与回填。

**请求参数**

| 位置 | 名称 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| path | `form` | string | 是 |  | 模板表号。 |

**响应**

- `200`：栏目与格子列表。
- `400`：模板资源路径越界或表样读取失败。
- `404`：模板库没有该表号的表样 PDF。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `503`：模板资源不可用。

**200 响应体**

```json
{
  "status": 200,
  "data": [
    {
      "field": "fld_supervisor",
      "name": "监理单位",
      "rect": {
        "x": 0.1,
        "y": 0.1,
        "w": 0.2,
        "h": 0.1
      },
      "behavior": "INPUT",
      "kind": "layout"
    }
  ]
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `SheetCellList` | 是 |  |  | 表样上可填的版面栏与其余空格子。 |

Schema：`SheetResponse`

### 15. `POST /wbs/draft`

| 项目 | 内容 |
| --- | --- |
| 摘要 | 生成施工图 WBS 划分初稿 |
| 契约状态 | `pending-review` |
| 来源 | AGENTS.md 第四节；docs/ocr.md；app/ocr/wbs_draft.py；tests/test_ocr.py |
| 副作用 | 只读取数据池文件，不写文件。 |
| 幂等/重试 | 同一输入结果稳定；只读调用可重试。 |

读取施工图 PDF（或 _N.pdf 单页拆分目录）和可选工可依据，生成单位/分部/分项划分初稿。不执行人工确认、审批或落库；当前不生成隧道划分。

**请求体**

```json
{
  "prefix": "S210",
  "drawings": [
    "projects/drawings/plan.pdf"
  ],
  "basis": {
    "facts": [
      [
        "路线起讫",
        "K0+000~K4+000"
      ]
    ]
  }
}
```

**请求字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `prefix` | string | 是 |  | minLength=1 | 合同段编码前缀，例如 S210。 |
| `drawings` | array<string> | 否 |  |  | PROJECTS_ROOT 数据池内的 PDF 路径或目录列表 |
| `imgs` | array<string> | 否 |  |  | base64 编码的 PDF 数据列表；drawings 与 imgs 至少提供一个 |
| `basis` | object 或 null | 否 |  |  | 工可依据，可包含 facts 键值对数组或对象。 |

Schema：`DraftReq`

**响应**

- `200`：划分初稿与识别依据。
- `400`：路径越界、施工图不是 PDF 或文档处理失败。
- `422`：请求校验失败，或输入与上下文超过预算。校验失败时 detail 为错误数组；输入超限时为字符串。
- `503`：WBS 规则模板或 PDF 处理资源不可用。

**200 响应体**

```json
{
  "status": 200,
  "data": {
    "units": [
      {
        "code": "S210-LJ01",
        "title": "K0+000-K4+000路基工程",
        "children": []
      }
    ],
    "count": {
      "units": 1,
      "parts": 0,
      "items": 0,
      "subs": 0
    },
    "drawings": []
  }
}
```

**响应字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `WbsDraftData` | 是 |  |  |  |

**`data` 字段**

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `units` | array<`WbsNode`> | 是 |  |  |  |
| `count` | `WbsCount` | 是 |  |  |  |
| `drawings` | array<`WbsDrawing`> | 是 |  |  |  |

Schema：`WbsDraftResponse`

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

### `BusinessIntentOption`

澄清时可选的合法二级功能。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | enum（`supervision_diary`、`work_list`、`image_library`、`recognition_platform`、`business_management`、`workbench`） | 是 |  |  |  |
| `action` | enum（`fill_supervision_log`、`fill_monthly_report`、`assign_monthly_report`、`view_supervision_log`、`fill_inspection_record`、`fill_standby_record`、`fill_environmental_log`、`fill_safety_log`、`approve_log`、`view_work_tasks`、`create_work_task`、`add_form`、`delete_supervision_form`、`view_approval_workflow`、`view_image_library`、`delete_image`、`create_album`、`delete_album`、`navigate_to_recognition`、`recognize_photo`、`add_personnel_configuration`、`delete_project_member`、`view_wbs`、`add_subproject`、`add_child_subproject`、`delete_subproject`、`delete_child_subproject`、`assign_wbs_personnel`、`navigate_to_work`、`view_today_tasks`、`view_pending_approvals`） | 是 |  |  |  |
| `name` | string | 是 |  | minLength=1，maxLength=100 |  |

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

### `DailyLogsReq`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的监理日志照片路径 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |
| `taskId` | string | 否 | `""` | maxLength=128 | 业务任务 ID，仅原样回显到 processed.taskId；不传则为 null |

### `DraftReq`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `prefix` | string | 是 |  | minLength=1 | 合同段编码前缀，例如 S210。 |
| `drawings` | array<string> | 否 |  |  | PROJECTS_ROOT 数据池内的 PDF 路径或目录列表 |
| `imgs` | array<string> | 否 |  |  | base64 编码的 PDF 数据列表；drawings 与 imgs 至少提供一个 |
| `basis` | object 或 null | 否 |  |  | 工可依据，可包含 facts 键值对数组或对象。 |

### `FillReq`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `form` | string | 是 |  | minLength=1 | 目标表号。 |
| `cfg` | object | 是 |  |  | 配置平台的字段、锚点、引用和公式元数据。 |
| `values` | object | 是 |  |  | 待计算和回填的字段值；公式目标字段以计算结果为准。 |
| `out` | string | 否 | `""` |  | 输出 PDF 相对路径；为空只计算，不写文件。 |
| `rects` | object | 否 |  |  | 本张表调整后的字段坐标 {x,y,w,h}。 |

### `HTTPValidationError`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `detail` | array<`ValidationError`> | 否 |  |  |  |

### `IntentRequest`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `user_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `session_id` | string | 是 |  | minLength=1，maxLength=128 |  |
| `history` | array<`ChatMessage`> | 是 |  |  | 当前用户当前会话的完整历史，首轮为[] |
| `text` | string | 是 |  | minLength=1，maxLength=2000 | 待识别的归档业务内容 |
| `intents` | array<`JsonValue`> | 否 |  | maxItems=0 | 仅为兼容保留，必须省略或为[]；不支持调用方自定义分类 |

### `JianbiaoReq`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的照片路径 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |
| `form` | string | 是 |  | minLength=1 | 目标表号，同时用于查找简表版面。 |
| `cfg` | object | 是 |  |  | 配置平台的字段、锚点、引用和公式元数据。 |
| `bound` | object | 否 |  |  | 项目资料带入值；照片识别值优先。 |
| `out` | string | 否 | `""` |  | 输出 PDF 相对路径；为空不写 PDF/Excel/校正图。 |

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

### `RecognizeReq`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `path` | string | 否 | `""` |  | PROJECTS_ROOT 数据池内的照片路径 |
| `form` | string | 否 | `""` |  | 表号；省略或空字符串时只按栏目文字取值。 |
| `img` | string | 否 | `""` |  | base64 编码的图片数据；path 与 img 至少提供一个 |

### `ValidationError`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `loc` | array<string 或 integer> | 是 |  |  |  |
| `msg` | string | 是 |  |  |  |
| `type` | string | 是 |  |  |  |
| `input` | any | 否 |  |  |  |
| `ctx` | object | 否 |  |  |  |

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

### `ImageSize`

输入图片的像素尺寸。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `width` | integer | 是 |  | minimum=1 |  |
| `height` | integer | 是 |  | minimum=1 |  |

### `AlignInfo`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `anchors` | integer | 是 |  | minimum=0 | 匹配到的表样锚点数。 |
| `how` | enum（`anchors`、`mismatch`、`none`） | 是 |  |  | anchors 表示按模板坐标取值；mismatch 表示照片与表样对不上；none 表示没有可用模板坐标。 |
| `ax` | number | 否 |  |  | 表样 x 比例到照片像素的缩放系数。 |
| `bx` | number | 否 |  |  | 表样 x 比例到照片像素的偏移。 |
| `ay` | number | 否 |  |  | 表样 y 比例到照片像素的缩放系数。 |
| `by` | number | 否 |  |  | 表样 y 比例到照片像素的偏移。 |

### `RecognizeDetailItem`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `field` | string | 是 |  |  |  |
| `value` | string | 是 |  |  |  |
| `how` | enum（`inline`、`rect`、`right`） | 是 |  |  | inline 为栏目名同行；rect 为模板坐标内；right 为栏目名右侧。 |
| `conf` | number | 是 |  | minimum=0，maximum=1 |  |
| `boxes` | array<array<number>> | 是 |  |  | 来源文字框 [x0, y0, x1, y1]。 |

### `OcrLine`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `s` | string | 是 |  |  | 原始 OCR 文字。 |
| `box` | array<number> | 是 |  | minItems=4，maxItems=4 | 文字框 [x0, y0, x1, y1]。 |
| `conf` | number | 是 |  | minimum=0，maximum=1 |  |

### `RecognizeData`

普通照片/简表照片识别草稿；200 不代表每个字段都准确。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `form` | string | 是 |  |  | 请求中的表号；未指定时为空字符串。 |
| `formName` | string | 是 |  |  | 模板库中的表名；未知表号时为空字符串。 |
| `layout` | boolean | 是 |  |  | 是否加载到表样版面坐标。 |
| `fields` | object | 是 |  |  | 栏目字段 → 识别值；未识别到的栏目不出现。 |
| `keys` | object | 是 |  |  | 第二册关键项目合格率等字段；仅按模板坐标对齐时产生。 |
| `detail` | array<`RecognizeDetailItem`> | 是 |  |  | 每个字段的取值方式、置信度和来源文字框。 |
| `warning` | string | 是 |  |  | 表号缺失、模板缺失或照片与表样不匹配时的提示；空字符串表示无提示。 |
| `align` | `AlignInfo` | 是 |  |  |  |
| `image` | `ImageSize` | 是 |  |  | 输入图片的像素尺寸。 |
| `lines` | array<`OcrLine`> | 是 |  |  | 原始 OCR 文字框。 |
| `ms` | integer | 是 |  | minimum=0 | 本次识别耗时，毫秒。 |

### `RecognizeResponse`

普通照片识别成功响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `RecognizeData` | 是 |  |  | 普通照片/简表照片识别草稿；200 不代表每个字段都准确。 |

### `Frame`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `how` | enum（`contour`、`contour+table`、`whole`、`whole+table`） | 是 |  |  | 外框定位方式；whole 表示未找到轮廓，按整张照片校正。 |
| `quad` | array<array<integer>> | 是 |  | minItems=4，maxItems=4 | 照片坐标系中的四角 [[x, y], ...]。 |

### `DailyLogsDetailItem`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `field` | string | 是 |  |  |  |
| `label` | string | 是 |  |  |  |
| `value` | string | 是 |  |  |  |
| `conf` | number | 是 |  | minimum=0，maximum=1 |  |
| `rect` | array<integer> | 是 |  | minItems=4，maxItems=4 | 校正后页面中的识别区域 [x0, y0, x1, y1]。 |

### `DailyLogsRecognized`

监理日记固定栏目；未识别到的栏目可能省略。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `project` | string | 否 |  |  |  |
| `number` | string | 否 |  |  |  |
| `supervision_org` | string | 否 |  |  |  |
| `recorder` | string | 否 |  |  |  |
| `weather` | string | 否 |  |  |  |
| `position` | string | 否 |  |  |  |
| `date` | string | 否 |  |  | 归一为 yyyy-mm-dd；识别不到时省略。 |
| `reviewer` | string | 否 |  |  |  |
| `construction` | string | 否 |  |  |  |
| `witness` | string | 否 |  |  |  |
| `patrol` | string | 否 |  |  |  |
| `issues` | string | 否 |  |  |  |
| `next_day_plan` | string | 否 |  |  |  |

### `DailyLogsMainWork`

当日主要监理工作情况下的三个子栏；识别不到为 null。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `construction` | string / null | 是 |  |  |  |
| `witness` | string / null | 是 |  |  |  |
| `patrol` | string / null | 是 |  |  |  |

### `DailyLogsCommon`

监理日记公共栏目；识别不到为 null，不做推断。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `projectName` | string / null | 是 |  |  |  |
| `documentNo` | string / null | 是 |  |  |  |
| `supervisionOrg` | string / null | 是 |  |  |  |
| `recorderName` | string / null | 是 |  |  |  |
| `recorderPosition` | string / null | 是 |  |  |  |
| `weather` | string / null | 是 |  |  |  |
| `logDate` | string / null | 是 |  |  |  |
| `reviewerName` | string / null | 是 |  |  |  |

### `DailyLogsFields`

监理日记正文栏目；识别不到为 null。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `mainWork` | `DailyLogsMainWork` | 是 |  |  | 当日主要监理工作情况下的三个子栏；识别不到为 null。 |
| `issues` | string / null | 是 |  |  |  |
| `nextDayPlan` | string / null | 是 |  |  |  |

### `DailyLogsProcessed`

监理日记业务结构；由 OCR 栏目文本映射，缺失栏目为 null。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `taskId` | string / null | 是 |  |  | 请求 taskId 原样回显；未提供为 null。 |
| `documentType` | const `supervision_diary` | 是 |  |  |  |
| `common` | `DailyLogsCommon` | 是 |  |  | 监理日记公共栏目；识别不到为 null，不做推断。 |
| `fields` | `DailyLogsFields` | 是 |  |  | 监理日记正文栏目；识别不到为 null。 |

### `DailyLogsData`

监理日记识别草稿；recognized 为原始栏目，processed 为业务结构。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `form` | const `JLB13` | 是 |  |  |  |
| `formName` | const `监理日志` | 是 |  |  |  |
| `frame` | `Frame` | 是 |  |  |  |
| `recognized` | `DailyLogsRecognized` | 是 |  |  | 监理日记固定栏目；未识别到的栏目可能省略。 |
| `detail` | array<`DailyLogsDetailItem`> | 是 |  |  | 每个固定栏目的识别值、置信度和区域。 |
| `processed` | `DailyLogsProcessed` | 是 |  |  | 监理日记业务结构；由 OCR 栏目文本映射，缺失栏目为 null。 |
| `warning` | string | 是 |  |  | 未检测到表格外框等定位提示；空字符串表示无提示。 |
| `image` | `ImageSize` | 是 |  |  | 输入图片的像素尺寸。 |
| `ms` | integer | 是 |  | minimum=0 |  |

### `DailyLogsResponse`

监理日志识别成功响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `DailyLogsData` | 是 |  |  | 监理日记识别草稿；recognized 为原始栏目，processed 为业务结构。 |

### `CellDetailItem`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `field` | string | 是 |  |  |  |
| `label` | string | 是 |  |  |  |
| `value` | string | 是 |  |  |  |
| `conf` | number | 是 |  | minimum=0，maximum=1 |  |
| `rect` | array<integer> | 是 |  | minItems=4，maxItems=4 |  |

### `RatioRect`

页面比例坐标；与简表 cells 的 [x, y, w, h] 数组语义相同但表示不同。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `x` | number | 是 |  |  |  |
| `y` | number | 是 |  |  |  |
| `w` | number | 是 |  | exclusiveMinimum=0 |  |
| `h` | number | 是 |  | exclusiveMinimum=0 |  |

### `AnchoredCell`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `anchor` | string | 是 |  |  | 配置锚点 ID；模板或网格补位时为空字符串。 |
| `field` | string | 是 |  |  |  |
| `behavior` | string | 是 |  |  |  |
| `rect` | `RatioRect` | 是 |  |  | 页面比例坐标；与简表 cells 的 [x, y, w, h] 数组语义相同但表示不同。 |
| `value` | string | 是 |  |  |  |
| `src` | string | 是 |  |  | 取值来源，例如 TEMPLATE、COPY、field、layout、grid。 |

### `StringMap`

类型：object

### `JianbiaoData`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `jianbiao` | string | 是 |  |  | 匹配到的简表编号。 |
| `jianbiaoName` | string | 是 |  |  |  |
| `frame` | `Frame` | 是 |  |  |  |
| `recognized` | `StringMap` | 是 |  |  |  |
| `detail` | array<`CellDetailItem`> | 是 |  |  | 简表每个格子的识别值、置信度和区域。 |
| `target` | string | 是 |  |  | 目标表号。 |
| `targetName` | string | 是 |  |  |  |
| `values` | `StringMap` | 是 |  |  |  |
| `errors` | object | 是 |  |  | 单条公式失败原因；调用方必须检查，失败字段不会写入计算值。 |
| `anchors` | array<`AnchoredCell`> | 是 |  |  |  |
| `pdf` | string | 是 |  |  | 相对 PROJECTS_ROOT 的 PDF 路径；未写文件时为空字符串。 |
| `xlsx` | string | 是 |  |  | 相对 PROJECTS_ROOT 的 Excel 路径；未写文件时为空字符串。 |
| `xlsxSkipped` | array<string> | 是 |  |  |  |
| `ms` | integer | 是 |  | minimum=0 |  |

### `JianbiaoResponse`

简表识别与填表成功响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `JianbiaoData` | 是 |  |  |  |

### `FillData`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `target` | string | 是 |  |  |  |
| `targetName` | string | 是 |  |  |  |
| `values` | `StringMap` | 是 |  |  |  |
| `errors` | object | 是 |  |  | 单条公式失败原因；调用方必须检查。 |
| `anchors` | array<`AnchoredCell`> | 是 |  |  |  |
| `pdf` | string | 是 |  |  |  |
| `xlsx` | string | 是 |  |  |  |
| `xlsxSkipped` | array<string> | 是 |  |  |  |

### `FillResponse`

公式/引用计算与填表成功响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `FillData` | 是 |  |  |  |

### `SheetCell`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `field` | string | 是 |  |  | 字段 ID 或格子键。 |
| `name` | string | 是 |  |  |  |
| `rect` | `RatioRect` | 是 |  |  | 页面比例坐标；与简表 cells 的 [x, y, w, h] 数组语义相同但表示不同。 |
| `behavior` | string | 是 |  |  | 填写行为，例如 INPUT。 |
| `kind` | enum（`layout`、`grid`） | 是 |  |  |  |

### `SheetCellList`

表样上可填的版面栏与其余空格子。

类型：array<`SheetCell`>

### `SheetResponse`

表样栏目成功响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `SheetCellList` | 是 |  |  | 表样上可填的版面栏与其余空格子。 |

### `WbsSource`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `page` | integer / null | 是 |  |  | 来源页码；无法定位时为 null。 |
| `text` | string | 是 |  |  | 识别依据原文。 |

### `WbsNode`

单位/分部/分项/子分项递归节点；叶子节点的 children 为 []。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `code` | string | 否 |  |  |  |
| `title` | string | 是 |  |  |  |
| `src` | array<`WbsSource`> | 否 |  |  | 识别依据；仅部分单位工程节点带该字段。 |
| `children` | array<`WbsNode`> | 是 |  |  |  |

### `WbsDrawing`

单份施工图的识别摘要；桥梁字段只在 bridge 类型出现。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `file` | string | 是 |  |  |  |
| `src` | array<`WbsSource`> | 是 |  |  |  |
| `kind` | enum（`bridge`、`tunnel`、`road`） | 是 |  |  |  |
| `name` | string | 是 |  |  |  |
| `volume` | string | 是 |  |  |  |
| `chainage` | array / null | 是 |  | minItems=2，maxItems=2 | 起止桩号（米）；未识别时为 null。 |
| `piers` | array<integer> | 否 |  |  |  |
| `abutments` | array<integer> | 否 |  |  |  |
| `spans` | integer | 否 |  |  |  |
| `split` | boolean | 否 |  |  |  |
| `girder` | string | 否 |  |  |  |
| `precast` | boolean | 否 |  |  |  |
| `partial` | boolean | 否 |  |  |  |

### `WbsCount`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `units` | integer | 是 |  | minimum=0 |  |
| `parts` | integer | 是 |  | minimum=0 |  |
| `items` | integer | 是 |  | minimum=0 |  |
| `subs` | integer | 是 |  | minimum=0 |  |

### `WbsDraftData`

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `units` | array<`WbsNode`> | 是 |  |  |  |
| `count` | `WbsCount` | 是 |  |  |  |
| `drawings` | array<`WbsDrawing`> | 是 |  |  |  |

### `WbsDraftResponse`

施工图划分初稿成功响应。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  | 业务成功状态，与 HTTP 200 一致；不是 HTTP 状态码的替代品。 |
| `data` | `WbsDraftData` | 是 |  |  |  |

### `JournalResponse`

用户于 2026-11-06 确认的 POST /ocr/daily-logs-new 成功响应；以 app/ocr/resources/daily-logs-output.json 为结构依据。

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `status` | const `200` | 是 |  |  |  |
| `message` | const `识别完成` | 是 |  |  |  |
| `data` | object | 是 |  |  |  |
