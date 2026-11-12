# 功能与接口覆盖清单

更新日期：2026-11-12。当前 10 个 HTTP 操作全部进入用户已批准的
[完整正式契约](openapi/fastapi.openapi.json)，均为 `confirmed`。

| 能力 | 方法与路径 |
| --- | --- |
| 进程存活 | `GET /health` |
| 模型就绪 | `GET /ready` |
| 本地依赖诊断 | `GET /diagnostics` |
| 工程日志总结 | `POST /agents/log-summary` |
| 业务端意图识别 | `POST /agents/intent/business` |
| 归档端意图识别 | `POST /agents/intent/archive` |
| 自由对话 | `POST /agents/chat` |
| 监理日记完整处理 | `POST /ocr/journal` |
| 监理日记纯 OCR | `POST /ocr/journal/recognize` |
| 监理日记业务生成 | `POST /ocr/journal/process` |

监理日记三个操作另有 [正式子契约](openapi/journal.openapi.json)，继续独立校验。
`process` 接收 `recognize` 响应的 `data`，支持人工校对后生成；
`journal` 与 `process` 均输出 `code/message/data/jsonData`，`recognize` 输出 `status/message/data`。

`/diagnostics` 只做本地静态检查，`data.ok=false` 时仍返回 HTTP 200。
接口字段、错误语义和约束见 [API.md](API.md)，本表不重复维护字段。

历史 `/ocr/daily-logs-new` 已迁移到 `/ocr/journal`；其他已删除的 OCR/WBS 路由不在本轮批准范围，
恢复这些接口仍需单独设计和审批。移除及迁移记录见 [CHANGELOG](CHANGELOG.md)。

YJH 引入的 `POST /ocr/jianbiao` 为第 11 个操作，保留其简表识别链、模板和输出能力，契约状态为 `pending-review`；详情见 [草案](drafts/fastapi.openapi.json)。

本轮只确立契约基线，不新增认证、持久会话、异步任务、流式响应或外部业务动作。
调用方历史观察见 [consumers.md](guides/consumers.md)，不能替代外部仓库的实时确认。
