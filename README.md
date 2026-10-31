# 公路工程业务智能体层

基于 LangChain 1.4.6、FastAPI 和 Pydantic 的公路工程业务智能体开发项目。主要为公路工程数据智采，业务平台，管理平台，归档组卷平台等提供智能体与AI算法服务。

开发环境为 macOS + Ollama + Qwen3.5 9B Q4_K_M，上线环境为 Linux + NVIDIA + 独立 vLLM；业务 API 统一通过 OpenAI 兼容协议调用模型。

包版本为 `0.1.0`（`pyproject.toml`）；当前 OpenAPI 标题为“公路工程业务智能体”、版本为 `0.1.0`（`app/main.py`）。两者分别维护项目包元信息与 API 文档元信息。三个智能体均通过 `langchain.agents.create_agent()` 执行，HTTP 层使用按领域组织的 `APIRouter`。

开发者和编程代理的共享规范见 [AGENTS.md](AGENTS.md)；`CLAUDE.md` 引用同一份规则。完整请求/响应契约见 [API 文档](docs/agents-api.md)，脚本入口见 [脚本说明](scripts/README.md)。

| 功能 | 接口 | 输入与输出 |
| --- | --- | --- |
| 工程日志描述 | `POST /agents/log-summary` | 可变结构的工程表单 OCR JSON（兼容文字）→ 日志段落及结构化字段 |
| 意图识别 | `POST /agents/intent` | 文字与历史消息 → 固定四个页面或一般交流类别、判断分数、澄清标记；一般交流返回聊天回答 |
| 自由对话 | `POST /agents/chat` | 当前消息、必填历史（首轮 `[]`）→ 回答和模型名称 |
| 照片/简表 OCR | `POST /ocr/recognize`、`POST /ocr/jianbiao` | 数据池照片 → 草稿字段、定位与识别详情 |
| 公式与填表 | `POST /ocr/fill` | 核对后的值 + 配置 → 公式/引用结果，可输出同源 PDF/Excel |
| 表样预览与字段 | `GET /ocr/blank/{form}.png`、`GET /ocr/sheet/{form}` | 空白表 PNG、版面栏与格子字段 |
| 施工图划分 | `POST /wbs/draft` | PDF/工可 → WBS 划分初稿 |
| 文档依赖自检 | `GET /health/deps` | OCR、PDF、Excel、图像库导入与推理设备检查 |
| 进程存活 | `GET /health` | `{"status":"ok"}`，不访问模型 |
| 模型就绪 | `GET /ready` | 检查配置模型是否出现在上游模型列表，成功返回 `{"status":"ready"}`，不执行推理 |

服务默认监听 `127.0.0.1:8309`，交互文档为 <http://127.0.0.1:8309/docs>。这些接口生成内容和计划，尚未连接审批、订单或消息发送等业务系统。

