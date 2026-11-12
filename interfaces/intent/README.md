# 业务端意图识别输出接口

接口：`POST /agents/intent/business`，JSON 编码为 UTF-8。归档端 `POST /agents/intent/archive`
使用独立的 `A`–`D` 占位分类，见 [归档端接口](archive/README.md)。成功返回 HTTP `200`，
响应直接是业务对象，不增加包装层。统一接口索引和完整 OpenAPI 草案见
[上级文档](../README.md)。

本目录的 JSON Schema 是已确认的成功响应子契约；请求体、错误响应和其余操作以
[OpenAPI 草案](../drafts/fastapi.openapi.json) 为准。

| 文件 | 用途 |
| --- | --- |
| [response.schema.json](response.schema.json) | 正式响应契约，与 `BusinessIntentResult.model_json_schema()` 及契约草案一致 |
| [response.default.schema.json](response.default.schema.json) | 保留原文件路径，内容与 `response.schema.json` 相同 |
| [response.example.json](response.example.json) | 填写监理日志的 `resolved` 响应参考 |
| [response.examples.json](response.examples.json) | 覆盖 `resolved`、`clarify`、`chat`、`unknown` 的配对请求与响应 |
| [response.fallback.examples.json](response.fallback.examples.json) | 单独保存 `unknown` 和一级意图 `clarify` 示例 |

示例是人工参考值，不是实际模型验收记录；`message`、`confidence` 的具体内容由本次推理产生。
发送请求时只发送 `request` 的内容；单次 API 响应只有 `response` 中的七个字段。

## 1、固定返回字段

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `status` | string 枚举 | `resolved`、`clarify`、`chat`、`unknown` 四选一 |
| `page` | string 枚举或 `null` | 一级业务模块编码；`chat`/`unknown` 为 `null` |
| `action` | string 枚举或 `null` | 二级功能编码；`resolved` 必填，`clarify` 必须为 `null` |
| `confidence` | number | 模型判断分数，闭区间 `[0, 1]`；不是校准概率 |
| `message` | string 或 `null` | `resolved` 为 `null`；`clarify`/`chat`/`unknown` 为文案或回答 |
| `options` | array 或 `null` | 仅 `clarify` 返回，每项为 `{page, action, name}`，且全部属于 `page` |
| `catalog_version` | string | 业务功能 JSON 的内容哈希，用于前后端编码版本核对 |

七个字段全部必填，禁止额外字段；不允许把 `null` 写成字符串 `"null"`。JSON 对象的键顺序
没有业务含义。

## 2、状态语义

| `status` | 含义 | 调用方处理 |
| --- | --- | --- |
| `resolved` | 已识别到可执行的最小二级功能 | 按 `page/action` 映射到 Vue 路由并跳转 |
| `clarify` | 只确定了一级模块或需要用户补充 | 展示 `message`；可用 `options` 渲染选项；不跳转 |
| `chat` | 问候、闲聊、概念问答或一般交流 | 展示 `message`；不跳转 |
| `unknown` | 信息不足、目标冲突或目录外任务 | 展示 `message` 并请用户重新描述；不跳转 |

`resolved` 必须带 `page` 和 `action`，且 `action` 必须属于 `page`。`clarify` 必须带
`page` 和非空 `message`；`options` 是该页面下的合法二级功能。`chat`/`unknown` 的
`page`、`action` 必须为 `null`。

## 3、请求

```json
{
  "user_id": "example-user",
  "session_id": "example-session",
  "message": "我要填写今天的监理日志。",
  "current_page": "workbench",
  "history": [],
  "last_navigation": {
    "page": "supervision_diary",
    "action": "view_supervision_log"
  },
  "pending_clarification": {
    "page": "supervision_diary",
    "attempts": 1
  }
}
```

- `user_id`、`session_id`、`message`、`current_page` 必填；
  `current_page` 必须是业务功能 JSON 中合法的 page code。
- `history` 可选，省略即 `[]`；传入时必须是由 `user`/`assistant` 组成、完整交替的回合。
- `last_navigation` 可选，结构为 `{page, action}`；`action` 可空，且必须属于 `page`。
- `pending_clarification` 可选，结构为 `{page, attempts}`；`attempts` 为已完成的澄清轮数，
  取值 `0`–`10`。
