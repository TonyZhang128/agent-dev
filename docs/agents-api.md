# 三个业务智能体 API

服务地址：`http://127.0.0.1:8309`。交互文档：`http://127.0.0.1:8309/docs`。

开发期可通过 frp 使用公网地址 `https://107.182.190.191:8443` 联调，接口路径和 JSON 请求/返回与本地一致；该能力仅用于开发环境，Linux 生产部署不包含 frp。公网访问无需账户、密码、API key 或 `Authorization` 请求头，HTTPS 使用私有 CA，客户端需配置 CA 证书信任，具体示例见 [frp 公网接入（仅开发）](frp.md)。`user_id`、`session_id` 仍是必填业务标识，不是登录凭据。

| 业务 | 方法与路径 | 模块 |
| --- | --- | --- |
| 总结并生成工作日志 | `POST /agents/log-summary` | `app/agents/log_summary.py` |
| 意图识别 | `POST /agents/intent` | `app/agents/intent.py` |
| 自由对话 | `POST /agents/chat` | `app/agents/chat.py` |

当前版本 `0.3.0`。三个智能体均通过 LangChain `create_agent()` 执行，共享 `app/llm.py` 的 `ChatOpenAI` 模型工厂和 `.env` 配置。日志总结、意图识别使用 `ProviderStrategy` 和 JSON Schema 约束生成，最后经过 Pydantic 校验；对话返回普通文本，再包装为 JSON。接口只处理传入内容，不执行外部业务操作，不将用户消息保存为服务端会话。

## 用户与会话请求契约

三个业务接口均要求非空字符串 `user_id`、`session_id`，去除首尾空白后各1–128字符。`/intent` 和 `/chat` 还必须传 `history`（首轮为 `[]`）；日志总结不接受该字段。旧请求缺少这些必填字段将返回422，成功响应结构不变；业务接口路径已统一为 `/agents/...`，不再使用 `/api/agents` 前缀。完整示例、并发隔离、裁剪规则和身份信任边界见 [用户与会话](sessions.md)。

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

根据用户输入识别想要进入的页面，或识别为问候、闲聊及一般交流。`text` 为待识别文字，最多 2000 字符。始终使用以下五个固定类别，`intents` 只能省略或为 `[]`：

