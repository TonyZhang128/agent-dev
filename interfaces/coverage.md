# 功能与接口覆盖清单

统计时间：2026-11-02。依据：`app/main.py`、`app/api/`、`app/schemas/`、`app/ocr/`、
`docs/`、`tests/` 以及运行时 `create_app().openapi()`。不包含本仓库外的 Java/前端源码。

## 汇总

| 项目 | 数量 | 说明 |
| --- | --- | --- |
| 已实现 HTTP 操作 | 14 | 见下表，运行时 OpenAPI 与契约测试一致 |
| 已实现且有文档 | 14 | 请求、成功响应、错误和业务流程均有说明 |
| 已有正式机器可读契约 | 3 | 三个已确认的响应子 Schema；完整 OpenAPI 尚无正式批准 |
| 待用户确认的完整 OpenAPI 基线 | 1 | [drafts/fastapi.openapi.json](drafts/fastapi.openapi.json) |
| 待确认操作 | 8 | `/diagnostics`、`/ocr/*`、`/wbs/draft` |
| 已实现但缺少文档 | 0 | 本次补齐 |
| 文档存在但契约未机器化 | 8 | 本次以草案补齐 |
| 已废弃或重复注册 | 0 | 未发现 |
| 业务需要但尚未实现的接口 | 0（当前范围） | 认证、异步、CRUD 等属于未立项能力，不在本次虚构 |

## 功能与接口

| 业务功能 | 方法与路径 | 实现 | 契约状态 | 调用方/备注 |
| --- | --- | --- | --- | --- |
| 进程存活 | `GET /health` | `app/api/system.py` | confirmed | 监控；不访问模型 |
| 模型就绪 | `GET /ready` | `app/api/system.py` | confirmed | 检查模型列表，不推理 |
| 工程日志描述 | `POST /agents/log-summary` | `app/api/agents.py`、`app/agents/log_summary.py` | confirmed | 固定六字段响应 |
| 业务端意图识别 | `POST /agents/intent/business` | `app/api/agents.py`、`app/agents/intent_business.py`、`app/agents/intent_catalog.py` | confirmed | JSON 目录派生 page/action；一级意图调用 Chat 澄清；不跟踪跳转 |
| 归档端意图识别 | `POST /agents/intent/archive` | `app/api/agents.py`、`app/agents/profiles.py` | confirmed | `A`–`D` 占位分类加 `unknown` |
| 自由对话 | `POST /agents/chat` | `app/api/agents.py`、`app/agents/chat.py` | confirmed | 调用方传完整历史，服务不保存 |
| 本地依赖诊断 | `GET /diagnostics` | `app/api/system.py`、`app/ocr/core/deps.py` | pending-review | Java `DocsvcClient` 原调用 `/health/deps`，需同步改为 `/diagnostics` |
| 普通照片/简表识别 | `POST /ocr/recognize` | `app/api/ocr.py`、`app/ocr/form_ocr.py` | pending-review | Java 调用；2 分钟超时 |
| 监理日志识别 | `POST /ocr/daily-logs` | `app/api/ocr.py`、`app/ocr/daily_logs.py` | pending-review | 未观察到 Java 调用 |
| 监理日志识别（新版链路） | `POST /ocr/daily-logs-new` | `app/api/ocr.py`、`app/ocr/journal/` | pending-review | 独立实现；返回结构与旧接口相同 |
| 简表识别与填表 | `POST /ocr/jianbiao` | `app/api/ocr.py`、`app/ocr/jianbiao.py` | pending-review | Java 调用；2 分钟超时 |
| 公式与填表 | `POST /ocr/fill` | `app/api/ocr.py`、`app/ocr/jianbiao.py`、`app/ocr/grid.py` | pending-review | Java 调用；30 秒超时；`out` 可空 |
| 表样预览 | `GET /ocr/blank/{form}.png` | `app/api/ocr.py` | pending-review | Java 读取原始 PNG |
| 表样栏目 | `GET /ocr/sheet/{form}` | `app/api/ocr.py`、`app/ocr/grid.py` | pending-review | Java 调用；表号 URL 编码 |
| 施工图划分 | `POST /wbs/draft` | `app/api/wbs.py`、`app/ocr/wbs_draft.py` | pending-review | Java 调用；5 分钟超时；不落库 |

