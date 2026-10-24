# 工程日志固定输出接口

接口：`POST /api/agents/log-summary`，JSON 编码为 UTF-8。成功返回 HTTP `200`，响应直接是包含以下六个必填字段的 JSON 对象，不增加额外包装层。

- [response.schema.json](response.schema.json)：供调用方校验、生成类型的 JSON Schema，与 `LogSummary.model_json_schema()` 一致。
- [response.example.json](response.example.json)：对应 [用户提供的 OCR 输入](../../data/log_summary.json) 的人工参考输出。

## 固定返回字段

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `title` | string | 事项标题，1–100字符 |
| `date` | string 或 null | 原样摘录日志或实际检测日期，1–50字符；本例只有计划开始日期，返回 `null` |
| `summary` | string | 可纳入当日日志的一段中文，1–1000字符 |
| `completed_items` | string[] | 仅明确已完成的事项，无则 `[]` |
| `pending_items` | string[] | 仅明确待办或进行中事项，无则 `[]` |
| `issues` | string[] | 仅明确的问题、风险或无法确定的矛盾，无则 `[]` |

三个数组各最多8项，每项1–300字符。六个字段必须全部存在；不得改为中文字段名、随内容增减字段、将数组改为字符串或将 `null` 写成字符串 `"null"`。调用方按字段名读取，JSON 对象的键顺序没有业务含义。

`summary` 按“项目或标段、工程部位—检测事项—指标实测值及单位—已记录的合格率或结论”组织，不存在的信息省略。实测值不换算、不四舍五入；弯沉 `0.1、0.2、0.3（单位0.01mm）` 保持原值和单位。`specified` 是要求，不能当作实际合格结论；缺失合格率不推断合格或不合格；表格存在不能推断已完成。当前固定的是 JSON 结构及描述顺序，具体业务话术仍按暂行规则生成，正式话术标准待补充；规则在 `app/prompts/log_summary.md` 维护。

## 发送系统输入并读取输出

`data/log_summary.json` 仅保存用户提供的原始 OCR 对象，不含测试集、参考答案或 HTTP 包装。调用现有 API 时仍放入 `content` 字段，并同时传入必填的用户与会话ID：

```zsh
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python - <<'PY'
import json
from pathlib import Path
import httpx

content = json.loads(Path("data/log_summary.json").read_text(encoding="utf-8"))
with httpx.Client(timeout=190, trust_env=False) as client:
    response = client.post(
        "http://127.0.0.1:8000/api/agents/log-summary",
        json={"user_id": "example-user", "session_id": "example-session", "content": content},
    )
    response.raise_for_status()
    result = response.json()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(result["summary"])
PY
```

请求序列化后最多4000字符；输入内部字段及层级可变化，继续兼容通用日志文字。这个目录的 JSON Schema 只定义成功响应。失败返回 `{"detail":"错误描述"}`：输入非法 `422`、模型不可达 `503`、超时 `504`、上游错误或输出不合法 `502`，不能按成功响应解析。

服务不自动把每次业务输出写入该目录，也不保存服务端日志会话；调用方获取响应后按自己的存储生命周期处理。真实验收报告在 `verification/agents-live-result.json`。

## 保持契约同步

修改 `LogSummary` 后，在项目根目录重新导出 Schema：

```zsh
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python - <<'PY'
import json
from pathlib import Path
from app.schemas import LogSummary

Path("interfaces/log_summary/response.schema.json").write_text(
    json.dumps(LogSummary.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY
```

随后同步响应示例、[API 文档](../../docs/agents-api.md#1-工作日志总结) 及调用方类型，执行 `uv run --locked pytest tests/test_log_summary_interface.py tests/test_agents.py -v`。测试会检查原始输入、Schema 与 Pydantic/OpenAPI 一致性、字段必填及示例合法性。边界回归数据在 `tests/fixtures/log_summary_cases.json`，不属于业务传入接口。
