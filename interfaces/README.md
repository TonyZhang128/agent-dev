# 接口文档

`interfaces/` 统一管理供其他系统对接的 HTTP 接口文档。接口契约优先（API-First）规则见
[AGENTS.md 第四节](../AGENTS.md#四接口契约与-api-first-开发流程)。

## 当前状态

截至 2026-11-04：

- 已实现的 14 个 HTTP 操作全部有文档，没有凭空描述尚未实现的接口。
- `/agents/*`、`/health`、`/ready` 的既有契约由 `AGENTS.md`、`docs/agents-api.md`、
  `docs/sessions.md` 和自动化测试共同保护，标记为 `confirmed`。
- `/diagnostics`、`/ocr/*`、`/wbs/draft` 已有实现和专题文档，但此前没有机器可读的完整
  响应/错误契约；本次归纳为 **待确认草案**，标记为 `pending-review`。
  `/diagnostics` 由原 `/health/deps` 更名并提升为一级路由。
- 完整 OpenAPI 草案位于 [drafts/fastapi.openapi.json](drafts/fastapi.openapi.json)。
  **它不是正式契约，不能作为接口变更授权。** 用户批准后才能提升到 `openapi/`。
- 当前评审稿版本为 `0.1.0-review.2`，评审文档位于 [API.md](API.md)，由 OpenAPI 自动生成，
  便于直接审阅；它不是独立契约，也不能替代 OpenAPI。
- 三个已发布的固定输出 Schema 仍是对外响应子契约：
  [日志总结](log_summary/README.md)、[业务端意图](intent/README.md)、
  [归档端意图](intent/archive/README.md)。

## 权威来源

1. 用户明确批准的正式契约：`interfaces/openapi/` 中的文件（当前尚无整包正式契约）。
2. 已确认的响应子契约：`interfaces/log_summary/`、`interfaces/intent/` 下的 JSON Schema。
3. 待确认草案：`interfaces/drafts/`。用于评审，不能用于授权实现变更。
4. 运行时 FastAPI 生成的 `/openapi.json`、`/docs`：实现的投影，便于调试；
   **不得**用自动生成结果覆盖正式契约。
5. `docs/`：实现细节、测试方法和专题说明，不替代 `interfaces/` 的对外契约。

代码与正式契约不一致时，必须先报告差异并由用户决定修代码还是改契约，不能默认以代码为准。

## 目录

```text
interfaces/
├── README.md                  # 本文件：全局规范、接口清单、使用方式
├── API.md                     # 由 OpenAPI 自动生成的第一版评审文档
├── coverage.md                # 功能-接口覆盖、调用方和差异清单
├── CHANGELOG.md               # 契约变更记录
├── openapi/
│   └── README.md              # 正式契约目录；批准后放 fastapi.openapi.json
├── drafts/
│   ├── README.md              # 待确认事项和批准流程
│   └── fastapi.openapi.json   # 从当前实现归纳的完整 OpenAPI 草案
├── guides/
│   ├── agents.md              # 智能体业务流、会话、超时与错误
│   ├── ocr.md                 # OCR/填表/WBS 业务流、路径和输出
│   ├── async-tasks.md         # 同步语义、无异步任务、重试与幂等
│   └── consumers.md           # Java/前端调用方观察结果
├── log_summary/               # 已确认的日志响应 Schema 与示例
└── intent/                    # 已确认的意图响应 Schema 与示例
    └── archive/               # 归档端响应 Schema 与示例
```

## 契约状态

| 状态 | 含义 | 能否据此实现 |
| --- | --- | --- |
| `confirmed` | 用户已确认，或由仓库既有强制规则和测试保护 | 只能按现有契约实现，变更需审批 |
| `pending-review` | AI 归纳或设计，等待用户确认 | 不得据此新增或修改对外行为 |
| `deprecated` | 已宣告废弃但尚未删除 | 不得新增调用；删除需审批 |

每个 OpenAPI 操作都带 `x-contract-status`、`x-contract-source`、`x-side-effects` 和
`x-idempotency`，便于审查。

## 接口清单

| 业务 | 方法与路径 | 状态 | 主要资料 |
| --- | --- | --- | --- |
| 进程存活 | `GET /health` | confirmed | [OpenAPI 草案](drafts/fastapi.openapi.json) |
| 模型就绪 | `GET /ready` | confirmed | [agents-api](../docs/agents-api.md) |
| 工程日志总结 | `POST /agents/log-summary` | confirmed | [日志接口](log_summary/README.md) |
| 业务端意图识别 | `POST /agents/intent/business` | confirmed | [意图接口](intent/README.md)、[智能体指南](guides/agents.md) |
| 归档端意图识别 | `POST /agents/intent/archive` | confirmed | [归档接口](intent/archive/README.md) |
| 自由对话 | `POST /agents/chat` | confirmed | [智能体指南](guides/agents.md) |
| 本地依赖诊断 | `GET /diagnostics` | pending-review | [OCR 指南](guides/ocr.md) |
| 普通照片/简表识别 | `POST /ocr/recognize` | pending-review | [OCR 指南](guides/ocr.md) |
| 监理日志识别 | `POST /ocr/daily-logs` | pending-review | [OCR 指南](guides/ocr.md) |
| 简表识别与填表 | `POST /ocr/jianbiao` | pending-review | [OCR 指南](guides/ocr.md) |
| 公式与填表 | `POST /ocr/fill` | pending-review | [OCR 指南](guides/ocr.md) |
| 表样预览 | `GET /ocr/blank/{form}.png` | pending-review | [OCR 指南](guides/ocr.md) |
| 表样栏目 | `GET /ocr/sheet/{form}` | pending-review | [OCR 指南](guides/ocr.md) |
| 施工图划分 | `POST /wbs/draft` | pending-review | [OCR 指南](guides/ocr.md) |

完整字段以 OpenAPI 草案的 `components/schemas` 为准；本目录的 Markdown 只说明业务流程、
状态转换、超时、重试、路径限制等 OpenAPI 不易表达的内容，不重复维护字段表。

## 通用约定

- 编码：JSON 请求与响应均为 UTF-8；`Content-Type: application/json`。
- 认证：当前应用没有自定义认证、授权、租户隔离或 CORS 配置。`user_id`、`session_id`
  只是业务标识，不是登录凭据。生产暴露时必须由部署边界或前置网关负责认证。
- 响应包装：
  - `/agents/*` 直接返回业务对象，没有 `data` 包装。
  - `/health`、`/ready` 返回 `{"status":"ok"}` / `{"status":"ready"}`。
  - `/diagnostics`、`/ocr/*`（PNG 除外）、`/wbs/draft` 返回
    `{"status":200,"data":...}`；`status` 是业务成功标记，不是 HTTP 状态码替代品。
  - `GET /ocr/blank/{form}.png` 返回原始 `image/png`。
- 错误：统一为 `{"detail": ...}`。请求校验失败时 `detail` 是错误数组；上下文超限和
  其余业务/模型错误是字符串。错误响应不回显原始输入、身份、历史、密钥或上游正文。
- 文件：没有 multipart 上传接口。`/ocr/recognize`、`/ocr/daily-logs` 接受数据池相对路径
  或 base64；`/ocr/jianbiao` 只接受数据池路径。输入输出不得越过 `PROJECTS_ROOT`。
- 分页：当前没有列表分页接口。
- 异步任务：当前没有任务提交、任务状态、轮询、webhook 或取消接口。所有请求同步完成。
- 流式：`/agents/chat` 返回完整回答，不使用 SSE 或流式响应。

## Swagger UI 与 OpenAPI

运行中的 FastAPI 自带交互文档，数据来自当前实现，适合调试：

```zsh
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8309
# Swagger UI
open http://127.0.0.1:8309/docs
# ReDoc
open http://127.0.0.1:8309/redoc
# 运行时 OpenAPI
curl -fsS http://127.0.0.1:8309/openapi.json
```

运行时 `/docs` 是实现的投影，不是正式契约。评审正式契约时使用
`interfaces/drafts/fastapi.openapi.json` 或批准后的
`interfaces/openapi/fastapi.openapi.json`，可用支持 OpenAPI 3.1 的编辑器、Swagger Editor
或 Redoc 预览。

## 生成与校验

```zsh
# 从当前应用导出待确认草案；脚本拒绝写入 interfaces/openapi/
uv run --locked python -m scripts.docs.export_openapi

# 把契约渲染为评审用 Markdown（interfaces/API.md）
uv run --locked python -m scripts.docs.render_api_markdown

# 比较契约与当前实现；有正式契约时优先检查正式契约，否则检查草案
uv run --locked python -m scripts.docs.check_openapi

# 契约同步测试（同时检查 API.md 是否过期）
uv run --locked pytest tests/test_interfaces_contract.py -v
```

`export_openapi` 只覆盖 `interfaces/drafts/fastapi.openapi.json`。正式契约的提升必须由
用户批准后人工完成，见 [openapi/README.md](openapi/README.md)。

## 新增或修改接口的流程

1. 先检查 `interfaces/openapi/` 是否有正式契约；有则严格按契约实现。
2. 没有正式契约时，先在 `interfaces/drafts/` 提出 OpenAPI 草案，说明路径、方法、请求、
   响应、错误、兼容性和业务影响。
3. 提交用户确认；未获明确批准前不得实现对外接口，也不得把草案标为 `confirmed`。
4. 批准后先提升正式契约并记录 [CHANGELOG](CHANGELOG.md)，再修改实现、测试和客户端。
5. 完成实现后运行 `scripts.docs.check_openapi` 和契约测试，确认实现与契约一致。

未经批准，禁止为了让代码运行、通过测试或解决前后端不一致而修改正式契约。

## 相关文档

- [API-First 规则](../AGENTS.md#四接口契约与-api-first-开发流程)
- [智能体 API](../docs/agents-api.md)、[用户与会话](../docs/sessions.md)
- [文档加工与 OCR](../docs/ocr.md)
- [覆盖清单](coverage.md)、[变更记录](CHANGELOG.md)、[待确认草案](drafts/README.md)
