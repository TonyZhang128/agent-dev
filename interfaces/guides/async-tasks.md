# 同步调用、异步任务与重试

## 当前没有异步任务接口

截至 2026-11-02，本服务没有：

- 任务提交接口。
- 任务 ID、任务状态、进度查询或轮询接口。
- 回调、webhook 或消息队列。
- 任务取消、暂停、恢复或删除接口。
- 后台任务持久化、重试队列或死信队列。

所有 HTTP 请求同步完成并直接返回结果。状态码和响应体就是本次调用的最终结果，不存在
“已受理”状态。调用方不应自行假设 `202 Accepted`、`job_id`、`status_url` 等字段。

## 调用方超时

本服务没有统一的 HTTP 请求超时配置；不同操作的实际耗时差异很大：

- `/health`、`/ready`、`/health/deps`：通常很快，但 `/ready` 依赖模型服务响应。
- `/agents/*`：受 `LLM_TIMEOUT_SECONDS` 和可选回退预算约束；`/agents/intent/business` 的
  `chat` 或 `clarify` 可能包含两次模型调用。
- `/ocr/recognize`、`/ocr/daily-logs`：首次调用可能需要加载 OCR 模型。
- `/ocr/jianbiao`、`/ocr/fill`、`/wbs/draft`：涉及多页 PDF、Excel 或大图处理，可能明显
  更慢。

调用方应按操作设置超时，不要用一个很短的全局超时覆盖所有接口。当前 Java 调用方对
`/ocr/jianbiao` 和 `/ocr/recognize` 使用 2 分钟，对 `/wbs/draft` 使用 5 分钟，对
`/ocr/sheet`、`/ocr/blank`、`/ocr/fill` 使用 30 秒；这些是调用方选择，不是服务端契约。

## 重试

- 只读接口可以重试：`GET /health`、`/ready`、`/health/deps`、
  `/ocr/sheet/{form}`、`/ocr/blank/{form}.png`，以及不写文件的
  `/ocr/recognize`、`/ocr/daily-logs`、`/ocr/jianbiao`、`/ocr/fill`、`/wbs/draft`。
- `/ocr/jianbiao`、`/ocr/fill` 在 `out` 非空时会写同名 PDF/Excel/校正图；相同 `out`
  重试会覆盖已有输出。当前没有幂等键，调用方应在重试前确认覆盖是否符合业务要求。
- 模型和 OCR 推理可能产生不同结果；重试成功不代表与首次结果逐字一致。
- 400、404、422 通常不应原样重试；应先修正路径、配置或请求结构。
- 502、503、504 和网络错误可以退避重试；仍失败时应向用户报告，不得伪造成功结果。

## 并发

- 不同请求的消息、元数据、执行状态和结果相互隔离。
- 同一应用的 OCR 推理串行加锁；并发 OCR 请求可能排队。
- 模型端是否并行生成取决于 Ollama/vLLM 部署配置；Mac 默认单推理并发。
- 同一 `user_id`、`session_id` 的并发请求不会自动合并、排序或恢复历史。

## 将来引入异步任务的约定

如确需异步化，必须先按 API-First 流程提交草案并获批，至少明确：

- 提交接口、任务 ID 和查询接口。
- 状态机及状态转换（例如 queued/running/succeeded/failed/cancelled）。
- 超时、重试、幂等键、并发限制和结果保留期限。
- 失败结果的错误码与脱敏规则。
- 是否需要持久化、回调或 webhook，以及相应的认证和重放保护。

在获批并实现前，不得在文档或客户端中把上述能力描述为已存在。