| 标签 | 类别 | 输入示例 |
| --- | --- | --- |
| `work_list` | 工作列表 | 打开工作列表；我今天有哪些待办任务 |
| `supervision_log` | 监理日志页面 | 进入监理日志；我要填写今天的监理日记 |
| `image_library` | 图片库 | 打开图片库；看看施工现场照片 |
| `business_management` | 业务管理页面 | 进入业务管理页面；带我去办理业务 |
| `chat` | 问候、闲聊或一般交流 | 你好；谢谢；监理日志是什么 |

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/intent \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"example-user","session_id":"example-session","history":[],"text":"你好，帮我打开图片库"}'
```

返回结构示例：

```json
{
  "intent": "image_library",
  "confidence": 0.95,
  "reason": "用户明确要求进入图片库查看图片。",
  "needs_clarification": false
}
```

只有明确的页面或页面功能诉求才归入对应页面。问候夹带导航时优先识别页面；否定和改口以最终明确目标为准，例如“不要图片库，打开工作列表”返回 `work_list`。解释概念或一般问答归入 `chat`，不能只因提及“监理日志”就触发导航。

固定输出接口的 [字段说明、JSON Schema 和配对输入输出示例](../interfaces/intent/README.md) 位于 `interfaces/intent/`。四个响应字段全部必填且禁止额外字段；Schema 与 `IntentResult` / OpenAPI 一致，固定枚举为上述五类标签及兜底 `unknown`。`response.examples.json` 仅保存五类主示例，`response.fallback.examples.json` 单独保存兜底示例。

`unknown` 是五类之外的兜底结果，不是第六个业务类别。目标含糊、多个页面无法确定唯一目标、不支持的页面，或无法匹配的业务指令均返回 `unknown`，不会强行归入 `chat` 或业务管理。例如“打开系统设置页面”“工作列表和图片库没想好先去哪一个”。模型判断分数低于 `0.65` 或需要澄清时，也返回 `intent: "unknown"`、`needs_clarification: true`。`confidence` 是模型判断分数，不是经过校准的概率；恰好 `0.65` 且不需澄清的有效标签可以保留。

调用方将四个页面标签映射到自己的路由；服务不执行跳转。有效分类为 `chat` 时，服务将原始 `text` 作为 `ChatRequest.message` 调用 `ChatAgent`，将其 `reply` 写入 `reason`，保留分类分数及澄清标记，调用方直接展示 `reason`。用户ID、会话ID及完整历史都会传给 ChatAgent。此接口接收当前用户当前会话的完整历史，识别与聊天各自按上下文预算裁剪；不保存服务端历史。低分或需澄清的结果先回退为 `unknown`，不调用聊天；`unknown` 应提示用户澄清。

例如输入 `{"text":"你好"}`，响应可以是：

```json
{
  "intent": "chat",
  "confidence": 0.95,
  "reason": "你好！有什么可以帮你？",
  "needs_clarification": false
}
```

`chat` 需要分类和聊天两次模型调用，共享 `LLM_TIMEOUT_SECONDS` 总超时。聊天失败沿用 `503`（不可达）、`504`（超时）、`502`（上游错误或无效回答），不会将分类理由作为成功回答返回。内部分类使用 `IntentClassification` 的严格 JSON Schema，分类理由始终限300字符；最终响应使用 `IntentResult` 校验，`chat` 的 `reason` 不受300字符限制且不做截断，其他标签仍保留该限制。

已取消自定义分类。为兼容已有的空字段请求，保留可选 `intents`，但只能省略或为 `[]`；任何非空列表均返回 `422`，即使其中使用的是当前五类标签，也不允许覆盖或缩减分类。模型不会收到调用方自定义候选。

四个响应字段保持不变，接口路径已由 `/api/agents/intent` 调整为 `/agents/intent`；请求不再接受非空 `intents`，响应 `intent` 的 JSON Schema 和 Pydantic 类型固定为上述五类及 `unknown`。旧调用方应去掉自定义候选并更新标签映射；模型返回集合之外的标签视为非法输出，返回 `502`。测试及真实评测标准见 [意图识别测试说明](intent-testing.md)。

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

业务规则在 `app/agents/`，系统提示词在 `app/prompts/`，请求及返回类型在 `app/schemas.py`，HTTP 路由在 `app/api/agents.py`、`system.py`，由 `app/api/router.py` 聚合、`app/main.py` 注册。`main.py` 保留应用工厂和共享资源生命周期；`app/http_errors.py` 注册原有全局异常处理器。`app/agents/base.py` 提供对话和结构化业务共用的 `BaseAgent`，以及带 Schema 和结果校验的 `StructuredAgent`；`runtime.py` 统一创建和调用 LangChain Agent，`middleware.py` 检查异常模型响应，`app/llm.py` 负责 OpenAI 兼容模型适配。新增业务的步骤见 [README](../README.md#项目结构与-agent-开发)。

```zsh
# 在项目根目录执行：
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked pytest -v
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python -m scripts.common.verify_agents
```

真实测试覆盖日志文字与 JSON 输入、`data/intent.json` 的完整版本化评测集、普通对话及携带历史的对话。意图逐条比对标签、澄清标记及分数规则；记录和数据集版本保存在 `verification/agents-live-result.json`。每条 `checks` 记录的 `request` 保存实际 JSON 请求体，`response` 保存 API 输出，可直接对照输入和结果。

输入不合法返回 422；模型不可达返回 503；模型推理超时返回 504；上游错误、响应截断或输出校验失败返回 502。

后台服务修改代码后，重启 API 即可，模型服务可继续复用：

```zsh
zsh scripts/dev/services.sh restart-api
```

Linux 上线请使用 [部署脚本说明](../scripts/README.md)中的 `scripts/prod/` 入口，并由服务管理器重启 API。
