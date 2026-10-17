# Qwen 业务智能体开发环境

提供工作日志总结、意图识别、自由对话和业务步骤规划 API。项目使用 Python 3.12、uv、FastAPI、Pydantic 和 OpenAI Python SDK；Mac 连接 Ollama，Linux 可连接 vLLM。

新增三个智能体的请求、返回结构和 curl 示例见 [智能体 API 文档](docs/agents-api.md)：

| 业务 | 接口 |
| --- | --- |
| 根据结构化文字或 JSON 生成工作日志 | `POST /api/agents/log-summary` |
| 识别文字意图，支持自定义候选标签 | `POST /api/agents/intent` |
| 普通对话及携带历史的多轮对话 | `POST /api/agents/chat` |

业务代码在 `app/agents/`，统一模型通信在 `app/llm.py`。原有 `POST /api/business/plan` 保持可用。当前版本为 `0.2.0`，未增加运行依赖。

新增业务验收通过：20 项自动化测试，以及 8 次真实 HTTP / Qwen 调用。覆盖文字与 JSON 日志、自定义与默认意图、不明确意图、普通及多轮对话、原有业务规划回归。实测结果见 [智能体验收记录](verification/agents-live-result.json)。

部署已完成：Ollama 0.40.5 和 FastAPI 已作为 macOS 用户会话服务运行，Qwen3.5 9B Q4_K_M 已下载并验证。真实 SDK 推理、ASGI 路由、实际 HTTP 接口和 GPU 验证全部通过；`ollama ps` 显示 `100% GPU`，上下文为 8192。本次 HTTP 业务请求耗时约 17.44 秒，返回 4 个结构化步骤。完整结果见 [验收状态](verification/STATUS.md)、[验收数据](verification/deployment-result.json) 和 [实际 JSON 返回](verification/http-response.json)。

## 本机检查

- macOS 26.7.1，Apple M5，24GB，Metal 支持。
- 复用 Homebrew 7.0.9、uv 0.11.19、uv 管理的 Python 3.12.13。
- 现有 Python 3.14 和 3.15 环境保持原样。
- Ollama CLI 0.40.5 已通过 Homebrew 安装；未改动 `.zshrc`、系统代理或已有服务配置。
- Homebrew 的 Ollama 配方自动安装 Python 3.15 和 MLX 依赖；业务项目继续使用隔离的 Python 3.12 环境。
- 模型选择 `qwen3.5:9b-q4_K_M`，Q4_K_M 混合 4-bit 量化，下载约 6.6GB。
- 默认 Ollama 上下文设为 8192，单模型、单并发，适合先在 24GB Mac 上验证业务流程。

## 安装与启动

在本机 Terminal/iTerm 中执行。若代理或执行权限限制下载，先参考下方代理和网络检查说明。

```zsh
cd /Users/zinnia/project/project-agent/qwen-business-dev
zsh scripts/setup.sh
zsh scripts/services.sh status
```

`setup.sh` 会检查并复用工具，必要时通过 Homebrew 安装 uv/Ollama，通过 uv 复用或安装 Python 3.12，创建 `.venv`、安装锁定依赖、运行离线测试、复用或启动用户会话服务、拉取模型，并进行真实推理、ASGI 接口、已运行的 TCP HTTP 接口和 GPU 分配验证。完成后两个服务已在后台运行。真实测试需要生成三次业务计划，首次加载可能较慢。

脚本仅在 `.env` 不存在时从 `.env.example` 创建它；不会覆盖已有配置。Ollama 复用默认模型目录 `~/.ollama/models` 和已有模型层；如已设置 `OLLAMA_MODELS`，保留该设置。启动失败时会退出并给出错误，不会删除现有文件。

已有 Ollama 服务会直接复用，其启动参数保持原样。`start-api.sh` 在前台运行，按 Ctrl-C 停止。需要服务在终端命令退出后持续运行时，使用 macOS 用户会话服务：

```zsh
HTTPS_PROXY=http://127.0.0.1:10808 zsh scripts/services.sh start
zsh scripts/services.sh status
# 修改业务代码后，仅重启 API：
zsh scripts/services.sh restart-api
# 停止本项目注册的服务：
zsh scripts/services.sh stop
```

