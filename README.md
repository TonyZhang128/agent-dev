# Qwen 业务智能体 API

基于 LangChain 1.x、FastAPI 和 Pydantic 的业务智能体开发项目。开发环境为 macOS + Ollama + Qwen3.5 9B Q4_K_M，上线环境为 Linux + NVIDIA + 独立 vLLM；业务 API 统一通过 OpenAI 兼容协议调用模型。

当前版本 `0.3.0`。四个业务均通过 `langchain.agents.create_agent()` 执行，保留原有 HTTP 请求和返回结构。

| 功能 | 接口 | 输入与输出 |
| --- | --- | --- |
| 工作日志总结 | `POST /api/agents/log-summary` | 文字或 JSON 对象 → 结构化日志 |
| 意图识别 | `POST /api/agents/intent` | 文字、可选候选标签 → 意图、判断分数、澄清标记 |
| 自由对话 | `POST /api/agents/chat` | 当前消息、可选历史 → 回答和模型名称 |
| 业务步骤规划 | `POST /api/business/plan` | 自然语言业务指令 → 目标、步骤、假设、待确认问题 |

服务默认监听 `127.0.0.1:8000`，交互文档为 <http://127.0.0.1:8000/docs>。这些接口生成内容和计划，尚未连接审批、订单或消息发送等业务系统。

## 环境与安装

本机已验证：Apple M5 / 24GB、macOS 26.7.1、Ollama 0.40.5、Qwen3.5 9B Q4_K_M、Metal GPU。项目固定 Python 3.12；`uv.lock` 锁定完整依赖，虚拟环境位于 `.venv/`，与其他 Python 项目隔离。

主要依赖：LangChain `1.4.6`、langchain-core `1.6.12`、langchain-openai `1.7.2`、FastAPI `0.136.3`、Pydantic `2.13.4`。OpenAI SDK 由 LangChain 模型适配器使用；LangSmith 已安装，默认关闭追踪。`create_agent()` 内部依赖 LangGraph 运行时，项目没有自行维护图工作流或引入 Dify。

新机器获取代码：

```zsh
git clone https://github.com/TonyZhang128/agent-dev.git
cd agent-dev
```

现有工作目录为 `qwen-business-dev/`；仓库克隆后的目录名可以不同。以下命令均在项目根目录执行。

Mac 已安装 Homebrew 时，可使用完整安装脚本：

```zsh
zsh scripts/dev/setup.sh
zsh scripts/dev/services.sh status
```

脚本检查并复用 uv、Ollama、Python 3.12 和模型层；缺少工具时使用 Homebrew / uv 安装。随后安装锁定依赖、运行自动化测试、启动用户会话服务、拉取约 6.6GB 模型并验证真实推理。已有 `.env` 保留；模型默认保存在 `~/.ollama/models`，已有 `OLLAMA_MODELS` 配置会被保留。

