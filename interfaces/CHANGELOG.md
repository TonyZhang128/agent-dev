# 接口契约变更记录

只记录对外接口契约的变化。运行时行为、提示词和内部重构不在此记录。

## 2026-11-02 — intent-business 层级意图改造（用户已确认）

- 业务端意图接口由 `POST /agents/intent` 替换为 `POST /agents/intent/business`；
  旧路径不再注册。当前没有旧调用方，不做兼容别名。
- 请求改为必填 `user_id`、`session_id`、`message`、`current_page`；可选 `history`、
  `last_navigation`、`pending_clarification`、`request_id`。移除 `text` 和非空
  `intents` 兼容字段。
- 响应由四字段 `intent/confidence/reason/needs_clarification` 改为七字段
  `status/page/action/confidence/message/options/catalog_version`。
- 新增 `resolved`、`clarify`、`chat`、`unknown` 四种状态；仅 `resolved` 要求 `action`。
- 一级意图调用 Chat 澄清模式；调用方传入 `pending_clarification.attempts`，最多 10 轮。
- 页面与二级功能编码由 `app/resources/intent/business_pages.json` 派生；
  `catalog_version` 为 JSON 内容哈希。
- 归档端 `POST /agents/intent/archive` 和自由对话 `POST /agents/chat` 契约不变。

## 2026-11-02 — 0.1.0-review.1（第一版评审稿，待确认）

- 将完整 OpenAPI 草案整理为第一版评审稿，补充中文操作摘要。
- 新增由契约自动生成的 `interfaces/API.md`，用于人工审阅；它不是独立契约。
- 契约状态仍为 `draft-pending-review`，8 个 OCR/WBS 操作仍为 `pending-review`，未提升为正式契约。
- 未修改任何运行时接口。

## 2026-11-02 — 0.1.0-draft.1（待确认）

- 建立 `interfaces/openapi/`、`interfaces/drafts/`、`interfaces/guides/` 目录和接口清单。
- 从 `app.main:app` 导出 14 个 HTTP 操作的 OpenAPI 3.1 草案。
- 补充 `/health`、`/ready`、`/health/deps`、`/ocr/*`、`/wbs/draft` 的成功响应 Schema。
- 补充统一错误响应：422 `RequestError`，400/404/502/503/504 `ErrorDetail`。
- 为每个操作记录契约状态、来源、副作用和幂等说明。
- 将 `/health/deps`、`/ocr/*`、`/wbs/draft` 标记为 `pending-review`，等待用户确认。
- 未修改任何运行时接口、请求字段、响应字段或状态码。
- 未将草案提升为正式契约。

批准后将新增 `0.1.0`（confirmed）记录，并保留本草案记录。
