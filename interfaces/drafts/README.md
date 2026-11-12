# 待确认接口草案

本目录保存 AI 根据当前实现归纳、但尚未获得用户批准的接口契约。

## 1、当前评审稿（0.1.0-review.2）

[fastapi.openapi.json](fastapi.openapi.json) 是当前应用 15 个 HTTP 操作的完整 OpenAPI 3.1
草案，由 `scripts/docs/openapi_contract.py` 从 `app.main:app` 生成并补充。便于阅读的
当前评审文档见 [../API.md](../API.md)，它由同一契约自动生成，不是独立契约。

- 智能体请求/成功响应：沿用 FastAPI/Pydantic 生成结果。
- `/health`、`/ready`、`/diagnostics` 的成功响应体。
- OCR/WBS 的 `{"status":200,"data":...}` 响应体及字段说明。
- 统一错误响应 `RequestError`、`ErrorDetail`。
- 每个操作的用途、契约状态、来源、副作用和幂等说明。

草案不改变任何运行时行为。草案中的 `confirmed` 操作表示其既有契约已由仓库规则和测试
确认；`pending-review` 操作表示响应/错误契约是本次归纳，等待用户逐项确认。

草案由 `scripts/docs/openapi_contract.py` 生成，不要手工修改 JSON。需要调整说明或
Schema 时修改该脚本后重新导出，使变更可审查、可复现。

## 2、需要用户确认的事项

### 2.1、是否确认完整 OpenAPI 基线

确认后，`interfaces/drafts/fastapi.openapi.json` 提升为
`interfaces/openapi/fastapi.openapi.json`，作为接口唯一权威来源。

### 2.2、是否确认以下 9 个 `pending-review` 操作

| 操作 | 需要确认的内容 |
| --- | --- |
| `GET /diagnostics` | `data.ok`、`data.warnings`、`data.caps` 的能力分组和可变字段 |
| `POST /ocr/recognize` | `form`、`formName`、`layout`、`fields`、`keys`、`detail`、`warning`、`align`、`image`、`lines`、`ms` |
| `POST /ocr/daily-logs` | 监理日记固定栏目、`recognized` 可省略字段、`processed` 业务结构（`taskId`/`documentType`/`common`/`fields`） |
| `POST /ocr/daily-logs-new` | 独立新链路；返回结构与 `/ocr/daily-logs` 相同的 `recognized`、`detail`、`processed`、`frame` |
| `POST /ocr/jianbiao` | 简表识别字段、`values`、`errors`、`anchors`、输出路径字段 |
| `POST /ocr/fill` | 计算值、`errors`、`anchors`、输出路径和 `xlsxSkipped` |
| `GET /ocr/blank/{form}.png` | 原始 `image/png`、`width` 上限 2400 的语义 |
| `GET /ocr/sheet/{form}` | `field`、`name`、`rect`、`behavior`、`kind` |
| `POST /wbs/draft` | `units` 递归节点、`count`、`drawings` 和桥梁可选字段 |

### 2.3、是否确认统一错误响应

- 422：请求校验失败为 `detail: [{type, loc, msg}]`；输入/上下文超限为 `detail: "..."`。
- 400/404/502/503/504：`detail: "..."`。
- 是否允许 422 这一种状态同时承载两种 `detail` 形态；若不允许，需要拆分状态码或包装，
  这属于契约变更，必须另行批准。

### 2.4、是否确认响应包装差异

- `/agents/*` 直接返回业务对象。
- OCR/WBS 返回 `{"status":200,"data":...}`。
- PNG 返回原始二进制。

当前草案如实记录现有差异，没有统一包装。若要求统一，属于破坏性契约变更。

### 2.5、是否确认未实现的接口不在本次范围

草案没有描述认证、用户/会话 CRUD、审批、订单修改、通知发送、异步任务、分页、文件上传、
流式聊天等未实现能力。

## 3、批准方式

请明确回复上述事项的批准或修改意见。示例：

```text
确认草案 0.1.0-review.2，同意将以下操作标为 confirmed：
/diagnostics、/ocr/recognize、/ocr/daily-logs、/ocr/daily-logs-new、/ocr/jianbiao、
/ocr/fill、/ocr/blank/{form}.png、/ocr/sheet/{form}、/wbs/draft。
错误响应和包装差异保持不变。
```

只有用户明确批准后，才能：

1. 把草案复制到 `interfaces/openapi/fastapi.openapi.json`。
2. 把 `info.x-contract-status` 改为 `confirmed`，把对应操作的 `x-contract-status` 改为
   `confirmed`。
3. 在 `interfaces/CHANGELOG.md` 记录批准版本。
4. 提交正式契约并开始后续实现。

用户未回复、未明确批准或仅要求继续开发，均不代表同意修改契约。未获批准时保留现有契约，
可以继续处理不依赖该变更的其他任务。

## 4、重新生成

```zsh
uv run --locked python -m scripts.docs.export_openapi
uv run --locked python -m scripts.docs.check_openapi
```

重新生成会覆盖本目录草案，但不会触碰 `interfaces/openapi/`。生成后应审查完整 diff，
不得把自动生成结果直接当作批准结果。
