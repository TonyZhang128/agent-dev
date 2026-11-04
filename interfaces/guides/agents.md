# 智能体接口说明

本文说明 `/agents/*` 的业务流程、会话规则、超时和错误处理。请求与响应字段以
[OpenAPI 草案](../drafts/fastapi.openapi.json) 的 `LogSummaryRequest`、`LogSummary`、
`BusinessIntentRequest`、`BusinessIntentResult`、`ArchiveIntentResult`、`ChatRequest`、
`ChatResponse` 为准。已确认的固定响应结构另见 [日志总结](../log_summary/README.md)、
[业务端意图](../intent/README.md)、[归档端意图](../intent/archive/README.md)。

## 调用方式

- 全部为同步 `POST`，一次请求内完成模型调用并返回完整结果。
- 没有流式响应、任务 ID、轮询、webhook 或服务端会话存储。
- `user_id`、`session_id` 是业务标识，不是认证凭据。
- `content`、`text`、`message` 为本次输入；`history` 是当前用户当前会话的完整历史，
  不包含本次输入。
- 业务意图还接收 `current_page`、`last_navigation` 和 `pending_clarification`；本服务不保存
  会话状态，由调用方每次传入并在响应后持久化。
- 服务只处理传入内容，不执行页面跳转、审批、订单修改、通知发送或数据库写入。

## 请求校验与历史

| 接口 | 当前输入 | 历史 |
| --- | --- | --- |
| `POST /agents/log-summary` | `content`：文字或 JSON 对象 | 不接受；携带 `history` 返回 422 |
| `POST /agents/intent/business` | `message`、`current_page`；可选 `last_navigation`、`pending_clarification` | 可选 `history`，省略即 `[]` |
| `POST /agents/intent/archive` | `text` 加 `intents` 空字段 | 必填 `history`，首轮 `[]` |
| `POST /agents/chat` | `message` | 必填 `history`，首轮 `[]` |

- 需求模型拒绝额外字段。
- `history` 只接受完整、交替的 `user` / `assistant` 回合，以 `user` 开头、`assistant`
  结束；拒绝调用方 `system` 消息。
- 服务按每次请求的上下文预算裁剪最早的完整回合，保留当前输入和系统提示词；不修改调用方
  原始历史，不恢复旧的 10 条或 4000 字符会话限制。
- 完整输入仍受 `CONVERSATION_MAX_INPUT_CHARACTERS` 限制；超限返回 422。
- UTF-8 字节估算是保守预算，不是精确 tokenizer。裁剪规则和信任边界详见
  [用户与会话](../../docs/sessions.md)。

## 日志总结流程

1. 校验 `content` 非空，序列化后不超过 4000 字符；字符串按去空白后的长度计算。
2. 使用结构化输出 Schema 约束模型生成 `title`、`date`、`summary`、
   `completed_items`、`pending_items`、`issues`。
3. Pydantic 再次严格校验；缺失字段、额外字段或类型不符视为非法输出。

语义规则：保留原始事实、数值、单位和记录结论；不换算实测值，不虚构日期、成果、任务或
合格结论；只有明确完成/待办/问题才进入对应数组。模型可能出错，调用方仍需业务核对。
规则和验收方法见 [日志总结测试说明](../../docs/log-summary-testing.md)。

## 意图识别流程

### 业务端

1. 页面（一级）和功能（二级）编码来自 `app/resources/intent/business_pages.json`；构建期
   生成枚举，运行时不读取 JSON。模型只能输出目录内编码。
2. 一次推理输出 `kind`、`page`、`action`、`confidence`、`reason` 和
   `needs_clarification`，服务再归一为以下状态：
   - 能确定具体二级功能且分数不低于 `0.65`：`status="resolved"`，必须带 `page` 和 `action`。
   - 只确定一级模块、同页多个动作无法确定、分数低于 `0.65` 或模型要求澄清：
     `status="clarify"`，返回 `page`、`action=null`、`message` 和目录生成的 `options`。
   - 问候、闲聊或概念问答：`status="chat"`，调用共享 ChatAgent，`message` 为回答。
   - 目录外任务、跨页面冲突或信息不足：`status="unknown"`，`page`/`action` 为 `null`。
3. `clarify` 时服务调用 Chat 澄清模式，只允许围绕 `options` 措辞。调用方保存
   `pending_clarification.page` 和 `attempts`，每次 `clarify` 后将 `attempts` 加 1；同一页面
   达到 10 轮仍不明确时返回 `unknown`。Chat 澄清失败时返回 HTTP 200 的确定性选项文案。
4. 分类和聊天/澄清推理共享总超时。非法编码、`action` 不属于 `page` 或结构不合法返回 `502`。
5. 本服务不返回 `navigation_id`，不跟踪前端跳转成功与否；调用方按 `page/action` 映射路由。

### 归档端

- 使用独立 profile，固定 `A`、`B`、`C`、`D` 占位分类加 `unknown`。
- 没有 `chat` 分类；问候或一般交流返回 `unknown`，不触发聊天。
- 请求、历史、阈值和回退规则与业务端一致。
- `A`–`D` 的真实业务含义尚未确定，调用方不应据此实现最终归档路由。

## 自由对话流程

- 使用当前 `message` 和调用方提供的完整 `history` 调用共享 ChatAgent。
- 返回完整 `reply` 和实际 `model` 名称；不使用流式响应。
- 服务不保存回复。多轮对话由调用方在下一轮把本轮问答加入 `history` 后传回。
- 不同请求之间不共享消息、执行状态或历史，即使 `user_id`、`session_id` 相同。

## 超时、回退与错误

| HTTP 状态 | 场景 | 响应 |
| --- | --- | --- |
| 200 | 成功 | 对应响应对象 |
| 422 | 请求字段、类型、枚举、历史格式或输入上限不合法 | `{"detail":[{type,loc,msg}]}` 或 `{"detail":"..."}` |
| 502 | 上游模型返回错误、输出截断、空输出、未通过 Schema/Pydantic 校验，或业务意图返回目录外编码 | `{"detail":"..."}` |
| 503 | 模型服务不可达 | `{"detail":"模型服务不可达，请检查 Ollama/vLLM"}` |
| 504 | 模型推理超时 | `{"detail":"模型推理超时"}` |

- 默认总超时为 `LLM_TIMEOUT_SECONDS`。
- 配置非空 `LLM_FALLBACK_API_KEY` 后，本地模型连接失败、超时或上游 HTTP 错误会改用回退
  模型重试一次；两次尝试的总预算为 `LLM_TIMEOUT_SECONDS + LLM_FALLBACK_TIMEOUT_SECONDS`。
- 回退只覆盖模型调用失败，不重试已返回但未通过校验的输出。
- 启用回退会把本次请求内容发送到云端，必须按数据合规要求评估。
- `/ready` 仍只检查本地模型，不代表回退模型可用。
- 错误响应统一脱敏，不泄露密钥、原始输入、身份、历史或上游错误正文。

## 重试建议

- 429/502/503/504 和网络错误可以退避重试；422 不应重试，应先修正请求。
- 同一输入可能生成不同措辞或回答，重试前应确认业务是否接受。
- `/agents/intent/business` 的 `chat` 或 `clarify` 可能触发两次模型调用，超时预算按整体计算。
