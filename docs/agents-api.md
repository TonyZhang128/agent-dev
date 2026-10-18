# 三个业务智能体 API

服务地址：`http://127.0.0.1:8000`。交互文档：`http://127.0.0.1:8000/docs`。

| 业务 | 方法与路径 | 模块 |
| --- | --- | --- |
| 总结并生成工作日志 | `POST /api/agents/log-summary` | `app/agents/log_summary.py` |
| 意图识别 | `POST /api/agents/intent` | `app/agents/intent.py` |
| 自由对话 | `POST /api/agents/chat` | `app/agents/chat.py` |

当前版本 `0.3.0`。三个智能体均通过 LangChain `create_agent()` 执行，共享 `app/llm.py` 的 `ChatOpenAI` 模型工厂和 `.env` 配置。日志总结、意图识别使用 `ProviderStrategy` 和 JSON Schema 约束生成，最后经过 Pydantic 校验；对话返回普通文本，再包装为 JSON。接口只处理传入内容，不执行外部业务操作，不将用户消息保存为服务端会话。

## 1. 工作日志总结

`content` 可以是结构化文字，也可以是 JSON 对象。字符串不能为空；对象不能为空；序列化后最多 4000 字符。数组数据可放在 JSON 对象字段内。

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/agents/log-summary \
  -H 'Content-Type: application/json' \
  -d '{"content":{"date":"2026-10-17","completed":["完成订单查询接口"],"pending":["等待验收"],"issues":["测试账号尚未开通"]}}'
```

也可以传文字：

```json
{
  "content": "日期：2026-10-17\n已完成：完成订单查询接口\n待办：等待验收\n问题：测试账号尚未开通"
}
```

返回结构示例：

```json
{
  "title": "订单接口开发工作日志",
  "date": "2026-10-17",
  "summary": "已完成订单查询接口，正在等待验收。测试账号尚未开通。",
  "completed_items": ["完成订单查询接口"],
  "pending_items": ["等待验收"],
  "issues": ["测试账号尚未开通"]
}
```

输入未明确提供日期时 `date` 返回 `null`；没有对应事实的列表返回 `[]`。总结要求保留事实和完成状态，不补充未提供的工作成果或计划。

## 2. 意图识别

`text` 为待识别文字，最多 2000 字符。可选 `intents` 提供本次请求允许的业务意图，最多 10 项，每项包含 `label` 和 `description`。

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/agents/intent \
  -H 'Content-Type: application/json' \
  -d '{"text":"查询订单 A100 的当前状态","intents":[{"label":"order_status","description":"查询已有订单的处理状态"},{"label":"cancel_order","description":"取消已有订单"}]}'
```

返回结构示例：

```json
{
  "intent": "order_status",
  "confidence": 0.95,
  "reason": "用户明确要求查询已有订单的状态。",
  "needs_clarification": false
}
```

`label` 支持中文或英文，最多 50 字符，忽略大小写后必须唯一；`unknown` 是保留标签，不能作为自定义标签。每项说明最多 200 字符，所有标签和说明合计最多 2000 字符。

不传 `intents` 或传 `[]` 时，使用通用分类：

| 标签 | 含义 |
| --- | --- |
| `query` | 查询记录、状态或资料 |
| `create` | 新增订单、申请或记录 |
| `update` | 修改已有业务信息 |
| `cancel` | 取消或撤销业务申请、订单 |
| `help` | 操作指导和问题解答 |
| `chat` | 问候或一般交流 |
| `unknown` | 信息不足、无法匹配或意图冲突 |

无法明确判断、需要澄清或模型判断分数低于 `0.65` 时，服务返回 `intent: "unknown"`、`needs_clarification: true`。`confidence` 是模型给出的判断分数，不是经过校准的概率。

## 3. 自由对话

最简单的请求只需要 `message`：

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/agents/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好，帮我解释一下什么是业务智能体。"}'
```

返回结构：

```json
{
  "reply": "业务智能体是能够理解业务需求，并结合规则或工具处理任务的程序……",
  "model": "qwen3.5:9b-q4_K_M"
}
```

多轮对话由调用方传回历史消息：

```json
{
  "message": "项目代号是什么？",
  "history": [
    {"role": "user", "content": "项目代号是青松。"},
    {"role": "assistant", "content": "已记住项目代号：青松。"}
  ]
}
```

- 当前 `message` 最多 2000 字符。
- `history` 最多 10 条消息，也就是 5 个完整回合。
- 历史消息按 `user`、`assistant` 交替排列，以 `user` 开头、`assistant` 结束。
- 每条历史内容最多 2000 字符，当前消息和全部历史合计最多 4000 字符。
- 不接收调用方的 `system` 消息；系统提示词在 `app/prompts/chat.md` 中维护。
- 每次返回完整回答，不使用流式响应。不同请求不会自动共享历史。

## 开发位置与验证

业务规则在 `app/agents/`，系统提示词在 `app/prompts/`，请求及返回类型在 `app/schemas.py`，路由在 `app/main.py`。`app/agents/base.py` 提供可复用的结构化 Agent，`runtime.py` 统一创建和调用 LangChain Agent，`middleware.py` 检查异常模型响应，`app/llm.py` 负责 OpenAI 兼容模型适配。新增业务的步骤见 [README](../README.md#项目结构与-agent-开发)。

```zsh
# 在项目根目录执行：
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked pytest -v
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python -m scripts.common.verify_agents
```

真实测试覆盖日志文字与 JSON 输入、自定义与默认意图、含糊意图、普通对话、携带历史的对话，以及原有业务规划接口。记录保存在 `verification/agents-live-result.json`。

输入不合法返回 422；模型不可达返回 503；模型推理超时返回 504；上游错误、响应截断或输出校验失败返回 502。

后台服务修改代码后，重启 API 即可，模型服务可继续复用：

```zsh
zsh scripts/dev/services.sh restart-api
```

Linux 上线请使用 [部署脚本说明](../scripts/README.md)中的 `scripts/prod/` 入口，并由服务管理器重启 API。

原有 `POST /api/business/plan` 接口继续可用。