开发期可用 frp 将本机 API 临时接入公网服务器，供其他电脑联调；该能力只存在于开发环境，Linux 生产部署不安装、不启动 frp。地址、证书信任和启动方式见 [frp 公网接入（仅开发）](#frp-公网接入仅开发)，完整运维见 [frp 部署说明](docs/frp.md)。

`docsvc` 的全部运行代码和辅助脚本已合并到 `app/ocr/`、`scripts/ocr/`，共用当前应用入口、Python 3.12、依赖锁和 CI。配置、接口与验收见 [文档加工与 OCR](docs/ocr.md)。工作区原先未跟踪的 `ocr/` 是另一个表单匹配项目，仍保持独立；本次迁移来源为 `../docsvc`。

## 环境与安装

此前本机验收环境为 Apple M5 / 24GB、macOS 26.7.1、Ollama 0.40.5、Qwen3.5 9B Q4_K_M、Metal GPU；这不是所有部署环境的版本要求。项目固定 Python 3.12；`uv.lock` 锁定完整依赖，虚拟环境位于 `.venv/`，与其他 Python 项目隔离。

主要依赖：LangChain `1.4.6`、langchain-core `1.6.12`、langchain-openai `1.7.2`、FastAPI `0.136.3`、Pydantic `2.13.4`。OpenAI SDK 由 LangChain 模型适配器使用；LangSmith 已安装，默认关闭追踪。`create_agent()` 内部依赖 LangGraph 运行时，项目没有自行维护图工作流或引入 Dify。

新机器获取代码：

```zsh
git clone https://github.com/TonyZhang128/agent-dev.git
cd agent-dev
```

仓库克隆后的目录名可以不同（当前本地工作目录为 `qwen-business-dev/`）。以下命令均在项目根目录执行。

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

该优先级针对 **API 实际启动进程**。launchd 后台任务不保证继承当前终端临时 `export` 的所有变量；业务配置优先写入根目录 `.env`，修改后重启 API。Ollama 的 `OLLAMA_*` 是模型服务进程配置，不由业务 `Settings` 加载，需要在它的实际启动环境中设置。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI 兼容模型 API，包含 `/v1` |
| `LLM_MODEL` | `qwen3.5:9b-q4_K_M` | 服务端模型名称 |
| `LLM_API_KEY` | `ollama` | Ollama 占位值；远端服务按需填写真实 key |
| `LLM_TIMEOUT_SECONDS` | `180` | 本地模型单次调用超时；启用回退时总预算再加回退超时 |
| `LLM_MAX_TOKENS` | `2048` | 模型输出长度限制 |
| `LLM_CONTEXT_TOKENS` | `8192` | 实际模型服务的上下文容量，含输入和输出 |
| `LLM_CONTEXT_MARGIN_TOKENS` | `256` | 历史裁剪预算额外余量 |
| `CONVERSATION_MAX_INPUT_CHARACTERS` | `1000000` | 历史及序列化当前输入总字符上限，超出返回422 |
| `LLM_REASONING_EFFORT` | `none` | 关闭当前 Qwen 服务的思考输出；不支持的服务可设为空 |
| `LLM_FALLBACK_BASE_URL` | `https://api.deepseek.com` | 本地 Ollama/vLLM 调用失败时的云端 OpenAI 兼容地址 |
| `LLM_FALLBACK_MODEL` | `deepseek-flash` | 回退模型名称 |
| `LLM_FALLBACK_API_KEY` | 空 | 回退密钥；留空即关闭回退 |
| `LLM_FALLBACK_TIMEOUT_SECONDS` | `60` | 回退调用超时，叠加在 `LLM_TIMEOUT_SECONDS` 之上 |
| `LLM_FALLBACK_REASONING_EFFORT` | `none` | 关闭回退模型思考；不支持的服务可设为空 |
| `AGENT_RECURSION_LIMIT` | `8` | Agent 运行步数上限，包含工具调用循环 |
| `LANGSMITH_TRACING` | `false` | 是否开启 LangSmith 追踪 |
| `TEMPLATES_ROOT` | `data/ocr/templates` | 模板 JSON：forms、layouts、refs |
| `ADMIN_ROOT` | `data/ocr/admin` | 管理端资料目录（优先查找 PDF/Excel） |
| `ASSET_ROOT` | `data/ocr/assets` | 规范 PDF/Excel 资料目录 |
| `PROJECTS_ROOT` | `data/ocr/projects` | 与 Java 共用的业务数据池，限制文件读写边界 |

云端回退默认关闭：只有提供非空 `LLM_FALLBACK_API_KEY` 时才启用。启用后，本地 Ollama/vLLM 的模型调用因连接失败、超时或上游 HTTP 错误抛出异常时，本次调用改用回退模型重试一次，总预算为 `LLM_TIMEOUT_SECONDS + LLM_FALLBACK_TIMEOUT_SECONDS`。回退不重试已返回但未通过 Schema 校验的输出，`/ready` 仍只检查本地模型。DeepSeek 不支持严格 `json_schema`，回退时改用 JSON 模式并继续用 Pydantic 校验，不会退回宽松文本解析。启用回退意味着业务输入会发送到云端，需按数据合规要求决定。

开启 LangSmith 时，还需在进程环境提供其凭据；追踪可能包含业务输入和模型输出。项目默认不会上传追踪。

OCR 相对路径均以仓库根目录解析。没有模板时仍可启动智能体；模板接口返回 `503` 提示配置资源。已有 daolu_v6 资料的本机配置示例见 [OCR 路径配置](docs/ocr.md#路径配置)。模板和业务文件不随代码迁移或提交。

Mac 后台运行：

```zsh
zsh scripts/dev/services.sh start
zsh scripts/dev/services.sh status
# 修改代码或 .env 后：
zsh scripts/dev/services.sh restart-api
# 停止本项目注册的 frpc、API、Ollama 任务：
zsh scripts/dev/services.sh stop
```

脚本按需注册 `local.highway-agent.ollama`、`local.highway-agent.api` 用户会话任务，复用已运行的服务，不修改 shell profile。任务持续到停止或退出登录；重新登录后运行 `start`。日志在 `.logs/*-service.*.log`。普通 `start` 不启动公网隧道；仅开发联调需要时单独执行 `start-frpc`，`stop` 会先停止本项目注册的 frpc，再处理 API/Ollama。

其他方式启动的进程不会被脚本停止。若 `restart-api` 提示端口 8309 被占用，说明尚未完成当前代码的重启部署；应确认进程归属并通过原启动方式管理，不直接杀进程。临时回环端口上的验证也不代表端口 8309 已更新。

前台开发时，先停止本项目后台任务，再在两个终端分别执行：

```zsh
zsh scripts/dev/start-ollama.sh
```

```zsh
zsh scripts/dev/start-api.sh --reload
```

如 Ollama 已由其他方式启动，直接复用。默认 Ollama 上下文 `8192`、单模型、单并发；Apple Silicon 的 GPU 由 Ollama 自动选择，使用 `ollama ps` 查看 `PROCESSOR` 列。不要同时在端口 8309 启动前台和后台 API。

需要断点调试时，可使用本机 `.vscode/launch.json`（该目录不纳入 Git）：

- 选择 `Debug API (launch)`，由 VS Code 直接启动并调试；
- 或先执行 `zsh scripts/dev/services.sh debug-api`，后台启动带 debugpy 的 API，再选择 `Debug API (attach)`；
- 前台调试也可执行 `zsh scripts/dev/start-api.sh --debug`。

`start-api.sh --debug` 和 `debug-api` 默认监听 `127.0.0.1:5678`，不支持 `--reload`；VS Code 的 launch 配置不需要该端口。执行普通 `zsh scripts/dev/services.sh restart-api` 会恢复非调试启动。

## frp 公网接入（仅开发）

frp 隧道只用于开发联调：把 Mac 本机 API 临时暴露给其他电脑。它不属于上线能力，Linux 生产部署不安装、不启动 frpc/frps，也不复制 `config/dev/frp/` 或 `.secrets/frp/`。生产对外入口由实际部署环境单独设计和配置。

开发期公网入口为 `https://107.182.190.191:8443`，Swagger 为 `/docs`；是否在线取决于本机 API、frpc 和服务器状态。frpc 主动连接 `107.182.190.191:7000`，将本机 `127.0.0.1:8309` 转发到服务端回环端口 `18000`，再由服务器 Caddy 提供 HTTPS。主应用没有自定义身份认证，调用方的 `user_id`、`session_id` 不是权限凭据；公网隧道本身也不增加认证。

HTTPS 使用私有 CA。调用方需取得 `.secrets/frp/ca.crt` 并配置证书信任，勿分发 CA 私钥或隧道 token。示例：

```zsh
curl --cacert ./ca.crt -fsS https://107.182.190.191:8443/health
# 需本机 API 已启动；仅管理本项目注册的隧道任务
zsh scripts/dev/services.sh start-frpc
zsh scripts/dev/services.sh stop-frpc
zsh scripts/dev/services.sh restart-frpc
```

隧道配置在 `config/dev/frp/`，凭据在 Git 忽略的 `.secrets/frp/`，日志在 `.logs/frpc-service.*.log`。服务端文件、跨电脑调用示例和验收边界见 [frp 部署说明](docs/frp.md)。

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

## 用户与会话

所有业务请求必须提供 `user_id`、`session_id`（非空字符串，各最多128字符）。意图识别和聊天还必须提供 `history`，首轮为 `[]`；日志不接收历史。旧调用方必须补齐字段，成功响应结构不变。

调用方传入当前会话全部历史；服务端按每次调用的系统提示词、Schema、输出预留和上下文容量，以保守UTF-8字节估算裁剪最早完整回合，不修改原始历史，不持久保存会话。精确token数量取决于模型，估算可能提前裁剪；`LLM_CONTEXT_TOKENS` 必须与实际服务配置一致。身份字段作为 LangChain 调用元数据传递，不送入模型提示词，不代表完成身份认证。详细契约和边界见 [用户与会话说明](docs/sessions.md)。

## 调用与验证

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/health
curl --noproxy '*' -fsS http://127.0.0.1:8309/ready
uv run --locked python -c 'import json; from pathlib import Path; print(json.dumps({"user_id": "example-user", "session_id": "example-session", "content": json.loads(Path("data/log_summary.json").read_text())}, ensure_ascii=False))' | \
  curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/log-summary \
    -H 'Content-Type: application/json' --data-binary @-
curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/intent \
  -H 'Content-Type: application/json' -d '{"user_id":"example-user","session_id":"example-session","history":[],"text":"打开监理日志页面"}'
curl --noproxy '*' -fsS http://127.0.0.1:8309/agents/chat \
  -H 'Content-Type: application/json' -d '{"user_id":"example-user","session_id":"example-session","history":[],"message":"你好，请解释业务智能体。"}'
```

完整字段、返回示例、意图标签及历史消息限制见 [智能体 API 文档](docs/agents-api.md)。`/health` 检查 API 存活，`/ready` 检查上游列出配置模型；只有业务调用会实际推理。

意图识别固定五类：`work_list`（工作列表）、`supervision_log`（监理日志页面）、`image_library`（图片库）、`business_management`（业务管理页面）、`chat`（问候、闲聊或一般交流）。无法确定目标、目标不支持、分数低于 `0.65` 或需要澄清时返回 `unknown`；它是兜底结果，不计入五类。四个页面类别由调用方执行跳转；有效 `chat` 会继续调用 `ChatAgent`，将回答放入现有 `reason` 字段，其余字段不变。聊天回答不受分类理由300字符限制，两次推理共享总超时；低分或需澄清时先回退为 `unknown`，不触发聊天。已取消自定义分类；`intents` 仅兼容省略或 `[]`，非空返回 `422`。调用方统一使用上述五类标签，`unknown` 仅作兜底。

错误状态：输入校验失败 `422`，模型服务不可达 `503`，调用超时 `504`，上游错误、拒绝、截断或不合法结果 `502`。模型失败不会返回伪造的成功结果。

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pytest -v
# 单独运行一个测试文件，或按名称筛选：
uv run --locked pytest tests/test_agents.py -v
uv run --locked pytest -k intent -v
# 需要运行中的 API 和真实模型：
uv run --locked python -m scripts.common.verify_agents
# 额外验证模型直调、ASGI、TCP 接口和 Ollama GPU：
uv run --locked python -m scripts.dev.verify_live
ollama ps
```

自动化测试使用 pytest / pytest-asyncio，运行真实 LangChain Agent 和模拟模型 HTTP 传输，不需要 Ollama、联网或云端凭据；首次安装依赖可能需要联网。测试文件直接位于 `tests/test_*.py`，目前没有 `tests/unit/` 或 `tests/integration/`。测试覆盖脚本分流、生产启动限制、配置保留，以及既有 API、结构化输出、并发标签隔离、消息隔离、超时、异常、工具调用循环、路由注册和共享资源生命周期。真实验收脚本覆盖用户提供的 OCR 输入、完整意图及测试目录中的日志回归集、文字日志和对话，记录写入本地 `verification/agents-live-result.json`；验收记录、日志和缓存不提交 Git。离线与真实模型验收标准见 [意图识别测试说明](docs/intent-testing.md) 和 [日志总结测试说明](docs/log-summary-testing.md)。GitHub Actions 在 Linux 上执行锁定依赖安装、Ruff 和自动化测试，不执行模型下载和真实推理。

业务验收报告的每条 `checks` 记录使用 `request` 保存实际 JSON 输入（含聊天历史），使用 `response` 保存 API 输出，方便逐条核对。

离线检查证明代码和协议行为，不证明正在运行的服务已加载新代码。推理协议、提示词、模型配置或 Agent 流程变更后，应重启目标服务并运行真实验收；纯文档修改不需要重启或推理。可通过 `BUSINESS_API_URL` 指定业务验收目标，但模型直调仍读取当前 `LLM_*`，二者应对应同一部署。

### OpenAPI 快照与当前工作区差异

`tests/test_routing.py` 将完整 OpenAPI 与 `tests/fixtures/api-openapi.json` 比较，覆盖路径、方法、字段、模型、状态码、operationId、tags、summary，以及应用标题和版本，并额外检查重复注册、Router 独立挂载和多应用资源隔离。

当前快照已与主应用同步，记录 `公路工程业务智能体 / 0.1.0`。修改应用标题或版本时必须先确认这项元信息变更，再审查完整差异并同步快照；不要跳过测试、删除元信息断言或自动覆盖整个基线。历史记录中的测试通过数量属于当时版本，当前状态以实际运行结果为准。

## 项目结构与 Agent 开发

```text
app/
  main.py                 # FastAPI 工厂、生命周期、路由与 HTTP 错误处理注册
  api/
    router.py             # 聚合 Router，由主应用统一 include_router
    agents.py             # /agents：日志总结、意图识别、聊天
    system.py             # /health、/ready：存活与模型就绪检查
    ocr.py                # /health/deps、/ocr：识别、简表、填表与表样
    wbs.py                # /wbs/draft：施工图划分初稿
  ocr/                    # 文档加工业务：资源隔离、识别、公式、PDF/Excel、WBS
  http_errors.py          # 输入与模型异常的统一 HTTP 映射、校验详情脱敏
  config.py               # .env 配置与默认值
  schemas.py              # 请求、响应的 Pydantic 模型和校验
  llm.py                  # ChatOpenAI 工厂、共享 HTTP 客户端、模型就绪检查
  errors.py               # 与 HTTP 无关的模型输出错误
  agents/
    runtime.py            # create_agent / ProviderStrategy / 超时 / 运行步数限制
    middleware.py         # 拒绝、截断、空输出及工具响应检查
    base.py               # 通用 BaseAgent 与结构化 StructuredAgent
    history.py            # 请求局部历史、预算及完整回合裁剪
    log_summary.py        # 工程表单 OCR 日志描述（兼容通用日志）
    intent.py             # 固定五类页面导航/交流意图及低分澄清
    chat.py               # 对话消息组织和文本回答
  prompts/
    __init__.py           # 按模块路径加载提示词，不依赖当前工作目录
    log_summary.md        # 各业务独立维护的系统提示词
    intent.md
    chat.md
tests/                    # pytest：API、错误处理、Agent 运行时与脚本测试
  fixtures/               # 日志版本化回归集及当前 OpenAPI 契约快照
data/                     # 用户提供的 OCR 输入、意图评测样例
interfaces/               # 供其他业务对接的固定输出 Schema、示例和说明
  log_summary/
  intent/                 # 四字段固定枚举响应、五类主示例及独立兜底示例
scripts/
  dev/                    # macOS：Homebrew、Ollama、launchd、Metal GPU 验收
  prod/                   # Linux：运行依赖、API、独立 vLLM、NVIDIA 验收
  common/                 # 两种环境共用的业务与模型真实推理验收，按日志/意图/会话组织
  ocr/                    # 原 docsvc 全部模板生成、文档检查和演示工具
  models/                 # 下载 Qwen3.5 GGUF 权重并组装 vLLM 模型目录
  README.md               # 脚本入口和迁移说明
  *.sh / verify_*.py      # 原路径兼容入口
config/dev/frp/          # 仅开发：frpc 配置、专用 frps 和公开访问的 Caddy HTTPS 模板
docs/frp.md              # 仅开发：frp 公网接入、凭据与服务端运维
docs/agents-api.md        # 对外 API 约定和示例
docs/log-summary-testing.md # OCR 日志描述规则及离线、真实模型验收
.github/workflows/ci.yml # Linux 自动检查
Dockerfile               # 生产业务 API 镜像（不含模型服务）
Dockerfile.vllm          # 生产 vLLM 模型服务镜像，基础镜像由构建参数决定
compose.prod.yml         # 生产编排：API + 模型服务，GPU 仅分配模型容器
docker/                  # 容器入口脚本与 compose 变量模板
pyproject.toml / uv.lock  # 直接依赖与完整锁文件
.env.example             # 可提交的配置模板；实际 .env 不提交
AGENTS.md                 # 后续编码 Agent 的仓库约定
CLAUDE.md                 # 引用 AGENTS.md，复用共享规则
```

业务输入说明见 [data/README.md](data/README.md)。`data/log_summary.json` 只保留用户提供的一条 OCR 原始对象，调用时提供 `user_id`、`session_id` 并将该对象放入 `content`；意图样例仍提取单条 `request`。日志固定输出六个必填字段，JSON Schema、输出示例及字段说明见 [interfaces/log_summary/README.md](interfaces/log_summary/README.md)。响应中的 `summary` 为可纳入当日日志的客观中文段落；原有日志回归集独立放在 `tests/fixtures/log_summary_cases.json`。工程 OCR 对象的字段和层级可变化，保留指标、实测值及单位；计划日期不作为实际日期，缺失合格率不推断合格，表单存在不代表已完成检测。当前采用暂行描述规则，正式业务话术待补充，统一维护在 `app/prompts/log_summary.md`。请求外层新增必填用户与会话ID，响应字段保持兼容；content 序列化后仍限 4000 字符。

意图识别固定输出 `intent`、`confidence`、`reason`、`needs_clarification` 四个必填字段。供调用方对接的固定枚举 JSON Schema、分开维护的五类主示例和兜底示例见 [interfaces/intent/README.md](interfaces/intent/README.md)。

调用链：`FastAPI → APIRouter → 业务 Agent → runtime.create_agent → ChatOpenAI → Ollama/vLLM`。结构化业务显式使用 `ProviderStrategy(JSON Schema, strict=True)`，最后再通过 Pydantic 校验；自由对话使用同一 Agent 运行时返回文本。业务代码不直接调用 OpenAI SDK。

路由按业务领域组织在 `app/api/`，通过 `router.py` 聚合；公共路径前缀和文档分组由领域 Router 定义。业务层继续复用 `app/agents/`。共享模型服务和 Agent 在 `main.py` 的 lifespan 中初始化一次，路由通过当前请求的 `request.app.state` 取得资源，关闭时由原生命周期释放 HTTP 客户端。迁移对照和验证见 [APIRouter 审查记录](docs/apirouter-review-2026-10-31.md)。

`main.py` 负责应用装配，不再直接注册业务接口。Router 只接收、校验 HTTP 参数并调用业务层，不导入全局 `app`；Agent 不依赖 HTTP 请求对象。lifespan 使用 `@asynccontextmanager` 和 `AsyncGenerator[None, None]` 类型注解，启动时构建资源，`yield` 期间处理请求，`finally` 释放资源；每个应用工作进程各自持有实例。不要每次请求创建 Agent，也不要把会话状态写入共享实例。当前分层已足够，不需要额外增加只做转发的 Service 层。

`BaseAgent` 统一加载提示词、构建和调用 Agent，子类通过 `messages()` 组织请求消息、`parse_result()` 转换结果。`ChatAgent` 直接继承它，保留文本输出及请求提供的历史；`StructuredAgent` 在此基础上提供 Schema 和 Pydantic 校验，结构化业务仍只需实现 `user_content()`。

新增结构化业务按以下顺序推进：

1. 先确定验收标准和正常、边界、失败用例，增加预期失败的 pytest 测试；在 `app/schemas.py` 定义请求与结果类型，在 `app/prompts/` 添加同名 `.md` 提示词。
2. 在 `app/agents/` 继承 `StructuredAgent[请求类型, 结果类型]`，定义 `name`、`result_type` 和 `user_content()`。日志总结模块可作为起点。
3. 在 `app/main.py` 生命周期中创建实例，在 `app/api/` 对应领域 Router 中增加携带 `response_model` 的路由；新领域创建 Router 并在 `app/api/router.py` 注册。
4. 最小实现使测试通过，覆盖输入校验、模型失败和资源隔离；同步 API 文档、固定输出接口和 README。纯路由整理应对比完整 OpenAPI，确认无非预期变化。

新增 Router 的注册关系示例（已定义对应模块后再添加）：

```python
# app/api/example.py
from fastapi import APIRouter

router = APIRouter(prefix="/example", tags=["示例业务"])
# 在此定义使用已有 Schema 和共享业务实例的 @router.get/post 等入口。
```

```python
# app/api/router.py
from app.api import example

api_router.include_router(example.router)
```

主应用已有 `app.include_router(api_router)`，无需重复注册。代码风格、契约、测试驱动、依赖和提交规则统一见 [开发规范](AGENTS.md)。

意图识别复用固定 Schema 的 Agent，五类定义由服务端维护；请求消息保持隔离，不接受调用方自定义分类。系统提示词修改后需重启 API，以刷新缓存。

需要调用真实业务系统时，用 LangChain `@tool` 定义工具，通过 `build_agent(..., tools=(... ,))` 注册；统一调用 `invoke_agent()` 保留超时、追踪和步数控制。现有业务未注册工具，测试中已覆盖完整工具循环。会改变业务状态的工具应先设计身份、权限、幂等和确认机制，再接入对应业务 API。

目前无服务端持久记忆：聊天历史由调用方传入，每次 Agent 调用使用独立消息状态，未配置 checkpointer。新增会话持久化时需明确用户隔离及存储生命周期。

## Linux + NVIDIA 上线

开发和上线使用同一份业务代码及 `uv.lock`，通过脚本目录与模型配置区分。Linux 不执行 Homebrew、launchd 或 Ollama 安装；vLLM 独立于业务 `.venv`。脚本清单见 [scripts/README.md](scripts/README.md)，后台托管示例见 [Linux 部署说明](docs/deployment-linux.md)。

容器化部署使用两个镜像（业务 API 与 vLLM 模型服务）和 [compose.prod.yml](compose.prod.yml)，权重由宿主机只读挂载；构建、GGUF 基础镜像选择与验收见 [Docker 生产部署](docs/docker.md)。下文是不使用容器的脚本部署方式。

先在 Linux 安装 uv，再准备业务环境：

```bash
bash scripts/prod/setup.sh
```

脚本使用 Python 3.12 和 `uv sync --locked --no-dev`，不安装 dev 依赖、不启动服务、不下载模型。根目录 `.env` 不存在时，从 `scripts/prod/api.env.example` 创建；已有 `.env` 保留。将 `LLM_API_KEY` 的占位值改为模型服务密钥，并确认以下配置：

```dotenv
LLM_BASE_URL=http://127.0.0.1:8001/v1
LLM_MODEL=highway-agent
LLM_API_KEY=your-server-key
LLM_REASONING_EFFORT=
```

按照 [Qwen3.5 vLLM 官方部署说明](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md)，在独立 Python 环境安装经过目标 GPU 验证的固定版本 vLLM。模型权重、CUDA 兼容性、显存、量化及并发参数由目标服务器确定，Mac 的 Ollama 模型不直接复用。

在模型服务的终端设置 `VLLM_BIN`（独立环境可执行文件的绝对路径）、`VLLM_MODEL_PATH`（HF 模型 ID 或本地目录），并通过运行环境注入 `VLLM_API_KEY`，与业务 `LLM_API_KEY` 一致。以下为 Qwen3.5 文本业务启动示例，具体参数需按已安装 vLLM 版本验证：

```bash
export VLLM_BIN=/opt/vllm/bin/vllm
export VLLM_MODEL_PATH=/srv/models/your-model
# 运行环境需已提供 VLLM_API_KEY，勿将真实密钥写入仓库。
bash scripts/prod/start-vllm.sh \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

该入口检查 Linux 和 NVIDIA 驱动，默认监听 `127.0.0.1:8001`，服务名为 `highway-agent`；其他 vLLM 参数原样传入。关闭思考的参数来自 [官方 Qwen3.5 配置说明](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md#configuration-tips)。密钥使用 [vLLM 原生环境变量](https://docs.vllm.ai/en/latest/configuration/env_vars/#environment-variables)传递。

另一终端启动业务 API，模型就绪后执行验收：

```bash
bash scripts/prod/start-api.sh
# 另一个终端：
bash scripts/prod/verify.sh
```

API 默认监听 `127.0.0.1:8309`，拒绝 `--reload`，启动时不安装或同步依赖。上线需由 systemd 等服务管理器托管，详见 [部署说明](docs/deployment-linux.md)。API 与模型可以部署在不同 Linux 主机；API 主机无需 GPU，`start-vllm.sh` 和完整 `verify.sh` 用于 GPU 主机，远端 API 可单独运行通用业务验收。生产部署不包含 frp 公网隧道；frp 只用于 macOS 开发联调。

模型服务需支持 Chat Completions 和原生 JSON Schema 输出；以真实业务验收结果判断具体模型和 vLLM 组合是否可用。验收文件写入 `verification/`，`nvidia-smi` 成功仅确认驱动和设备可见，模型 GPU 占用需另看服务日志和设备监控。本机未执行 Linux GPU 部署。

## Git 版本管理

远端：<https://github.com/TonyZhang128/agent-dev>。提交 `app/`、测试、文档、脚本、依赖锁文件与 CI；忽略 `.env`、虚拟环境、模型、缓存、日志、验收输出和本地 `skills/`。

开始前检查当前分支与工作区，按任务需要创建功能分支，保留已有修改。以下示例展示已跟踪文件的逐块暂存；新增文件应审查后按明确路径单独加入，避免把其他任务内容带入提交：

```zsh
git status --short
git branch --show-current
git switch -c feature/your-agent
# 开发并运行上述检查
git diff --check
git add -p
git diff --cached
git status --short
git commit -m "feat: add a business agent"
git push -u origin feature/your-agent
```

升级依赖时使用 `uv add` 管理声明和锁文件，通过测试后将 `pyproject.toml` 和 `uv.lock` 一起提交，不手改锁文件；LangChain 相关版本固定，升级前核实官方文档和模型服务兼容性。`.env`、`.secrets/`、真实追踪和未跟踪的独立应用不因主项目修改自动提交。

## 官方资料

- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain 结构化输出](https://docs.langchain.com/oss/python/langchain/structured-output)
- [ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)
- [uv 项目管理](https://docs.astral.sh/uv/guides/projects/)
- [Ollama OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)
- [Ollama 结构化输出](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama GPU 支持](https://docs.ollama.com/gpu)
- [vLLM 结构化输出](https://docs.vllm.ai/en/latest/features/structured_outputs/)
