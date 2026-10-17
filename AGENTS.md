# 项目开发约定

本文件适用于整个仓库。项目为 Python 3.12 / uv / FastAPI / Pydantic / LangChain 1.x 的 Qwen 业务智能体 API。Mac 使用 Ollama，后续 Linux 使用独立部署的 vLLM；模型连接通过 `.env` 切换。

## 工作前检查

- 阅读 `README.md`、`pyproject.toml` 和本次涉及的模块；API 约定见 `docs/agents-api.md`。
- 检查 `git status`，保留用户已有修改，不覆盖 `.env`，不删除现有文件、模型或用户数据。
- 工具与 Python 环境先检查再安装，使用 Homebrew 管理 Mac 工具、uv 管理项目环境。不要向系统 Python 或其他项目环境安装包。
- 业务框架使用 LangChain 当前项目版本；升级时核对官方文档和供应商兼容性，不引入过时的 `AgentExecutor`、`initialize_agent` 等接口。

## 架构与代码位置

- `app/main.py` 负责 HTTP 路由、依赖生命周期和异常映射，不编写提示词或模型协议细节。
- `app/schemas.py` 负责输入输出契约。保持 Pydantic 严格校验和多余字段拒绝，明确长度、枚举及跨字段限制。
- `app/agents/` 负责业务输入组织、规则与 Agent 执行；`app/prompts/*.md` 维护系统提示词，按 `load_prompt()` 加载。
- 所有推理通过 `app/agents/runtime.py` 的 `build_agent()` / `invoke_agent()` 执行，使用 `langchain.agents.create_agent()`；禁止新增绕过 LangChain 的 SDK 推理路径。
- `app/llm.py` 只负责共享 `ChatOpenAI` 模型工厂、HTTP 客户端及就绪探测，不放业务提示词或分类规则。客户端由应用生命周期关闭。
- 结构化业务继承 `StructuredAgent`，显式使用 `ProviderStrategy(schema, strict=True)` 请求原生 JSON Schema，结果再经 Pydantic 校验。不要自动回退为宽松文本解析或构造默认成功结果。
- 动态 Schema 必须请求隔离，参考意图识别模块；不要修改共享已编译 Agent 的候选枚举或状态。
- 使用 LangChain 消息类型、工具和 middleware。新工具可用 `@tool`，通过 `build_agent(..., tools=...)` 注册；保留响应检查、总超时与运行步数限制。
- 当前不持久化消息、不开启 checkpointer。历史由请求提供，禁止请求之间隐式共享；增加持久会话前设计用户隔离及存储生命周期。

## 保持既有业务契约

- 保留 `/api/business/plan`、`/api/agents/log-summary`、`/api/agents/intent`、`/api/agents/chat` 的路径、请求及响应字段；契约变更必须明确记录并增加兼容性测试。
- 日志总结接受文字或 JSON 对象，不编造日期、成果或待办。
- 意图识别仅返回本次允许标签或 `unknown`；分数低于 `0.65` 或需要澄清时统一返回 `unknown`、`needs_clarification=true`。分数不是校准概率。
- 自由对话只接受完整交替的 user/assistant 历史，不接收调用方 system 提示词；限制历史条数与总长度。
- 非法输入 `422`、模型不可达 `503`、推理超时 `504`、上游错误或不合法输出 `502`；不泄漏 key、用户原文和上游错误正文。
- `/health` 是进程存活检查；`/ready` 检查模型列表，不应额外触发推理。

## 新增业务流程

1. 在 `schemas.py` 定义请求、结果和校验；在 `prompts/` 添加与 Agent `name` 同名的提示词。
2. 新建业务 Agent，优先复用 `StructuredAgent`。动态 schema 或特殊规则参考 `intent.py`。
3. 在 FastAPI 生命周期创建实例，路由声明 `response_model`。
4. 测试正常输出、输入边界及新增失败路径，更新 API 文档与 README 的结构说明。
5. 如连接业务系统，外部副作用工具需具备身份、权限、幂等与业务确认设计；当前代码不执行审批、订单修改或通知。

## 环境与依赖

- 依赖统一维护在 `pyproject.toml` 与 `uv.lock`，使用 `uv add` 更新并提交两者，不手改锁文件。
- 使用 Python 3.12，代码可采用该版本的类型语法。Ruff 负责格式、基础静态检查及导入顺序。
- `langchain`、`langchain-core`、`langchain-openai` 使用已验证的固定版本；新增集成优先选对应供应商包。不要引入 Dify 或没有业务需要的框架。
- vLLM 是 Linux 独立模型服务，不加入 Mac 业务环境；本机模型权重由 Ollama 管理，不纳入 Git。
- `LANGSMITH_TRACING=false` 为默认值，只有显式配置才开启追踪；凭据由运行环境提供，不提交真实业务追踪内容。
- 新增配置需同时更新 `Settings`、`.env.example` 和 README，保留现有 `.env`。

## 验证命令

在项目根目录运行：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked python -m unittest discover -s tests -v
```

自动化测试使用真实 LangChain Agent 加模拟 HTTP 模型响应，不需要网络或 Ollama。变更必须通过相关检查；不要通过删除校验或测试掩盖失败。

涉及推理协议、提示词、模型配置或 Agent 流程的变更，启动服务后进行真实验证：

```zsh
zsh scripts/services.sh restart-api
uv run --locked python -m scripts.verify_agents
# 如涉及 Ollama GPU 或部署脚本，再运行：
uv run --locked python -m scripts.verify_live
```

验收结果写入本地 `verification/`，不提交 Git。后台服务修改代码后须重启，不能仅以离线测试宣称部署成功。Linux CI 只运行离线业务测试和 Ruff，不下载模型。

## Git 与运行操作

- 远端 `origin`：`https://github.com/TonyZhang128/agent-dev.git`。保留历史，使用清楚描述最终行为的提交信息。
- 不提交 `.env`、密钥、模型、`.venv`、缓存、日志、验收数据或本地 `skills/`；提交前检查暂存内容。
- 不执行破坏性清理、强制推送或覆盖用户修改。为任务提交相关改动，避免纳入无关文件。
- Mac 服务通过 `scripts/services.sh` 管理，避免重复启动或停止其他来源的进程。日志见 `.logs/`；不修改用户 shell profile。
- 告知用户最终改动、实际验证结果、项目路径及运行方式；未执行的 Linux GPU 部署需明确区分。

## 可选的本地技能

本机已安装下列项目技能。若对应文件存在，匹配任务开始前阅读并遵循；`skills/` 按本地约定被 Git 忽略，新克隆仓库不要求存在这些文件。

- LangChain Agent、工具和结构化输出：`skills/langchain-fundamentals/SKILL.md`
- LangChain 环境与依赖：`skills/langchain-dependencies/SKILL.md`
- 检索增强与知识库：`skills/langchain-rag/SKILL.md`
- LangGraph 状态和工作流：`skills/langgraph-fundamentals/SKILL.md`

来源：https://github.com/langchain-ai/langchain-skills
固定修订：`16a992f09ab3ccfb642dd4f08d350d833d1990bf`。

本地选择 `skills/` 路径是因为当前环境保护 `.agents/` 与 `.codex/` 写入；这些技能不依赖全局自动发现。代码结构、依赖、运行方式仍以仓库文件为准。
