# 意图识别输出接口

接口：`POST /api/agents/intent`，JSON 编码为 UTF-8。成功返回 HTTP `200`，响应直接是包含以下四个必填字段的 JSON 对象，不增加包装层。

| 文件 | 用途 |
| --- | --- |
| [response.schema.json](response.schema.json) | 正式响应契约，与 `IntentResult.model_json_schema()`、FastAPI OpenAPI 一致，枚举固定为五类及兜底 `unknown` |
| [response.default.schema.json](response.default.schema.json) | 保留原文件路径，内容与 `response.schema.json` 相同，统一使用固定枚举 |
| [response.example.json](response.example.json) | “你好，帮我打开图片库”的单个响应参考 |
| [response.examples.json](response.examples.json) | 仅包含五类主示例，每类一组配对输入 `request` 与输出 `response` |
| [response.fallback.examples.json](response.fallback.examples.json) | 单独保存2组 `unknown` 兜底示例，覆盖目标含糊和低分需澄清 |

示例为人工参考值，不是实际模型验收记录；`reason` 的措辞和 `confidence` 的具体值由本次推理产生。发送请求时只发送 `request` 的内容；单次 API 响应只有 `response` 中的四个字段，示例中的 `name`、`request`、`response` 不构成响应包装。

## 固定返回字段

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `intent` | string 枚举 | 仅允许下列五类标签或兜底值 `unknown`，不接受旧标签或自定义分类 |
| `confidence` | number | 模型判断分数，闭区间 `[0, 1]`；不是经过校准的概率 |
| `reason` | string | `chat` 时为聊天智能体回答，至少1字符，不受300字符限制；其他标签为1–300字符的分类理由。不用于确定页面路由 |
| `needs_clarification` | boolean | 是否需要调用方提示用户澄清；使用 JSON 布尔值 `true` / `false` |

四个字段全部必填，禁止额外字段；不返回 `null`，不能把分数、布尔值写成字符串。JSON 对象的键顺序没有业务含义。

## 五类业务意图

| `intent` | 含义 | 调用方处理 |
| --- | --- | --- |
| `work_list` | 工作列表 | 映射到工作列表页面 |
| `supervision_log` | 监理日志页面 | 映射到监理日志页面 |
| `image_library` | 图片库 | 映射到图片库 |
| `business_management` | 业务管理页面 | 映射到业务管理页面 |
| `chat` | 问候、闲聊或一般交流 | 直接展示 `reason` 中的聊天回答，不触发页面跳转 |

五类主示例统一放在 `response.examples.json`，没有旧版订单、库存等自定义分类。实际页面 URL 由调用方维护，服务只返回分类，不执行跳转。

## 独立的兜底状态

`unknown` 表示信息不足、目标冲突、不支持或分数过低等无法确定分类的情况，不计入上述五类。对应示例只放在 `response.fallback.examples.json`，不混入五类主示例。

模型返回 `unknown`、分数低于 `0.65`，或 `needs_clarification=true` 时，服务统一返回 `intent="unknown"`、`needs_clarification=true`，保留模型分数和判断依据。因此 `unknown` 不一定是低分结果；即使分数较高，也可能需要澄清。恰好 `0.65`、标签有效且无需澄清时保留该标签。

调用方应先判断 `needs_clarification` 或 `intent == "unknown"` 并提示用户澄清，再处理 `chat`，其余允许的页面标签才用于路由映射。不能仅按分数或 `reason` 中的关键词跳转。

对外 JSON Schema 定义固定枚举、字段结构、非空字符串和分数范围；非 `chat` 理由的300字符限制由 `IntentResult` 校验，分类回退规则由 `IntentAgent.run()` 执行。内部分类使用独立的 `IntentClassification` Schema，所有分类理由均限300字符，不将其作为最终聊天响应契约。有效 `chat` 将用户ID、会话ID、当前 `text` 和完整历史传给共享的 `ChatAgent`，仅替换 `reason` 为回答；低分或需澄清时先回退为 `unknown`，不触发聊天。两次推理共享总超时，聊天失败沿用下表错误码，不返回分类理由充当回答。模型语义准确性由 [意图评测集](../../data/intent.json) 和 [测试说明](../../docs/intent-testing.md) 验收。

## 请求与分类约束

请求必须包含 `user_id`、`session_id`、`text` 和 `history`（首轮为[]），`text` 去除首尾空白后不能为空，最多2000字符。

已取消自定义分类。`intents` 字段仅为空字段兼容保留，可以省略或传 `[]`。任何非空 `intents` 都返回 `422`，包括传入合法的五类标签、缩减类别或尝试覆盖说明；请求在调用模型前即被拒绝。完整契约见 [API 文档](../../docs/agents-api.md#2-意图识别)。

现有调用方应删除非空候选配置，只按服务端固定五类及兜底状态处理响应。两个 Schema 文件都包含相同固定枚举，均不支持自定义结果。

## 调用示例及失败响应

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/agents/intent \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"example-user","session_id":"example-session","history":[],"text":"你好，帮我打开图片库"}'
```

成功响应见 `response.example.json`。`chat` 和 `unknown` 都是 HTTP `200` 的合法结果。

| HTTP 状态 | 含义 |
| --- | --- |
| `422` | 请求校验失败，例如空文字、长度超限或非空 `intents` |
| `503` | 模型服务不可达或不可用 |
| `504` | 推理超时 |
| `502` | 上游错误、输出不合法或模型返回固定集合之外的标签 |

失败响应不能按成功 Schema 解析。请求校验失败的 `detail` 为 FastAPI 校验详情数组；上述模型错误返回 `{"detail":"错误描述"}`。模型返回旧标签或任意非候选标签会返回 `502`，不会伪装成成功的 `unknown`。

服务不会将每次输出写入 `interfaces/`，也不保存意图会话。实际验收记录在 `verification/agents-live-result.json` 的 `checks[].request` 和 `checks[].response`；旧报告保留其当时版本，不作为当前分类契约。

## 保持契约同步

修改 `IntentResult` 后，在项目根目录重新导出两个内容相同的 Schema：

```zsh
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python - <<'PYTHON'
import json
from pathlib import Path
from app.schemas import IntentResult

root = Path("interfaces/intent")
schema = IntentResult.model_json_schema()
for filename in ("response.schema.json", "response.default.schema.json"):
    (root / filename).write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
PYTHON
```

同步五类主示例、独立兜底示例、API 文档及调用方类型，再执行 `uv run --locked pytest tests/test_intent_interface.py tests/test_intent_chat.py tests/test_agents.py tests/test_runtime.py -v`。测试检查最终响应 Schema 与 Pydantic/OpenAPI 一致、内部分类理由长度限制和聊天分流、主示例仅覆盖五类、兜底示例独立，以及非空候选在推理前被拒绝。
