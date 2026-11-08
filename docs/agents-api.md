# 业务智能体 API

本文说明原有 `/agents/*` 契约。合并后的文档加工接口 `/ocr/*`、`/wbs/draft` 与系统级诊断 `/diagnostics` 见 [OCR API 与路径配置](ocr.md)，与本文共用 `app.main:app` 和 8309 端口。统一接口索引、契约状态和待确认草案见 [interfaces/README.md](../interfaces/README.md)；完整 OpenAPI 草案见 [interfaces/drafts/fastapi.openapi.json](../interfaces/drafts/fastapi.openapi.json)。

服务地址：`http://127.0.0.1:8309`。交互文档：`http://127.0.0.1:8309/docs`。`/docs` 是运行时实现的投影，不是正式契约；接口变更必须按 [AGENTS.md 第四节](../AGENTS.md#四接口契约与-api-first-开发流程)审批。

`user_id`、`session_id` 是必填业务标识，不是登录凭据。

| 业务 | 方法与路径 | 模块 |
| --- | --- | --- |
| 总结并生成工作日志 | `POST /agents/log-summary` | `app/agents/log_summary.py` |
| 业务端意图识别 | `POST /agents/intent/business` | `app/agents/intent_business.py`，目录见 `app/agents/intent_catalog.py` |
| 归档端意图识别 | `POST /agents/intent/archive` | `app/agents/intent.py`，配置见 `app/agents/profiles.py` |
| 自由对话 | `POST /agents/chat` | `app/agents/chat.py` |

当前 API 文档版本 `0.1.0`（以 `app/main.py` 为准）。三类智能体均通过 LangChain `create_agent()` 执行，共享 `app/llm.py` 的 `ChatOpenAI` 模型工厂和 `.env` 配置。日志总结、意图识别使用 `ProviderStrategy` 和 JSON Schema 约束生成，最后经过 Pydantic 校验；对话返回普通文本，再包装为 JSON。接口只处理传入内容，不执行外部业务操作，不将用户消息保存为服务端会话。

## 用户与会话请求契约

各智能体接口均要求非空字符串 `user_id`、`session_id`，去除首尾空白后各1–128字符。业务端意图还要求 `message`、`current_page`，`history` 可选；归档端和 `/chat` 必须传 `history`（首轮为 `[]`）；日志总结不接受该字段。业务意图的 `current_page`、`last_navigation`、`pending_clarification` 由调用方传入并持久化。完整示例、并发隔离、裁剪规则和身份信任边界见 [用户与会话](sessions.md)。

## 1. 工作日志总结

`content` 主要接收工程人员填表后的 OCR 识别 JSON 对象，也兼容既有通用日志文字和 JSON 对象。内部字段名、嵌套层级、指标数组或对象可变化，无须固定为下列示例结构；对象内部允许数组和 `null`。字符串去除首尾空白后不能为空，对象不能为空，顶层不接受数组，请求外层仅允许 `user_id`、`session_id` 和 `content`，不接收历史。

长度限制保持为 4000 字符：字符串按去除首尾空白后的长度计算，对象按 Python `json.dumps(content, ensure_ascii=False)` 的结果计算（包含默认分隔空格，不按 UTF-8 字节计数）。超限返回 `422`，不截断；表格较大时由调用方按记录拆分并保留必要工程上下文。接口不执行图片识别，输入是 OCR 后的数据。

请求示例（用户提供的系统输入，经 `content` 包装）：

```json
{
  "user_id": "example-user",
  "session_id": "example-session",
  "content": {
    "项目编号": "20240721LDZSM",
    "项目名称": "泸定至石棉高速公路工程项目",
    "表格类型": "JB12-4.2.2",
    "表格名称": "土方路基抽检记录表",
    "开工类型": null,
    "监理单位标段": "JL2",
    "监理单位名称": "四川公路工程咨询监理有限公司",
    "施工单位标段": "TJ9",
    "施工单位名称": "四川省交通建设集团有限责任公司",
    "抽检人": "任伟",
    "计划开始日期": "2024年10月25日",
    "分部工程": {
      "工程名称": "土方路基",
      "前桩号": "K86+300",
      "后桩号": "K86+660"
    },
    "fields": [
      {
        "key": "△压实度(%)",
        "norm": "△压实度(%)",
        "specified": "满足设计要求",
        "measured": [
          95.2,
          94.8,
          96.1
        ],
        "pass_rate": 100
      },
      {
        "key": "△弯沉（0.01mm）",
        "norm": "△弯沉(0.01mm)",
        "specified": "≤设计验收弯沉值",
        "measured": [
          0.1,
          0.2,
          0.3
        ],
        "pass_rate": null
      },
      {
        "key": "宽 度（mm）",
        "norm": "宽度(mm)",
        "specified": "满足设计要求",
        "measured": [
          1000,
          1005,
          1010
        ],
        "pass_rate": null
      }
    ]
  }
}
```

固定返回示例（参考话术，六个字段全部必填）：

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

固定输出接口的 [JSON Schema、示例和对接说明](../interfaces/log_summary/README.md) 位于 `interfaces/log_summary/`。`data/log_summary.json` 只保存用户提供的 OCR 原始对象，发送 HTTP 请求时需提供 `user_id`、`session_id`，并将原始对象放入 `content`。响应固定为 `title`、`date`、`summary`、`completed_items`、`pending_items`、`issues` 六个必填字段，禁止额外字段，空日期使用 `null`，无对应事实的数组使用 `[]`。

调用方读取 `summary` 作为当日日志的一部分；接口继续返回结构化 JSON，响应字段不变；接口路径已统一为 `/agents/log-summary`；旧文字及对象输入仍放在 content，但请求必须补充 user_id 和 session_id。

当前采用暂行客观描述规则，正式业务话术标准待补充；规则集中在 `app/prompts/log_summary.md`：

| 内容 | 处理规则 |
| --- | --- |
| `summary` | 一段正式中文，按项目或标段、工程部位、检测事项、指标实测值及记录结论组织；可分多句，无 Markdown、建议或字段解释，最多 1000 字符 |
| 指标 | `norm` 非空时优先，否则使用 `key`；可去除多余空格和装饰性 `△`，不修改指标含义或单位。其他结构按语义理解 |
| 要求与实测 | `specified` 是规定要求，不是已达标结论；`measured` 中的数值逐项保留并带原单位，不自行换算或只输出均值、范围 |
| 合格率 | 仅转述原表记录；`pass_rate: 100` 是该项记录合格率 100%，`0` 是有效的 0%；不得扩大到其他指标或整个工程，不自动计算或推断合格结论 |
| 空值与缺失 | `null`、空字符串、空数组和缺失字段不等于零或不合格，可描述未填写实测值、未记录合格率；不自动生成质量问题、复检或整改待办 |
| `date` | 只原样摘录明确日志日期或实际检测日期；仅有计划开始日期、开工或填表日期时为 `null`，日期冲突无法消除时也为 `null`；不补入当前日期 |
| 完成状态 | 表格或实测值存在不等于已完成检测或验收，优先表述为“抽检表记录”“实测值为”；不编造完成、整改或验收状态 |
| 列表 | `completed_items` 仅明确完成事项，`pending_items` 仅明确待办或进行中事项，`issues` 仅明确问题、风险或无法确定的矛盾；无对应事实为 `[]`，每个最多 8 项、每项最多 300 字符 |

`title` 为最多 100 字符的事项标题。`summary`、标题和列表不能添加原文未提供的日期、天气、人员职责、成果或计划。输入备注中的命令不能覆盖系统规则。以上语义由提示词约束和真实模型评测验证，JSON Schema / Pydantic 校验不能保证任意输入的事实正确性；OCR 含糊、矛盾和正式话术仍需业务人员核对。

评测数据与验收方法见 [日志总结测试说明](log-summary-testing.md)。

## 2. 意图识别

接口：`POST /agents/intent/business`。根据用户当前诉求、当前页面、上次导航和服务端业务目录，识别一级页面及能够完成任务的最小二级功能。本服务不保存会话、不做认证；调用方传入 `current_page`、可选的 `history`/`last_navigation`/`pending_clarification`，并持久化识别结果。

请求示例：

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/intent/business \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"example-user","session_id":"example-session","message":"我要填写今天的监理日志。","current_page":"workbench","history":[]}'
```

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `user_id`、`session_id` | 是 | 非空字符串，各最多128字符；只作业务标识，不是认证凭据 |
| `message` | 是 | 当前诉求，最多2000字符 |
| `current_page` | 是 | 调用方当前实际页面，必须是业务目录中的 page code |
| `history` | 否 | 当前会话历史，省略即 `[]`；只接受完整、交替的 user/assistant 回合 |
| `last_navigation` | 否 | 上一次返回的导航目标 `{page, action}`；`action` 可空且必须属于 `page` |
| `pending_clarification` | 否 | 一级意图澄清状态 `{page, attempts}`；`attempts` 为已完成的澄清轮数，0–10 |
| `request_id` | 否 | 仅供调用方关联；本服务不持久化，不提供幂等保证 |

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string 枚举 | `resolved`、`clarify`、`chat`、`unknown` |
| `page` | string 或 `null` | 一级页面 code |
| `action` | string 或 `null` | 二级功能 code；`resolved` 必填，`clarify` 必须为空 |
| `confidence` | number | 0–1 的模型判断分数，不是校准概率 |
| `message` | string 或 `null` | `resolved` 为 `null`；`clarify` 为澄清文案；`chat` 为回答；`unknown` 为引导 |
| `options` | array 或 `null` | 仅 `clarify` 返回，每项 `{page, action, name}`，全部属于 `page` |
| `catalog_version` | string | 业务功能 JSON 的内容哈希 |

状态语义：

| `status` | 调用方处理 |
| --- | --- |
| `resolved` | 按 `page/action` 映射到前端路由并跳转 |
| `clarify` | 展示 `message`，可用 `options` 渲染选项；不跳转 |
| `chat` | 展示 `message`；不跳转 |
| `unknown` | 请用户重新描述；不跳转 |

示例：

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

仅表达一级模块时，返回 `status="clarify"`、`page`、`action=null`，并调用 Chat 澄清模式生成 `message`；`options` 由后端从业务目录生成，Chat 只负责措辞，不得提出目录外操作。调用方保存 `pending_clarification.page` 和 `attempts`，每收到一次 `clarify` 将 `attempts` 加 1；同一页面达到 10 轮仍不明确时返回 `unknown`。Chat 澄清失败时返回 HTTP 200 的确定性选项文案。

```json
{
  "status": "clarify",
  "page": "supervision_diary",
  "action": null,
  "confidence": 0.9,
  "message": "你想填写监理日志、查看监理日志，还是执行其他监理日记相关操作？",
  "options": [
    {"page": "supervision_diary", "action": "fill_supervision_log", "name": "填写监理日志"},
    {"page": "supervision_diary", "action": "view_supervision_log", "name": "查看监理日志"}
  ],
  "catalog_version": "b158b448e3cf4d0a"
}
```

`current_page` 和 `last_navigation` 是上下文，不是限制条件。用户明确要求其他模块时，模型直接识别新页面；用户说“不对”“不是这个”时，结合 `last_navigation` 避免重复被否定的动作。服务不返回 `navigation_id`，不跟踪前端跳转是否成功。

业务目录唯一来源为 `app/resources/intent/business_pages.json`，构建期生成枚举；修改后运行 `uv run --locked python -m scripts.intent.compile_catalog`，并用 `--check` 校验。模型返回目录外编码、`action` 不属于 `page` 或结构不合法时返回 `502`。

错误：请求校验失败 `422`；模型不可达 `503`；分类、聊天或澄清超时 `504`；上游错误、非法输出或目录外编码 `502`。响应不泄露原始输入、身份、历史或上游错误正文。归档端见下一节。

## 2.1 归档端意图识别

文件归档系统使用独立的扁平 profile 和分类流程，接口为 `POST /agents/intent/archive`。请求沿用 `IntentRequest`：`text` 最多 2000 字符，必须携带 `history`，`intents` 只能省略或为 `[]`。响应为四字段，`intent` 只能取当前占位分类 `A`、`B`、`C`、`D` 或兜底 `unknown`；没有 `chat` 分流。

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/intent/archive \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"example-user","session_id":"example-session","history":[],"text":"把这份文件归档"}'
```