## 文档完整性

本次整理前：

- `interfaces/` 只覆盖 `log-summary`、`intent`、`intent/archive` 三个成功响应。
- `/agents/chat`、`/health`、`/ready`、`/diagnostics`、`/ocr/*`、`/wbs/draft` 没有统一的
  `interfaces/` 入口。
- FastAPI 自动 OpenAPI 对 `/health`、`/ready`、`/diagnostics`、`/ocr/*`、`/wbs/draft` 的
  200 响应 schema 为空对象，调用方无法据此生成类型。
- 自动 OpenAPI 只声明 200/422，没有 400/404/502/503/504。
- 没有契约变更记录、待确认草案目录或自动漂移检查。

本次整理后：

- 14 个操作全部进入统一清单和 OpenAPI 草案。
- OCR/WBS 的响应体、统一错误响应和每个操作的副作用/幂等说明进入草案。
- 新增契约生成、校验和 pytest 漂移检查。
- 未修改任何运行时请求、响应、状态码或业务行为。

## 代码与文档差异

| 差异 | 现状 | 处理 |
| --- | --- | --- |
| `AGENTS.md` 称包版本与 OpenAPI 版本“当前不同” | 实际均为 `0.1.0` | 已在规则中改为“分别维护，当前数值相同” |
| `interfaces/README.md` 只列三个智能体输出 | 不覆盖聊天、OCR、WBS | 已重写为 14 个操作的统一入口 |
| `interfaces/log_summary/README.md` 将失败响应写成统一 `detail` 字符串 | 422 校验失败实际是数组 | 已补充两种 422 形态 |
| 自动 OpenAPI 的 422 使用 FastAPI `ValidationError` | 实际处理器只保留 `type/loc/msg` | 草案改用 `RequestError` / `ValidationErrorItem` |
| OCR/WBS 自动 OpenAPI 响应 schema 为空 | 实现返回结构化对象 | 草案补充完整响应 Schema |
| `/agents/*` 无 `status/data` 包装，OCR/WBS 有 | 现有实现不一致 | 如实记录，未擅自统一；统一属于破坏性变更 |
| Java 客户端读取 `message` 或 `detail` | 本服务错误只有 `detail`，422 可能是数组 | 记录兼容性风险；未修改错误结构 |
| Java 客户端要求 `status == 200` | `/agents/*` 无该包装 | 文档明确两个域不同；Java 未调用 `/agents/*` |

未发现：重复注册、废弃路径、同一路径重复方法、文档描述为已实现但实际不存在的接口。

## 未实现能力

以下能力**没有实现，也没有在契约中描述为已实现**：

- 认证、授权、租户隔离、CORS。
- 用户、会话、历史的 CRUD 或持久化。
- 审批、订单修改、通知发送、文件归档等外部业务动作。
- 数据库 schema、任务表、审计日志。
- 异步任务、任务状态、轮询、webhook、回调。
- 分页、批量接口、multipart 上传。
- 流式聊天（SSE/WebSocket）。
- 前端直接调用的 BFF 接口。
- Java 后端的业务 API（属于相邻仓库，不在本仓库范围）。

如业务需要上述能力，应先提出接口设计草案并按
[API-First 流程](../AGENTS.md#四接口契约与-api-first-开发流程)获得批准，再实现。

## 调用方范围

本仓库不含 Java 和前端源码。基于相邻 `daolu_v6_code` 的静态检索：

- Java `DocsvcClient` 原调用 8 个操作：`/health/deps`、`/ocr/recognize`、`/ocr/jianbiao`、
  `/ocr/fill`（两处）、`/ocr/sheet`、`/ocr/blank`、`/wbs/draft`。其中 `/health/deps`
  已更名为 `/diagnostics`，Java 调用方必须同步更新；其余路径不变。
- 未观察到 Java 直接调用 `/agents/*` 或 `/ocr/daily-logs`。
- 前端通过 Java 后端间接调用文档加工接口，未观察到直接访问本服务。
- 这些观察不能替代外部仓库的实时确认；变更前仍需通知对应调用方。

详见 [调用方与兼容性](guides/consumers.md)。
