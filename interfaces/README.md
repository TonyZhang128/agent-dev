# 业务输出接口

各业务使用独立目录保存供其他系统对接的成功响应契约。接口定义由 `app/schemas.py` 中的 Pydantic 模型生成，与 FastAPI OpenAPI 及模型原生严格 JSON Schema 保持一致。

| 业务 | 路径 | 接口资料 |
| --- | --- | --- |
| 工程日志描述 | `POST /api/agents/log-summary` | [固定字段、Schema 和示例](log_summary/README.md) |
| 意图识别 | `POST /api/agents/intent` | [固定五类字段、Schema、主示例和兜底示例](intent/README.md) |

示例文件是接口参考值，实际调用返回内容由本次输入生成，不会覆盖这些文件。真实验证结果保存在 `verification/`。

意图识别 Schema 与 `IntentResult` / OpenAPI 一致，固定允许五类标签及额外兜底 `unknown`，不支持自定义分类。五类主示例与兜底示例分文件维护，详见业务目录。
