# 正式 OpenAPI 契约

本目录只保存**用户已明确批准**的正式契约。

## 1、当前正式契约

当前没有完整的正式 OpenAPI 文件。用户于 2026-11-12 批准了 [监理日记正式子契约](journal.openapi.json)，覆盖 `/ocr/journal`、`/ocr/journal/recognize`、`/ocr/journal/process`。校验脚本独立检查这三个操作和全部可达 Schema，不从实现覆盖正式文件。

其他已确认的对外契约包括：

- `POST /agents/log-summary` 的固定六字段响应：
  [response.schema.json](../log_summary/response.schema.json)
- `POST /agents/intent/business` 的固定七字段响应：
  [response.schema.json](../intent/response.schema.json)
- `POST /agents/intent/archive` 的固定四字段响应：
  [response.schema.json](../intent/archive/response.schema.json)
- `POST /ocr/journal` 的成功响应（2026-11-06 用户指定后端格式）：
  [response.schema.json](../journal/response.schema.json)
- `/agents/*`、`/health`、`/ready` 的请求路径、方法和既有业务规则：
  [AGENTS.md 第四节](../../AGENTS.md#4接口契约与-api-first-开发流程)、
  [agents-api.md](../../docs/agents-api.md)

完整 OpenAPI 草案见 [drafts/fastapi.openapi.json](../drafts/fastapi.openapi.json)，
在获得用户批准前不能复制到本目录，也不能视为正式契约。

## 2、提升草案的步骤

1. 用户逐项确认 [drafts/README.md](../drafts/README.md) 中的待确认事项。
2. 复制草案为 `interfaces/openapi/fastapi.openapi.json`。
3. 将 `info.x-contract-status` 和对应操作的 `x-contract-status` 改为 `confirmed`。
4. 在 [CHANGELOG.md](../CHANGELOG.md) 记录批准日期、版本、批准范围。
5. 运行：

   ```zsh
   uv run --locked python -m scripts.docs.check_openapi
   uv run --locked pytest tests/test_interfaces_contract.py -v
   ```

6. 提交正式契约。此后任何路径、方法、字段、类型、必填性、默认值、状态码、错误语义、
   认证或权限要求的变更，都必须先获得用户批准。

## 3、禁止事项

- 禁止用 `scripts.docs.export_openapi` 直接写入本目录；脚本会拒绝。
- 禁止因为测试失败、代码重构或前后端不一致而自动覆盖正式契约。
- 禁止删除或弱化契约测试来“修复”不一致。
- 禁止把未批准的草案描述为已实现或已确认的接口。

## 4、校验行为

`scripts/docs/check_openapi.py` 在本目录存在 `fastapi.openapi.json` 时，优先以该文件为
权威契约与当前实现比较；不存在时检查 `drafts/fastapi.openapi.json`，并明确提示草案
尚未批准。