已有工具和模型、只需准备项目时：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev
test -f .env || cp .env.example .env
```

`scripts/dev/setup.sh` 需要已有 Homebrew，缺少时会提示安装地址并退出。缓存齐全时 uv 命令可追加 `--offline`。

## 配置与启动

配置读取顺序：进程环境变量优先，然后是项目根目录 `.env`，最后是代码默认值。API key 使用 `SecretStr`，不应提交到 Git。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI 兼容模型 API，包含 `/v1` |
| `LLM_MODEL` | `qwen3.5:9b-q4_K_M` | 服务端模型名称 |
| `LLM_API_KEY` | `ollama` | Ollama 占位值；远端服务按需填写真实 key |
| `LLM_TIMEOUT_SECONDS` | `180` | 一次 Agent 调用的总超时，也用于模型 HTTP 超时 |
| `LLM_MAX_TOKENS` | `2048` | 模型输出长度限制 |
| `LLM_REASONING_EFFORT` | `none` | 关闭当前 Qwen 服务的思考输出；不支持的服务可设为空 |
| `AGENT_RECURSION_LIMIT` | `8` | Agent 运行步数上限，包含工具调用循环 |
| `LANGSMITH_TRACING` | `false` | 是否开启 LangSmith 追踪 |

开启 LangSmith 时，还需在进程环境提供其凭据；追踪可能包含业务输入和模型输出。项目默认不会上传追踪。

Mac 后台运行：

```zsh
zsh scripts/dev/services.sh start
zsh scripts/dev/services.sh status
# 修改代码或 .env 后：
zsh scripts/dev/services.sh restart-api
# 停止本项目注册的两个任务：
zsh scripts/dev/services.sh stop
```

脚本注册 `local.qwen-business-dev.ollama`、`local.qwen-business-dev.api` 用户会话任务，复用已运行的服务，不修改 shell profile。任务持续到停止或退出登录；重新登录后运行 `start`。日志在 `.logs/*-service.*.log`。其他方式启动的进程不会被脚本停止。

前台开发时，先停止本项目后台任务，再在两个终端分别执行：

```zsh
zsh scripts/dev/start-ollama.sh
```

```zsh
zsh scripts/dev/start-api.sh --reload
```

如 Ollama 已由其他方式启动，直接复用。默认 Ollama 上下文 `8192`、单模型、单并发；Apple Silicon 的 GPU 由 Ollama 自动选择，使用 `ollama ps` 查看 `PROCESSOR` 列。不要同时在端口 8000 启动前台和后台 API。

## 代理与下载

本机代理示例为 `http://127.0.0.1:10808`，端口以实际代理配置为准。TUN 开启后仍建议验证终端和模型下载服务的连通性：

```zsh
zsh scripts/dev/check-network.sh http://127.0.0.1:10808
HTTPS_PROXY=http://127.0.0.1:10808 \
https_proxy=http://127.0.0.1:10808 \
NO_PROXY=localhost,127.0.0.1,::1 \
no_proxy=localhost,127.0.0.1,::1 \
zsh scripts/dev/setup.sh
```

下载由 Ollama 服务进程发起；新启动的服务继承代理，复用的服务需要自身具有可用网络配置。安装命令的代理设置不修改 `.zshrc`。HTTP 401/403 只表示收到响应，不能证明有下载权限。

## 调用与验证

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8000/health
curl --noproxy '*' -fsS http://127.0.0.1:8000/ready
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/agents/log-summary \
  -H 'Content-Type: application/json' \
  -d '{"content":{"completed":["完成订单接口"],"pending":["等待验收"],"issues":[]}}'
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/agents/intent \
  -H 'Content-Type: application/json' -d '{"text":"查询订单 A100 的状态"}'
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/agents/chat \
  -H 'Content-Type: application/json' -d '{"message":"你好，请解释业务智能体。"}'
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/business/plan \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"检查报销发票，齐全则提交经理审批，否则通知员工补齐。"}'
```

完整字段、返回示例、意图标签及历史消息限制见 [智能体 API 文档](docs/agents-api.md)。`/health` 检查 API 存活，`/ready` 检查上游列出配置模型；只有业务调用会实际推理。

错误状态：输入校验失败 `422`，模型服务不可达 `503`，调用超时 `504`，上游错误、拒绝、截断或不合法结果 `502`。模型失败不会返回伪造的成功结果。

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked python -m unittest discover -s tests -v
# 需要运行中的 API 和真实模型：
uv run --locked python -m scripts.common.verify_agents
# 额外验证模型直调、ASGI、TCP 接口和 Ollama GPU：
uv run --locked python -m scripts.dev.verify_live
ollama ps
```

自动化测试运行真实 LangChain Agent 和模拟模型 HTTP 传输，不需要 Ollama、联网或云端凭据。测试覆盖脚本分流、生产启动限制、配置保留，以及既有 API、结构化输出、并发标签隔离、消息隔离、超时、异常以及工具调用循环。真实验收脚本覆盖 8 个业务案例，记录写入本地 `verification/agents-live-result.json`；验收记录、日志和缓存不提交 Git。GitHub Actions 在 Linux 上执行锁定依赖安装、Ruff 和自动化测试，不执行模型下载和真实推理。

## 项目结构与 Agent 开发

```text
app/
  main.py                 # FastAPI 路由、生命周期、错误到 HTTP 状态的映射
  config.py               # .env 配置与默认值
  schemas.py              # 请求、响应的 Pydantic 模型和校验
  llm.py                  # ChatOpenAI 工厂、共享 HTTP 客户端、模型就绪检查
  errors.py               # 与 HTTP 无关的模型输出错误
  agents/
    runtime.py            # create_agent / ProviderStrategy / 超时 / 运行步数限制
    middleware.py         # 拒绝、截断、空输出及工具响应检查
    base.py               # 可复用的类型化结构化业务 Agent
    business_plan.py      # 业务步骤规划
    log_summary.py        # 工作日志总结
    intent.py             # 请求级候选标签、意图识别及低分澄清
    chat.py               # 对话消息组织和文本回答
  prompts/
    __init__.py           # 按模块路径加载提示词，不依赖当前工作目录
    business_plan.md     # 各业务独立维护的系统提示词
    log_summary.md
    intent.md
    chat.md
tests/                    # API、错误处理、Agent 运行时与工具调用测试
scripts/
  dev/                    # macOS：Homebrew、Ollama、launchd、Metal GPU 验收
  prod/                   # Linux：运行依赖、API、独立 vLLM、NVIDIA 验收
  common/                 # 两种环境共用的业务与模型真实推理验收
  README.md               # 脚本入口和迁移说明
  *.sh / verify_*.py      # 原路径兼容入口
docs/agents-api.md        # 对外 API 约定和示例
.github/workflows/ci.yml # Linux 自动检查
pyproject.toml / uv.lock  # 直接依赖与完整锁文件
.env.example             # 可提交的配置模板；实际 .env 不提交
AGENTS.md                 # 后续编码 Agent 的仓库约定
```

调用链：`FastAPI → 业务 Agent → runtime.create_agent → ChatOpenAI → Ollama/vLLM`。结构化业务显式使用 `ProviderStrategy(JSON Schema, strict=True)`，最后再通过 Pydantic 校验；自由对话使用同一 Agent 运行时返回文本。业务代码不直接调用 OpenAI SDK。

新增结构化业务通常修改四处：

1. 在 `app/schemas.py` 定义请求与结果类型，在 `app/prompts/` 添加同名 `.md` 提示词。
2. 在 `app/agents/` 继承 `StructuredAgent[请求类型, 结果类型]`，定义 `name`、`result_type` 和 `user_content()`。日志总结模块可作为起点。
3. 在 `app/main.py` 生命周期中创建实例，增加携带 `response_model` 的路由。
4. 为正常、非法输入和模型失败增加测试，更新 API 文档并运行检查。

动态候选标签参考 `IntentAgent.response_schema()`，每次请求单独构建带枚举的 Agent，避免并发污染。系统提示词修改后需重启 API，以刷新缓存。

需要调用真实业务系统时，用 LangChain `@tool` 定义工具，通过 `build_agent(..., tools=(... ,))` 注册；统一调用 `invoke_agent()` 保留超时、追踪和步数控制。现有业务未注册工具，测试中已覆盖完整工具循环。会改变业务状态的工具应先设计身份、权限、幂等和确认机制，再接入对应业务 API。

目前无服务端持久记忆：聊天历史由调用方传入，每次 Agent 调用使用独立消息状态，未配置 checkpointer。新增会话持久化时需明确用户隔离及存储生命周期。

## Linux + NVIDIA 上线

开发和上线使用同一份业务代码及 `uv.lock`，通过脚本目录与模型配置区分。Linux 不执行 Homebrew、launchd 或 Ollama 安装；vLLM 独立于业务 `.venv`。脚本清单见 [scripts/README.md](scripts/README.md)，后台托管示例见 [Linux 部署说明](docs/deployment-linux.md)。

先在 Linux 安装 uv，再准备业务环境：

```bash
bash scripts/prod/setup.sh
```

脚本使用 Python 3.12 和 `uv sync --locked --no-dev`，不安装 dev 依赖、不启动服务、不下载模型。根目录 `.env` 不存在时，从 `scripts/prod/api.env.example` 创建；已有 `.env` 保留。将 `LLM_API_KEY` 的占位值改为模型服务密钥，并确认以下配置：

```dotenv
LLM_BASE_URL=http://127.0.0.1:8001/v1
LLM_MODEL=qwen-business
LLM_API_KEY=your-server-key
LLM_REASONING_EFFORT=
```

按照 [Qwen3.5 vLLM 官方部署说明](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md)，在独立 Python 环境安装经过目标 GPU 验证的固定版本 vLLM。模型权重、CUDA 兼容性、显存、量化及并发参数由目标服务器确定，Mac 的 Ollama 模型不直接复用。

在模型服务的终端设置 `VLLM_BIN`（独立环境可执行文件的绝对路径）、`VLLM_MODEL_PATH`（HF 模型 ID 或本地目录），并通过运行环境注入 `VLLM_API_KEY`，与业务 `LLM_API_KEY` 一致。以下为 Qwen3.5 文本业务启动示例，具体参数需按已安装 vLLM 版本验证：

```bash
export VLLM_BIN=/opt/vllm/bin/vllm
export VLLM_MODEL_PATH=/srv/models/your-qwen-model
# 运行环境需已提供 VLLM_API_KEY，勿将真实密钥写入仓库。
bash scripts/prod/start-vllm.sh \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

该入口检查 Linux 和 NVIDIA 驱动，默认监听 `127.0.0.1:8001`，服务名为 `qwen-business`；其他 vLLM 参数原样传入。关闭思考的参数来自 [官方 Qwen3.5 配置说明](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md#configuration-tips)。密钥使用 [vLLM 原生环境变量](https://docs.vllm.ai/en/latest/configuration/env_vars/#environment-variables)传递。

另一终端启动业务 API，模型就绪后执行验收：

```bash
bash scripts/prod/start-api.sh
# 另一个终端：
bash scripts/prod/verify.sh
```

API 默认监听 `127.0.0.1:8000`，拒绝 `--reload`，启动时不安装或同步依赖。上线需由 systemd 等服务管理器托管，详见 [部署说明](docs/deployment-linux.md)。API 与模型可以部署在不同 Linux 主机；API 主机无需 GPU，`start-vllm.sh` 和完整 `verify.sh` 用于 GPU 主机，远端 API 可单独运行通用业务验收。

模型服务需支持 Chat Completions 和原生 JSON Schema 输出；以真实业务验收结果判断具体模型和 vLLM 组合是否可用。验收文件写入 `verification/`，`nvidia-smi` 成功仅确认驱动和设备可见，模型 GPU 占用需另看服务日志和设备监控。本机未执行 Linux GPU 部署。

## Git 版本管理

远端：<https://github.com/TonyZhang128/agent-dev>。提交 `app/`、测试、文档、脚本、依赖锁文件与 CI；忽略 `.env`、虚拟环境、模型、缓存、日志、验收输出和本地 `skills/`。

后续开发可从 `main` 创建功能分支，运行检查后提交：

```zsh
git switch -c feature/your-agent
# 开发并运行上述检查
git add app tests docs README.md pyproject.toml uv.lock
git commit -m "feat: add a business agent"
git push -u origin feature/your-agent
```

升级依赖时使用 `uv add` / `uv lock` 同步更新 `pyproject.toml` 和 `uv.lock`，通过测试后一起提交，不手改锁文件。

## 官方资料

- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain 结构化输出](https://docs.langchain.com/oss/python/langchain/structured-output)
- [ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)
- [uv 项目管理](https://docs.astral.sh/uv/guides/projects/)
- [Ollama OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)
- [Ollama 结构化输出](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama GPU 支持](https://docs.ollama.com/gpu)
- [vLLM 结构化输出](https://docs.vllm.ai/en/latest/features/structured_outputs/)