- `request_id` 可选，仅由调用方用于关联；本服务不持久化，也不提供幂等保证。
- 本服务不读写数据库、不做认证；历史、当前页面和待澄清状态由调用方持久化并在每次请求传入。

## 4、目录与编码

业务功能 JSON 位于 `app/resources/intent/business_pages.json`，是页面和二级功能的唯一数据源。
构建期由 `scripts.intent.compile_catalog` 生成 `app/schemas/intent_catalog_generated.py`；
应用运行时只导入生成常量，不读取 JSON。

```zsh
# 修改 JSON 后重新生成
uv run --locked python -m scripts.intent.compile_catalog

# CI/提交前检查生成文件是否过期
uv run --locked python -m scripts.intent.compile_catalog --check
```

目录校验失败（重复 code、页面与动作 code 冲突、保留字 `chat`/`unknown`、空名称等）会阻止生成。
`action` 必须唯一归属于一个 `page`；API 只输出 `code`，`id` 仅作目录元数据。
模型返回目录外编码、`action` 不属于 `page` 或结构不合法时，服务返回 HTTP `502`，不会伪装成
`unknown` 或成功跳转。

## 5、一级意图与澄清

仅识别到一级模块时返回 `status="clarify"`、`page=<code>`、`action=null`，并调用 Chat 澄清
模式生成 `message`。`options` 由后端从目录生成，Chat 只负责措辞，不得提出目录外操作。

- 调用方保存 `pending_clarification.page` 和 `attempts`；每收到一次 `clarify`，将 `attempts`
  加 1 后随下一次请求传回。
- 同一页面最多返回 10 次澄清；`attempts >= 10` 且仍无法确定时返回 `status="unknown"`，
  不再调用 Chat。
- `pending_clarification.page` 与本次识别页面不同时，按新页面重新计数。
- Chat 澄清不可达、超时或输出为空时，服务返回 HTTP `200` 的 `clarify`，`message` 为后端根据
  目录生成的确定性选项文案，不中断导航流程。

## 6、纠错与上下文

`current_page` 表示调用方当前实际页面；`last_navigation` 表示上一次返回的导航目标。两者分开
保存，不能互相替代。用户以“不对”“不是这个”等表达否定上次导航时，模型结合
`last_navigation` 重新识别，并避免重复被否定的 `action`。当前明确诉求优先于历史；跨模块
切换不受旧 `page` 限制。

本服务不跟踪前端跳转是否成功，也不返回 `navigation_id`。调用方后端负责前端跳转、权限和
失败处理。

## 7、调用示例

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/intent/business \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"example-user","session_id":"example-session","message":"我要填写今天的监理日志。","current_page":"workbench","history":[]}'
```

`resolved` 成功响应见 `response.example.json`。`clarify`、`chat`、`unknown` 都是 HTTP `200`
的合法结果。

| HTTP 状态 | 含义 |
| --- | --- |
| `422` | 请求校验失败，例如缺少 `current_page`、历史不是完整回合、`attempts` 越界 |
| `502` | 上游错误、结构不合法、目录外编码，或 `action` 不属于 `page` |
| `503` | 模型服务不可达或不可用 |
| `504` | 分类、聊天或澄清推理超时 |

失败响应不能按成功 Schema 解析。请求校验失败的 `detail` 为 FastAPI 校验详情数组；上述模型
错误返回 `{"detail":"错误描述"}`。错误响应不泄露原始输入、身份、历史或上游错误正文。

## 8、保持契约同步

修改 `BusinessIntentResult` 后，在项目根目录重新导出 Schema：

```zsh
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python - <<'PYTHON'
import json
from pathlib import Path
from app.schemas.agents import BusinessIntentResult

root = Path("interfaces/intent")
schema = BusinessIntentResult.model_json_schema()
for filename in ("response.schema.json", "response.default.schema.json"):
    (root / filename).write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
PYTHON
```

随后同步示例、[API 文档](../../docs/agents-api.md#3意图识别)、OpenAPI 草案和调用方类型，
执行 `uv run --locked pytest tests/test_intent_interface.py tests/test_intent_business.py
tests/test_intent_catalog.py tests/test_interfaces_contract.py -v`。测试检查 Schema 与
Pydantic/契约草案一致、示例状态覆盖、目录层级、澄清选项、错误映射和生成文件漂移。