```json
{
  "intent": "A",
  "confidence": 0.95,
  "reason": "用户要求归档当前文件。",
  "needs_clarification": false
}
```

`A`–`D` 的业务含义尚未确定，当前只是占位标签；补充真实含义时修改 `app/agents/profiles.py` 的 `ARCHIVE_INTENTS` 与 `app/prompts/intent/archive.md`，无需复制 Agent 实现。归档端没有 `chat` 分类，问候或一般交流返回 `unknown`，不会触发聊天调用。模型返回 `A`–`D` 之外的业务端标签、旧标签或非法分数均视为非法输出并返回 `502`。低分、需澄清和显式 `unknown` 的统一回退规则由 `IntentProfile` 执行，阈值 `0.65` 由 profile 配置。

归档端响应的 [Schema 和示例](../interfaces/intent/archive/README.md) 位于 `interfaces/intent/archive/`。在真实分类含义补齐前，归档端不纳入真实模型语义评测；离线测试只验证档案隔离、枚举、回退、错误映射和契约。

## 3. 自由对话

最简单的请求只需要 `message`：

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"example-user","session_id":"example-session","history":[],"message":"你好，帮我解释一下什么是业务智能体。"}'
```

返回结构：

```json
{
  "reply": "业务智能体是能够理解业务需求，并结合规则或工具处理任务的程序……",
  "model": "qwen3.5:9b-q4_K_M"
}
```

多轮对话由调用方传回历史消息：

```json
{
  "user_id": "example-user",
  "session_id": "example-session",
  "history": [
    {
      "role": "user",
      "content": "项目代号是青松。"
    },
    {
      "role": "assistant",
      "content": "已记住项目代号：青松。"
    }
  ],
  "message": "项目代号是什么？"
}
```

- 当前 `message` 最多 2000 字符。
- `history` 必填，传入当前用户当前会话的全部历史；首轮为 `[]`，不再限制为10条。
- 历史消息按 `user`、`assistant` 交替排列，以 `user` 开头、`assistant` 结束。
- 历史内容必须非空，不再使用每条2000及总计4000字符限制；完整请求受可配置的输入总字符上限约束。超出上下文预算时裁剪最早的完整回合，保留当前消息。详见 [裁剪规则](sessions.md)。
- 不接收调用方的 `system` 消息；系统提示词在 `app/prompts/chat.md` 中维护。
- 每次返回完整回答，不使用流式响应。不同请求不会自动共享历史。

## 开发位置与验证

业务规则在 `app/agents/`，系统提示词在 `app/prompts/`，请求及返回类型在 `app/schemas/agents.py`，HTTP 路由在 `app/api/agents.py`、`system.py`，由 `app/api/router.py` 聚合、`app/main.py` 注册。`main.py` 保留应用工厂和共享资源生命周期；`app/http_errors.py` 注册原有全局异常处理器。`app/agents/base.py` 提供对话和结构化业务共用的 `BaseAgent`，以及带 Schema 和结果校验的 `StructuredAgent`；`runtime.py` 统一创建和调用 LangChain Agent，`middleware.py` 检查异常模型响应，`app/llm.py` 负责 OpenAI 兼容模型适配。新增业务的步骤见 [README](../README.md#项目结构与-agent-开发)。

```zsh
# 在项目根目录执行：
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked pytest -v
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python -m scripts.common.verify_agents
```

真实测试覆盖日志文字与 JSON 输入、`data/intent.json` 的完整版本化评测集、普通对话及携带历史的对话。意图逐条比对标签、澄清标记及分数规则；记录和数据集版本保存在 `verification/agents-live-result.json`。每条 `checks` 记录的 `request` 保存实际 JSON 请求体，`response` 保存 API 输出，可直接对照输入和结果。

输入不合法返回 422，其中请求字段校验失败的 `detail` 是 `[{type,loc,msg}]` 数组，输入/上下文超限时是字符串；模型不可达返回 503；模型推理超时返回 504；上游错误、响应截断或输出校验失败返回 502。模型类错误的 `detail` 均为脱敏字符串。

云端回退默认关闭；设置 `LLM_FALLBACK_ENABLED=true` 且配置非空 `LLM_FALLBACK_API_KEY` 后才启用。设为 `false` 可保留密钥并禁止回退，总预算恢复为 `LLM_TIMEOUT_SECONDS`。启用后，本地 Ollama/vLLM 的模型调用因连接失败、超时或上游 HTTP 错误抛出异常时，本次调用改用回退模型重试一次，两次尝试的总预算为 `LLM_TIMEOUT_SECONDS + LLM_FALLBACK_TIMEOUT_SECONDS`。回退只覆盖模型调用失败，不重试已返回但未通过 Schema 校验的输出；`/ready` 仍只检查本地模型。回退模型若为 DeepSeek，`ProviderStrategy` 的严格 `json_schema` 请求会降级为 `json_object`，响应仍由 LangChain 解析并由 Pydantic 严格校验。启用回退会把本次请求内容发送到云端，需按数据合规要求评估。

后台服务修改代码后，重启 API 即可，模型服务可继续复用：

```zsh
zsh scripts/dev/services.sh restart-api
```

Linux 上线请使用 [部署脚本说明](../scripts/README.md)中的 `scripts/prod/` 入口，并由服务管理器重启 API。
