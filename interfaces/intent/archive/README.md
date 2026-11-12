# 归档端意图识别输出接口

接口：`POST /agents/intent/archive`，JSON 编码为 UTF-8。成功返回 HTTP `200`，响应直接是包含以下四个必填字段的 JSON 对象，不增加包装层。

| 文件 | 用途 |
| --- | --- |
| [response.schema.json](response.schema.json) | 正式响应契约，与 `ArchiveIntentResult.model_json_schema()`、FastAPI OpenAPI 一致 |
| [response.example.json](response.example.json) | 单个 `A` 类响应参考 |

## 1、固定返回字段

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `intent` | string 枚举 | 仅允许 `A`、`B`、`C`、`D` 或兜底值 `unknown` |
| `confidence` | number | 模型判断分数，闭区间 `[0, 1]`；不是经过校准的概率 |
| `reason` | string | 1–300 字符的分类理由；归档端当前没有聊天分流 |
| `needs_clarification` | boolean | 是否需要调用方提示用户澄清 |

四个字段全部必填，禁止额外字段；不返回 `null`，不能把分数、布尔值写成字符串。

## 2、分类与兜底

归档端当前使用 `A`、`B`、`C`、`D` 四个占位分类，具体业务含义由服务端在 [profiles.py](../../../app/agents/profiles.py) 中补充。分类候选只由服务端提供，请求中的 `intents` 只能省略或为 `[]`；任何非空列表都返回 `422`，不会在推理前改写候选。

模型返回 `unknown`、分数低于 `0.65`，或 `needs_clarification=true` 时，服务统一返回 `intent="unknown"`、`needs_clarification=true`，保留模型分数和判断依据。归档端没有 `chat` 分类，问候或一般交流不会触发聊天调用。

## 3、请求示例

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/intent/archive \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"example-user","session_id":"example-session","history":[],"text":"把这份文件归档"}'
```

请求同样要求 `user_id`、`session_id`、`text` 和 `history`（首轮为 `[]`），`text` 去除首尾空白后不能为空且最多 2000 字符。

| HTTP 状态 | 含义 |
| --- | --- |
| `422` | 请求校验失败，例如空文字、长度超限或非空 `intents`；`detail` 是错误数组，输入/上下文超限时为字符串 |
| `503` | 模型服务不可达或不可用 |
| `504` | 推理超时 |
| `502` | 上游错误、输出不合法或模型返回固定集合之外的标签 |

完整 HTTP 契约（含错误 Schema）见 [OpenAPI 草案](../../drafts/fastapi.openapi.json)。业务端已改为 `POST /agents/intent/business` 的层级 page/action 契约，见 [上级接口说明](../README.md)。