这会注册 `local.qwen-business-dev.ollama` 和 `local.qwen-business-dev.api` 两个用户会话任务；已有服务会复用。日志位于 `.logs/ollama-service.*.log`、`.logs/api-service.*.log`。不会写入 shell profile、创建开机登录项或替换已有服务配置，任务持续到停止或用户退出登录。`stop` 只移除这两个项目任务，不会停止其他方式启动的 Ollama。

重新登录 Mac 后，可用 `zsh scripts/services.sh start` 恢复两个后台服务。如果需要以前台方式开发，先用 `zsh scripts/services.sh stop` 停止本项目后台任务，然后在一个终端执行：

```zsh
zsh scripts/start-ollama.sh
```

再在另一个终端执行 `zsh scripts/start-api.sh`。开发时可追加 `--reload`。使用上述后台服务时，无需同时执行前台启动命令。

## v2rayN 代理

本机 v2rayN 配置记录的本地端口是 `10808`，TUN 已启用。CLI 未读取到系统代理或终端代理环境变量。先在普通终端验证实际连通性：

```zsh
zsh scripts/check-network.sh http://127.0.0.1:10808
```

如直连失败而代理成功，可仅对安装命令设置 HTTPS 代理及本地绕过规则：

```zsh
HTTPS_PROXY=http://127.0.0.1:10808 \
https_proxy=http://127.0.0.1:10808 \
NO_PROXY=localhost,127.0.0.1,::1 \
no_proxy=localhost,127.0.0.1,::1 \
zsh scripts/setup.sh
```

不必改动 `.zshrc`。模型下载由 Ollama 服务进程发起；脚本新启动的服务会继承上述代理。如果复用的 Ollama 服务无法下载，需要在它自己的启动环境中配置代理。`check-network.sh` 的 HTTP 401/403 表示已收到服务端响应，并不等同于下载授权成功。

本次部署初期，受限执行环境的 socket 返回 `PermissionError: Operation not permitted`，端口监听同样被拒绝。在允许扩展执行权限后，Homebrew 和 Qwen 模型清单均返回 HTTP 200，下载及本地服务已正常运行。TUN 连接状况与执行进程的沙箱权限需要分别检查。

## 测试接口

本节演示原有业务规划接口；三个新增业务请参考 [智能体 API 文档](docs/agents-api.md)。

API 启动后，打开 http://127.0.0.1:8000/docs，或执行：

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8000/health
curl --noproxy '*' -fsS http://127.0.0.1:8000/ready
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/business/plan \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"员工提交报销申请后，检查发票是否齐全，齐全则提交部门经理审批，否则通知员工补齐。"}'
```

示意返回（仅展示结构，具体内容由真实模型生成）：

```json
{
  "goal": "处理员工报销申请",
  "steps": [
    {
      "step": 1,
      "action": "检查报销发票是否齐全",
      "responsible_role": "报销受理人员",
      "condition": "收到报销申请",
      "expected_output": "发票完整性检查结果"
    },
    {
      "step": 2,
      "action": "提交部门经理审批",
      "responsible_role": "报销受理人员",
      "condition": "发票齐全",
      "expected_output": "审批申请"
    },
    {
      "step": 3,
      "action": "通知员工补齐发票",
      "responsible_role": "报销受理人员",
      "condition": "发票不齐全",
      "expected_output": "补件通知"
    }
  ],
  "assumptions": ["报销受理人员的实际岗位待企业确认"],
  "questions": []
}
```

`/health` 只检测 API 进程；`/ready` 检查上游服务是否列出配置的模型，不代表已经完成一次推理。业务接口才会实际调用模型。该接口只生成计划，步骤中的 `condition` 表达分支条件，不会执行报销、审批或通知操作。

输入缺失、空白、超出 2000 字符或含多余字段返回 422；服务不可达返回 503；推理超时返回 504；上游错误、截断或 JSON 校验失败返回 502。不会以默认业务计划掩盖模型失败。

## 验证命令

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python -m scripts.verify_live
uv run --locked python -m scripts.verify_agents
ollama show qwen3.5:9b-q4_K_M
ollama ps
```

