# 意图识别测试说明

接口：`POST /api/agents/intent`。请求、响应和兼容说明见 [API 文档](agents-api.md#2-意图识别)。

## 验收规则

业务分类固定为五类，`unknown` 作为分类之外的兜底状态：

| 标签 | 类别 | 正常用例 |
| --- | --- | --- |
| `work_list` | 工作列表 | 打开工作列表；今天有哪些待办任务 |
| `supervision_log` | 监理日志页面 | 进入监理日志；填写今天的监理日记 |
| `image_library` | 图片库 | 打开图片库；看看施工现场照片 |
| `business_management` | 业务管理页面 | 进入业务管理页面；去办理业务 |
| `chat` | 问候、闲聊或一般交流 | 你好；谢谢；监理日志是什么 |

不传 `intents` 和传 `[]` 的效果相同。任何非空 `intents` 均返回 `422` 且不调用模型；不支持自定义分类，即使传入的标签属于当前五类也不允许覆盖候选。各请求的消息保持隔离，响应枚举固定为五类加兜底 `unknown`。

| 边界或失败场景 | 预期 |
| --- | --- |
| “你好，帮我打开图片库” | `image_library`，问候不覆盖导航 |
| “不要图片库，打开工作列表” | `work_list`，识别最终明确目标 |
| “监理日志是什么” | `chat`，概念问答不触发导航 |
| 工作列表和图片库无法确定先去哪一个 | `unknown`，需要澄清 |
| 打开系统设置页面 | `unknown`，不支持的页面 |
| 含糊指令、无法匹配的订单修改、要求忽略规则 | `unknown`，不强制归入业务管理或交流 |
| 分数为 `0` 或 `0.6499` | `unknown`，`needs_clarification=true` |
| 有效标签、分数恰为 `0.65` 或 `1`，无需澄清 | 保留该标签，`needs_clarification=false` |
| 模型标记需澄清，或直接返回 `unknown` | `unknown`，`needs_clarification=true` |
| 模型返回旧默认标签或其他非候选标签、非法分数、非法结构 | HTTP `502` |
| 空输入、超长文字及任何非空 `intents` | HTTP `422`，不调用模型 |
| 模型不可达、超时、上游错误 | HTTP `503`、`504`、`502` |

旧标签或自定义标签不再是合法分类结果；测试中的旧标签只用于验证拒绝行为。实际路由由调用方映射，`chat` 和 `unknown` 不触发页面跳转。有效 `chat` 会继续调用 `ChatAgent`，`reason` 返回其回答，其他三个字段保持分类结果；其他标签仍返回分类理由。分数不是校准概率。

## 离线自动化测试

`tests/test_intent_chat.py` 覆盖聊天分流、原文传递、超过300字符的完整回答、0.65边界、低分和需澄清时不调用聊天、非聊天标签单次推理、跨接口消息隔离、聊天失败错误码和整条调用链总超时。分类理由仍限300字符，仅最终聊天回答放宽限制。

`tests/test_agents.py` 使用真实 LangChain Agent 和模拟模型 HTTP 响应，验证五类枚举、提示词输入候选、原生严格 Schema、分数边界、兜底、非法输出和非空候选拒绝。`tests/test_runtime.py` 验证并发固定分类请求的消息隔离；`tests/test_verify_agents.py` 验证真实验收脚本读取版本化数据集并在标签不匹配时报告失败。模拟模型响应只验证程序契约，语义判断能力由真实评测验收。

`tests/test_intent_interface.py` 检查 [输出接口资料](../interfaces/intent/README.md)：固定响应 Schema 与 Pydantic/OpenAPI 一致，兼容文件的 Schema 与最终响应一致，内部 Agent 使用独立分类 Schema 保留300字符理由限制，四字段全部必填且禁止额外字段。`response.examples.json` 仅包含五类主示例，`response.fallback.examples.json` 单独包含2组兜底示例；两者均验证固定枚举与澄清规则。`response.schema.json` 与兼容路径 `response.default.schema.json` 内容相同，均固定为五类及兜底枚举；测试还验证24条分类和4条拒绝请求的版本化数据集。

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pytest -v
```

测试目前直接放在 `tests/`。`AGENTS.md` 的 TDD 命令引用尚不存在的 `tests/unit/` 和 `tests/integration/`，因此当前全量测试使用上面的 `pytest -v`。

## 真实模型评测

版本化数据集 [data/intent.json](../data/intent.json) 为 `4.0.0`，包括24条 `samples` 分类用例和4条 `invalid_requests` 非法候选请求。分类成功标准为24条用例全部 HTTP `200`，通过 `IntentResult` 校验，标签和澄清标记与 `expected` 完全匹配；所有非 `unknown` 结果分数不低于 `0.65` 且不需澄清，所有 `unknown` 结果必须需要澄清。`reason` 无需逐字匹配。4条非法请求必须返回 HTTP `422`；若服务仍接受非空候选，验收失败。

在 Mac 启动模型服务后，重启 API 以加载新提示词，再验收：

```zsh
zsh scripts/dev/services.sh restart-api
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python -m scripts.common.verify_agents
```

脚本同时验证用户提供的1条日志输入、`tests/fixtures/log_summary_cases.json` 的11条回归样例（含5条工程 OCR）、两个兼容日志、两个对话及一个业务规划案例，加上24条意图分类和4条非法候选请求，合计45次 HTTP 业务调用（41次成功响应、4次预期 `422`）；日志标准见 [日志总结测试说明](log-summary-testing.md)。报告写入不提交 Git 的 `verification/agents-live-result.json`，包含模型、框架版本、数据集版本、逐条实际请求及响应；意图和数据集日志用例还包含预期及通过状态。每条 `checks[i].request` 是实际发送的 JSON 请求体（包括非法候选请求或聊天历史），`checks[i].response` 是 API 返回结果，`expected` 是对应业务参考答案，`passed` 是比对结果，日志还包含 `acceptance` 事实约束，非法候选检查使用 `expected_http_status` 和 `passed` 记录预期拒绝结果。任一意图或日志不匹配都会使脚本退出失败；有限样例通过不代表所有自然语言输入均能正确分类。

Linux 使用相同业务代码和评测集，重启部署服务后执行通用验收，完整 GPU 验收见 [Linux 部署说明](deployment-linux.md#4-真实验收)。Mac 结果不能代替 Linux + vLLM 实机验收。

会话契约和历史裁剪测试见 `tests/test_sessions.py`，覆盖交错并发用户/会话、独立失败、完整历史与裁剪、边界预算、原始历史不变和两级 Agent 元数据。新增历史指代、当前意图覆盖和历史导航后感谢样例，输入含必填身份与历史字段。
