# 调用方与兼容性

本文记录对本仓库之外调用方的观察结果，用于评估接口变更影响。外部仓库不随本仓库版本化，
以下内容基于 2026-11-02 的本地工作区检索，不能替代对外部仓库的实时确认。

## 本仓库范围

本仓库只包含 Python/FastAPI 服务，不包含：

- Java/Spring Boot 后端源码。
- 业务前端、管理前端或 App 源码。
- 数据库 schema、消息队列或审批系统。

因此本文不描述、也不修改 Java 或前端接口。相邻的 `daolu_v6_code` 工作区包含 Java 后端和
前端，仅作为调用方证据使用。

## Java `DocsvcClient` 的假设

相邻 Java 项目通过单一 `DocsvcClient` 调用本服务。其行为要点：

- 基础地址来自 `daolu.docsvc-url`，默认 `http://127.0.0.1:8309`。
- POST 使用 JSON；GET 用于自检和表样。
- 只有 HTTP 200 且响应体 `status == 200` 才视为成功，并返回 `data`。
- 错误说明优先读取响应体 `message`，其次 `detail`，否则使用 HTTP 状态码。
- PNG 通过二进制 GET 读取，非 200 返回空。
- 连接/读超时、非 JSON 响应和业务错误都会转换为调用方异常。

这意味着 OCR/WBS 的成功包装 `{"status":200,"data":...}` 和错误字段 `detail` 必须保持。
`/agents/*` 不使用该包装，Java `DocsvcClient` 也不调用 `/agents/*`。

## 已观察到的调用

| 本服务操作 | Java 调用方 | 兼容性注意 |
| --- | --- | --- |
| `GET /health/deps` | 管理端依赖自检 | 期望 `{status:200,data}` |
| `POST /ocr/recognize` | 现场照片识别 | 2 分钟超时；读取 `data` 对象 |
| `POST /ocr/jianbiao` | 简表识别与填表 | 2 分钟超时；读取 `data` 对象 |
| `POST /ocr/fill` | 保存后重算、预览重算 | 30 秒超时；`out` 可为空字符串 |
| `GET /ocr/sheet/{form}` | 目标表栏目 | 表号经 URL 编码；读取 `data` |
| `GET /ocr/blank/{form}.png` | 表样预览 | 期望原始 `image/png` |
| `POST /wbs/draft` | 施工图划分初稿 | 5 分钟超时；读取 `data` 对象 |

未观察到 Java 或前端直接调用：

- `/agents/log-summary`
- `/agents/intent/business`
- `/agents/intent/archive`
- `/agents/chat`
- `/ocr/daily-logs`
- `/health`、`/ready`（可能由运维或监控调用，未在业务源码中确认）

这些接口仍是本仓库的对外契约，不能因为当前未观察到调用而删除或改变语义。

## 兼容性要求

- OCR/WBS 成功响应不得移除 `status`、`data`，也不得把 `status` 改成布尔值或字符串。
- 错误响应不得移除 `detail`；Java 读取的是顶层 `message` 或 `detail`。
- 422 的 `detail` 是数组，Java 客户端可能把它转成字符串展示；这属于调用方展示问题，
  但修改本服务错误结构会影响所有调用方，必须审批。
- PNG 接口不得改为 JSON 包装，否则 Java 二进制读取会失败。
- `out` 为空时不得写文件；非空时的输出路径语义不得改变。
- 数据池相对路径和 `projects/` 前缀兼容性不得改变。
- 任何路径、字段、包装、状态码或错误字段变化，都必须先评估上述调用方并按
  [API-First 流程](../../AGENTS.md#四接口契约与-api-first-开发流程)获得批准。

## 前后端调用链

当前观察到的文档加工调用链为：

```text
业务前端 → Java 后端 → DocsvcClient → FastAPI /ocr/*、/wbs/draft
```

前端没有直接访问本服务的证据。智能体接口目前没有接入该 Java 调用链；若后续接入，需要
先在调用方明确页面路由映射、会话历史归属、超时和错误展示，再按 API-First 流程实现。
