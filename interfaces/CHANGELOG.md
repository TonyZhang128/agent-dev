# 接口契约变更记录

只记录对外接口契约的变化。运行时行为、提示词和内部重构不在此记录。

## 2026-11-12 — 算法服务名称统一（用户已确认）

- 用户确认完整服务名称“公路工程智能算法服务”、简称“算法服务”，程序／容器标识为 `agent-service`；项目标题“公路工程业务智能体层”保留。
- OpenAPI `info.title` 从“公路工程业务智能体”调整为“公路工程智能算法服务”，草案介绍文字同步；版本保持 `0.1.0`，不变更路径、方法、请求／响应字段、状态码或业务语义。
- 本次命名确认不代表整包 OpenAPI 草案已获批准；已有响应子契约保持不变。

## 2026-11-08 — mainWork 规则优先、全文生成兜底（用户已确认）

- 用户明确允许整理表达、合并断句和去标题，但要求保留全部业务事实与关键数据，不摘要、不补充事实。
- 先从合并后的mainWork按施工情况、旁站情况、巡视情况关键词提取；规则不足时由Agent基于全文直接生成三个字段，不再返回unit_id分类计划。
- 替代旧版逐字分配及保留标题要求，正式行为依据见 `journal/main-work-processing.md`。输出字段/类型、请求及mainWork之外字段不变；标题可能不再出现在值中。
- 保留现有table失败400及mainWork失败502，空/不存在类别仍可为null，不承诺模型故障或不可辨输入也产生虚构成功。

## 2026-11-07 — 监理日记无可靠表格时终止（用户已确认）

- 用户明确回复“同意，按上述 400 语义执行”。`POST /ocr/daily-logs-new` 无通过模板结构核验的 table，或无法消解多个候选时，在 OCR 和 mainWork 分类之前终止。
- 返回 HTTP `400` 和 `{"detail":"未检测到监理日志表格，请重新拍摄"}`，正式响应子契约为 `journal/table-not-found.schema.json`。
- 删除纸张/整图回退以及定位失败后的空字段200；真实合法空白表格仍可成功返回空字段。
- 成功 Schema、请求、taskId 和既有 mainWork 拆分失败502不变；调用方需对新增400条件提示重新拍摄。本确认不提升无关接口或整包OpenAPI。

## 2026-11-07 — 草案移除未启用的 OCR/WBS 接口（用户已确认）

- 从待确认草案中移除 `POST /ocr/recognize`、`POST /ocr/daily-logs`、
  `POST /ocr/jianbiao`、`POST /ocr/fill`、`GET /ocr/blank/{form}.png`、
  `GET /ocr/sheet/{form}` 与 `POST /wbs/draft`；实现代码已删除，对应入口在
  `app/api/ocr.py` 中保留为注释，`app/api/wbs.py` 已移除。
- 保留 `POST /ocr/daily-logs-new`、`/diagnostics` 及智能体接口，行为与状态不变。
- 这些接口此前均为 `pending-review`，从未提升为正式契约；本次只同步草案、实现与
  测试，不涉及已确认契约的破坏性变更。
- 调用方影响：仍调用上述已移除接口的客户端会收到 404；需要这些能力时应重新提交
  接口草案并完成审批，不能直接恢复路由。
- 同时移除了仅被这些接口引用的组件 Schema，避免草案保留不可达模型。

## 2026-11-07 — 新版监理日志 mainWork 字段拆分（待确认）

- `POST /ocr/daily-logs-new` 的 `data.fields.mainWork.construction`、`witness`、
  `patrol` 由“整段 `mainWork` 同时回填”改为“按业务含义拆分后的原文”。
  这是行为变化，已随 `docs/journal-mainwork-split.md` 方案确认。
- 成功响应结构不变：仍严格为 `status`、`message`、`data`，不新增原始 `mainWork`、
  未分类内容或复核状态字段；`interfaces/journal/response.schema.json` 不变。
- 字段值只从本次 `mainWork` OCR 文本原样截取，保留各节标题；原文没有的类别为
  `null`；不改动 `common`、`issues`、`nextDayPlan`。
- 新增失败语义：模型与标题规则都无法可靠完成时返回 `502`，`detail` 为固定文案，
  不回显原文、OCR 内容、单元 ID 或上游错误正文。
- 操作仍为 `pending-review`，未提升为正式契约。
- 调用方影响：原来读取三个相同整段值的调用方需要按类别读取；同一字段可能为
  `null`；需要处理新增的 `502`。

## 2026-11-06 — 新版监理日志成功响应对齐后端约定（用户已确认）

- 用户指定 `data/ocr/resources/daily-logs-output.json` 为 `POST /ocr/daily-logs-new`
  的成功响应格式；已确认的响应子契约保存在 `journal/response.schema.json`。
- 顶层严格为 `status`、`message`、`data`，成功值为 `200`、`识别完成`；原
  `data.processed` 的业务字段直接放到 `data`，不返回 `form`、`formName`、`frame`、
  `recognized`、`detail`、`processed`、`warning`、`image`、`ms`。
- `data` 严格包含 `taskId`、`documentType`、`common`、`fields`；缺失值保留为
  `null`，`mainWork` 整段暂时回填三个子字段的规则不变。
- 调用方直接读取 `data.common` 和 `data.fields`，不再读取 `data.processed`。
  本次只确认新版接口的成功响应，未批准整包 OpenAPI；旧接口和错误响应保持原约定。

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
