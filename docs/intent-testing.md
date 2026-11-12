# 意图识别测试说明

接口：`POST /agents/intent/business`。请求、响应和兼容说明见 [API 文档](agents-api.md#2-意图识别)。
归档端 `POST /agents/intent/archive` 仍使用 `A`–`D` 占位分类及 `unknown` 兜底，不纳入本文件的
业务意图语义评测；其离线测试见 `tests/test_intent_archive.py`。

## 验收规则

业务端使用层级目录 `app/resources/intent/business_pages.json`，页面编码和二级功能编码由
构建期生成枚举。响应状态与验收标准：

| `status` | 验收标准 |
| --- | --- |
| `resolved` | `page`、`action` 均存在，`action` 属于 `page`，`confidence >= 0.65` |
| `clarify` | `page` 存在，`action` 为 `null`，`message` 非空，`options` 全部属于 `page` |
| `chat` | `page`、`action` 为 `null`，`message` 非空 |
| `unknown` | `page`、`action` 为 `null`，`message` 非空 |

目录外编码、`action` 不属于 `page`、结构不合法或非法 JSON 必须是 HTTP `502`，不能降级为
`unknown` 或伪造成功跳转。

| 场景 | 预期 |
| --- | --- |
| 明确的二级意图，例如“我要填写监理日志” | `resolved`，`supervision_diary/fill_supervision_log` |
| 只表达一级模块，例如“进入监理日记这个模块” | `clarify`，`page=supervision_diary`，`action=null` |
| 同页多个动作无法确定 | `clarify`，携带该页 `options` |
| 用户否定上次导航 | 结合 `last_navigation` 重新识别，不重复被否定的 `action` |
| 用户明确提出新模块 | 直接识别新页面，不受 `current_page` 限制 |
| 问候、闲聊或概念问答 | `chat` |
| 目录外任务或跨页面冲突 | `unknown` |
| 缺少 `current_page`、非法 page code、非完整历史 | HTTP `422`，不调用模型 |
| 模型不可达、超时、上游错误 | HTTP `503`、`504`、`502` |

`confidence` 是模型判断分数，不是校准概率。低分或同页动作不确定时返回 `clarify`；只有无法
确定页面时才返回 `unknown`。

## 澄清轮次

- 调用方在 `pending_clarification.attempts` 传入已完成的澄清轮数，从 0 开始。
- 同一页面返回 `clarify` 后，调用方将 `attempts` 加 1 再传回。
- `attempts >= 10` 且模型仍无法确定时返回 `unknown`，不再调用 Chat。
- `pending_clarification.page` 与本次识别页面不同时，按新页面重新计数。
- Chat 澄清失败时返回 HTTP `200` 的确定性选项文案，保留 `page` 和 `options`。

## 离线自动化测试

- `tests/test_intent_catalog.py`：JSON 唯一性、保留字、父子关系、内容哈希、生成文件漂移。
- `tests/test_intent_business.py`：`resolved`/`clarify`/`chat`/`unknown`、低分和需澄清回退、
  10 轮上限、`last_navigation`/`pending_clarification` 传递、非法模型输出 `502`、
  Chat 澄清失败降级、请求校验和错误映射。
- `tests/test_intent_chat.py`：业务意图 `chat` 分流、消息隔离、分类与聊天共享总超时。
- `tests/test_intent_interface.py`：发布 Schema 与 Pydantic/契约草案一致、示例状态覆盖、
  版本化数据集结构、共享 Chat/澄清 Agent。
- `tests/test_sessions.py`：业务意图可选历史、完整历史传递、裁剪和并发隔离。
- `tests/test_interfaces_contract.py`、`tests/test_routing.py`：完整 OpenAPI、路由注册和
  已发布响应子契约。

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev --extra ocr-cpu
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked python -m scripts.intent.compile_catalog --check
uv run --locked pytest -v
```

## 真实模型评测

版本化数据集 [data/intent.json](../data/intent.json) 为 `5.0.0`，包含 42 条业务意图样例和
4 条非法请求：

- 31 条二级功能样例，覆盖目录中的全部 `action`；
- 6 条一级意图 `clarify` 样例，覆盖全部 `page`；
- 1 条基于 `last_navigation` 的纠错样例；
- 2 条 `chat` 样例；
- 2 条 `unknown` 样例；
- 4 条非法请求：缺少/非法 `current_page`、非法历史角色、旧 `text` 字段，均应返回 `422`。

成功标准：

- 每条样例 HTTP `200` 且通过 `BusinessIntentResult` 校验；
- `status`、`page`、`action` 与 `expected` 完全匹配；
- 所有 `resolved` 结果 `confidence >= 0.65`；
- 所有 `clarify` 结果 `action=null`、`options` 属于 `page`；
- 所有 `unknown`/`chat` 结果 `page`、`action` 为 `null`；
- 4 条非法请求均返回 `422`。

`message` 的具体措辞、`reason`（内部字段）和 `confidence` 的具体数值不要求逐字一致。

在 Mac 启动模型推理服务后，重启算法服务以加载新提示词和目录，再验收：

```zsh
zsh scripts/dev/services.sh restart-api
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python -m scripts.common.verify_agents
```

报告写入不提交 Git 的 `verification/agents-live-result.json`，包含模型、框架版本、数据集版本、
逐条实际请求及响应。有限样例通过不代表所有自然语言输入均能正确分类；新增或调整目录后必须
重新运行生成器和真实评测。Linux 使用相同业务代码和评测集，重启部署服务后执行通用验收；
Mac 结果不能代替 Linux + vLLM 实机验收。
