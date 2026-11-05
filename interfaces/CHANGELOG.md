# 接口契约变更记录

只记录对外接口契约的变化。运行时行为、提示词和内部重构不在此记录。

## 2026-11-05 — 监理日记新版识别链路（待确认）

- 新增 `POST /ocr/daily-logs-new`，作为新版监理日志识别链路的独立入口；
  请求字段与 `/ocr/daily-logs` 相同（`path`、`img`、可选 `taskId`），成功响应沿用
  `DailyLogsResponse` 结构，未新增或删除响应字段。
- 新链路在照片上直接定位表格、只做一次透视校正和一次整页 OCR，再按固定栏目匹配；
  歧义或漏框字段最多补充识别 3 次。旧的 `/ocr/daily-logs` 与其实现保持不变。
- 样例表中 `construction`、`witness`、`patrol` 同属一个 `mainWork` 单元格；当前只
  整格识别 `mainWork`，`recognized`、`detail` 和 `processed` 中的这三个字段暂时取
  同一个整段值，后续再按印刷小标题拆分。响应字段结构不变。
- 操作状态为 `pending-review`；未提升为正式契约。
- 调用方影响：新增接口，现有调用方不受影响；启用新链路需显式改调用路径。

## 2026-11-05 — 监理日记业务结构（用户已确认）

- `POST /ocr/daily-logs` 的 `processed` 由固定 `{}` 改为业务结构：
  `taskId`、`documentType`（固定 `supervision_diary`）、`common`、`fields`；
  识别不到的栏目为 `null`，不做推断。
- 请求新增可选 `taskId`（最长 128，去除首尾空白），仅原样回显到 `processed.taskId`；
  服务仍不生成任务 ID。
- 识别栏目按现场《监理日记》表样重标定：`recognized` 新增 `position`、`witness`、
  `patrol`、`next_day_plan`，移除 `supervision_work`。
- 响应包装仍为 `{"status":200,"data":...}`，未新增 `message`；`form`、`frame`、
  `detail`、`warning`、`image`、`ms` 保持不变。
- 操作仍为 `pending-review`，未提升为正式契约。
- 调用方影响：未使用 `processed` 的调用方不受影响；使用 `supervision_work` 的调用方
  需改用 `witness`/`patrol`。

## 2026-11-04 — 0.1.0-review.2（diagnostics 端点，用户已确认）

- `GET /health/deps` 更名为一级路由 `GET /diagnostics`，归入系统级接口；旧路径不再注册，
  仍为 `pending-review` 操作。
- 响应新增 `data.warnings` 和 `caps["OCR 资源"]`；`caps["推理设备"]` 增加 `configured`、
  `device`、`runtime`、`note`，`ok` 改为配置设备与 onnxruntime provider 的一致性检查。
- `/diagnostics` 只做本地静态检查：不初始化 OCR 引擎、不加载模型、不注册 CUDA DLL、
  不访问网络、不写文件；`data.ok=false` 时仍返回 HTTP 200。
- `/health`、`/ready` 契约不变。
- 已知调用方影响：Java `DocsvcClient` 原调用 `/health/deps`，必须同步改为 `/diagnostics`。

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
