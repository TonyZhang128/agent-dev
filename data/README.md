# 业务输入示例

| 文件 | 内容 | 用法 |
| --- | --- | --- |
| `log_summary.json` | 仅用户提供的一条工程表单 OCR 原始对象 | 请求体包含 `user_id`、`session_id`，并将此对象放入 `content`；固定输出见 [日志接口目录](../interfaces/log_summary/README.md) |
| `intent.json` | 42条业务意图样例及4条非法请求样例，版本 `5.0.0` | 发送单条 `samples[i].request` 到文件中指定的 `endpoint` |

## 工程日志输入

`log_summary.json` 保留用户给出的项目编号 `20240721LDZSM`、项目名称、施工和监理单位、抽检人、计划开始日期、分部工程桩号，以及压实度、弯沉、宽度三项指标。文件直接是系统传入的 OCR 数据对象，不含 `samples`、`request`、`expected_response` 或 `acceptance` 等评测包装，也不包含其他业务例子。

固定成功响应有 `title`、`date`、`summary`、`completed_items`、`pending_items`、`issues` 六个字段。可供其他系统使用的 [输出 Schema](../interfaces/log_summary/response.schema.json) 和 [对应输出示例](../interfaces/log_summary/response.example.json) 独立存放。日志片段读取 `summary`；本例仅有计划日期，`date` 应为 `null`，不凭表单存在推断已完成。

在项目根目录调用：

```zsh
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python - <<'PY'
import json
from pathlib import Path
import httpx

content = json.loads(Path("data/log_summary.json").read_text(encoding="utf-8"))
with httpx.Client(base_url="http://127.0.0.1:8309", timeout=190, trust_env=False) as client:
    response = client.post("/agents/log-summary", json={"user_id": "example-user", "session_id": "example-session", "content": content})
    response.raise_for_status()
    print(response.json()["summary"])
PY
```

原有11条人工回归用例已移入 `tests/fixtures/log_summary_cases.json`，用于离线与真实模型测试，不再出现在业务输入文件中。工程字段和层级变化、空值、0%合格率、备注注入及旧文字/对象兼容测试继续保留；详见 [日志总结测试说明](../docs/log-summary-testing.md)。

## 意图输入

`intent.json` 的 `endpoint` 是目标 API，`samples` 是42条业务意图样例，`expected` 是人工参考的 `status/page/action`；调用接口时只发送单条 `request`。样例覆盖全部一级页面和二级功能、一级意图澄清、基于 `last_navigation` 的纠错、聊天和未知场景。另有4条 `invalid_requests`，验证缺少/非法 `current_page`、非法历史角色或旧 `text` 字段返回 `expected_status: 422`。输出状态和示例见 [业务端意图接口](../interfaces/intent/README.md)。

`resolved` 要求 `action` 属于 `page` 且分数不低于 `0.65`；仅确定一级模块时返回 `clarify`；问候或概念问答返回 `chat`；目录外或无法确定返回 `unknown`。参考答案不要求 `message` 逐字一致，也不会执行页面跳转或其他业务操作；详见 [意图测试说明](../docs/intent-testing.md)。

`uv run --locked python -m scripts.common.verify_agents` 验证用户给出的日志输入、测试目录中的日志回归集及意图集，并验证文字日志和对话。实际请求、响应和验收结果写入本地 `verification/agents-live-result.json`，不写入本目录或接口定义文件。