离线环境可加 `--offline`，例如 `uv sync --locked --offline`。项目已复用本机缓存，不依赖其他项目的虚拟环境。`uv.lock` 包含跨平台 wheel 信息；两个精确版本的编译包元数据记录在 `pyproject.toml`，使本次离线解析可以完成。升级这两个包时应删除对应 `dependency-metadata` 条目，联网重新生成锁文件。

真实验证结果写入 `verification/live-result.json`：`real_inference`、`asgi_api`、`http_api`、`gpu_verified` 和 `passed` 用来区分各层验证。失败同样保留记录。可通过 `BUSINESS_API_URL=http://127.0.0.1:8000 uv run --locked python -m scripts.verify_live` 验证已运行的 API；未指定时脚本在临时本地端口启动并关闭测试 API。

Mac 的 GPU 由 Ollama 通过 Metal 自动选择，无需 CUDA。用 `ollama ps` 查看 PROCESSOR 列，并检查真实测试记录里的 `size_vram` 和 `quantization_level`。本次实测为 `100% GPU`，33/33 层加载到 GPU，模型 GPU 分配约 5.04GB；日志生成速度约 21–22 token/s。最终三次请求分别约 19.09 秒、16.53 秒、17.44 秒。模型默认空闲约 5 分钟后释放资源，下次请求会重新加载。

## 切换 Linux + vLLM

业务 API 与模型服务分开运行。Linux 上先根据 GPU/CUDA 环境按 vLLM 官方文档安装模型服务；不要把 vLLM 加入 Mac 的业务项目依赖。官方 Qwen3.5 部署命令可参考：

```bash
vllm serve Qwen/Qwen3.5-9B \
  --served-model-name qwen-business \
  --host 127.0.0.1 --port 8001 \
  --max-model-len 8192 \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

这是未来部署参考，本机尚未执行。该示例使用 Hugging Face 模型权重，与 Mac 的 Q4_K_M 文件格式及内存需求不同；正式服务器的精度、量化和并发参数需要根据实际显存验证。

在 `.env` 中调整配置，然后重启业务 API：

```dotenv
LLM_BASE_URL=http://127.0.0.1:8001/v1
LLM_MODEL=qwen-business
LLM_API_KEY=your-server-key-or-placeholder
LLM_REASONING_EFFORT=none
```

若模型服务位于另一台主机，将地址换成它的可访问地址。需要认证时填服务端配置的 key。如果某个服务版本不接受 `reasoning_effort`，可设 `LLM_REASONING_EFFORT=`，并在服务端用模板参数关闭思考模式。前台启动时可用环境变量覆盖 `.env`；后台用户会话服务从 `.env` 读取配置，无须改动业务代码。

Linux 业务 API 启动：

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

重新运行相同的接口和真实推理验证，以检查服务端 JSON Schema 兼容性。

## 文件说明

- `app/main.py`：HTTP 路由、生命周期和上游错误处理。
- `app/agents/log_summary.py`：日志总结提示词和业务入口。
- `app/agents/intent.py`：意图分类、默认候选和不确定结果处理。
- `app/agents/chat.py`：对话提示词及本次请求的历史消息组织。
- `app/llm.py`：共享 OpenAI 兼容客户端、结构化及普通文本生成、原有业务规划。
- `app/schemas.py`：四个业务的输入、返回结构和校验规则。
- `app/config.py`：`.env` 配置，API key 使用 `SecretStr`。
- `scripts/`：检查网络、安装、启动及真实推理验证；`verify_agents.py` 验证三个新增业务。
- `tests/test_api.py`：真实 SDK + 模拟 HTTP 传输的离线测试。
- `tests/test_agents.py`：三个新增业务的接口、校验、历史隔离和错误处理测试。
- `docs/agents-api.md`：三个新增智能体的接口约定、调用示例和开发位置。
- `verification/`：本次实际验证结果和后续真实验证记录。

## 官方资料

- [Ollama Qwen3.5 量化标签](https://registry.ollama.com/library/qwen3.5/tags)
- [Ollama Metal 支持](https://docs.ollama.com/gpu)
- [Ollama OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)
- [Ollama 结构化输出](https://docs.ollama.com/capabilities/structured-outputs)
- [Homebrew Ollama](https://formulae.brew.sh/formula/ollama)
- [vLLM Qwen3.5 部署](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md)
- [vLLM JSON Schema 输出](https://docs.vllm.ai/en/latest/features/structured_outputs/)
