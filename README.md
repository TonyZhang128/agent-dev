# 公路工程业务智能体层

为公路工程软件系统提供智能体与 OCR 识别算法服务，支撑数据智采、业务管理和归档组卷等场景。上层系统通过统一的 FastAPI HTTP 接口调用，算法层负责意图理解、内容生成和照片识别。

智能体通过 OpenAI 兼容协议调用独立模型推理服务，OCR 在算法服务进程内按需加载识别引擎。当前不持久保存会话，聊天历史由调用方提供；尚未接入审批、订单修改或通知发送等外部业务动作。

对外服务名称为 **公路工程智能算法服务**，简称“算法服务”，程序与容器标识统一为 `agent-service`；独立的 Ollama／vLLM 称为“模型推理服务”。

## 1、安装与部署

### 1.1、macOS 本机开发

默认已安装 Homebrew， Git。
在终端获取代码并执行[环境安装脚本](scripts/dev/setup.sh) 并进行如下配置：

- 安装 LLM 推理引擎 Ollama，拉取 qwen3.5:9b-q4_K_M
- 创建环境变量 `cp -n .env.example .env`
- 创建 Python 环境 `uv sync --locked --group dev --extra ocr-cpu`

**注意：上述 安装/配置 不会重复设置。即本地已有 Ollama 不会重复下载，已有 `.env` 不会重复配置！**

```zsh
git clone https://github.com/TonyZhang128/agent-dev.git
cd agent-dev
zsh scripts/dev/setup.sh
```

环境配置完成后，在项目根目录后台启动 Ollama 和算法服务：

```zsh
zsh scripts/dev/services.sh start
zsh scripts/dev/services.sh status
```

macOS 系统的详细开发、断点调试和排障见 [macOS 本地开发](docs/macos-dev.md)。

### 1.2、Windows 本机开发

准备 Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和 [Ollama for Windows](https://docs.ollama.com/windows)，在 PowerShell 中执行：

```powershell
git clone https://github.com/TonyZhang128/agent-dev.git
cd agent-dev
$env:UV_CACHE_DIR = "$PWD/.cache/uv"
uv python install 3.12
uv sync --locked --group dev --extra ocr-cpu # 默认cpu推理，可替换为ocr-gpu
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

环境配置完成后，退出托盘中已有的 Ollama，在一个 PowerShell 窗口启动模型推理服务：

```powershell
$env:OLLAMA_CONTEXT_LENGTH = "8192"
ollama serve
```

另开 PowerShell，在项目根目录拉取模型（首次需要）并启动算法服务：

```powershell
ollama pull qwen3.5:9b-q4_K_M
uv run --locked --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8309 --reload
```

Windows 的设备配置与运行检查见 [配置说明](docs/configuration.md) 和 [测试与验收](docs/testing.md)；上述步骤尚未进行 Windows 实机验收。

### 1.3、本机配置与访问

Mac 与 Windows 均使用根目录 `.env`，首次安装从 [.env.example](.env.example) 创建。默认配置如下；已有配置请核对，不要覆盖：

```dotenv
LLM_BASE_URL=http://127.0.0.1:11434/v1 # LLM 推理引擎地址，Ollama默认11434，vLLM默认8001
LLM_MODEL=qwen3.5:9b-q4_K_M
LLM_API_KEY=ollama
OCR_DEVICE=cpu # OCR推理设备，默认cpu，win/linux可选cuda
```

算法服务默认监听 `127.0.0.1:8309`，Swagger UI 为 <http://127.0.0.1:8309/docs>。`/health` 检查进程存活，`/ready` 检查模型列表，`/diagnostics` 检查本地依赖与 OCR 资源；这些检查均不执行推理。实际业务与识别效果按 [测试与验收](docs/testing.md) 分别验证，完整变量见 [配置说明](docs/configuration.md)。

### 1.4、Docker 部署

无 GPU 主机、OCR 仅用 CPU 且 LLM 调用云端时，使用独立的
[Dockerfile.cpu](Dockerfile.cpu)、[compose.cpu.yml](compose.cpu.yml) 和
[docker/cpu.env.example](docker/cpu.env.example)，步骤见
[CPU OCR + 云端 LLM](docs/docker.md#10cpu-ocr--云端-llm)。该方案不部署本地 LLM。

生产编排面向 **Linux x86_64 + NVIDIA GPU**，算法服务与模型推理服务分别运行在独立容器中。先按 [Docker 部署说明](docs/docker.md) 准备驱动、Container Toolkit、模型权重和数据目录，再在仓库根目录创建配置：

```bash
test -f docker/prod.env || cp docker/env.example docker/prod.env
chmod 600 docker/prod.env
```

编辑 `docker/prod.env`，核对模型镜像、权重路径、数据目录、OCR 设备，并设置实际 `VLLM_API_KEY`；已有文件保留。配置完成后构建并启动：

```bash
docker compose --env-file docker/prod.env -f compose.prod.yml config --quiet
docker compose --env-file docker/prod.env -f compose.prod.yml build
docker compose --env-file docker/prod.env -f compose.prod.yml up -d
docker compose --env-file docker/prod.env -f compose.prod.yml ps
```

**注意：上述docker命令需要在 agent-dev 根目录执行。若要单独构建算法服务或模型推理服务，或者是在daolu_v6构建docker服务，详见[Docker 部署说明](docs/docker.md)**
默认算法服务地址仍为 `http://127.0.0.1:8309`，模型加载后检查 `/ready`，再分别验收 Agent 与 OCR。权重迁移、离线构建、GPU 与升级步骤见 [Docker 部署说明](docs/docker.md)；不使用容器时见 [Linux 部署](docs/deployment-linux.md)。

## 2、技术架构与主要功能

```text
上层业务系统
    │ HTTP / JSON
    ▼
智能算法服务（FastAPI）
    ├── 智能体：日志生成 / 意图识别 / 对话
    │       └── LangChain → OpenAI 兼容模型推理服务
    └── OCR：表格定位 / 模板对齐 / 整页识别 / 字段提取
            ├── RapidOCR + ONNX Runtime
            └── JournalAgent 生成施工、巡视和旁站分栏记录
```

- 运行环境：Python 3.12，使用 uv 和 `uv.lock` 管理依赖。
- 服务与智能体：FastAPI、Pydantic、LangChain；主要图像处理使用 OpenCV、PyMuPDF。
- 本机开发（macOS／Windows）：Ollama，默认 Qwen3.5 9B Q4_K_M；OCR 默认使用 CPU。
- Linux 生产：独立 vLLM 服务；OCR 可选 NVIDIA GPU 或 CPU。业务环境与模型推理服务环境分离。

模块职责、资源生命周期和扩展方式见 [架构与扩展](docs/architecture.md)。

主要功能如下：

| 类别 | 能力 | 业务用途 |
| --- | --- | --- |
| 智能体 | 工程日志生成 | 将工程表单 OCR JSON 或文字整理为日志段落与结构化字段，保留事实、数值和单位 |
| 智能体 | 业务端意图识别 | 根据消息、当前页面和上下文识别页面／功能，支持澄清与聊天分流 |
| 智能体 | 归档端意图识别 | 独立的扁平意图分类，目前使用 A–D 占位分类与 unknown |
| 智能体 | 自由对话 | 根据调用方提供的历史回答当前问题 |
| OCR | 监理日记识别 | 从数据池照片或 base64 图片定位表格、整页识别并提取业务字段，基于原始记录生成施工、巡视四项和旁站五项；支持完整处理、纯 OCR 和业务生成三个入口 |

监理日记生成配置为 `JOURNAL_TIMEOUT_SECONDS`（默认 30）和 `JOURNAL_CONCURRENCY`（默认 1）；部署时需迁移旧 `MAIN_WORK_SPLIT_*` 配置，本机 `.env` 不自动覆盖。

接口清单、请求响应与契约状态统一见 [接口文档](interfaces/README.md)。

## 3、项目结构

```text
app/
  main.py          # 应用工厂、生命周期与共享资源
  api/             # 系统、智能体和 OCR 路由
  agents/          # 智能体业务与统一运行时
  prompts/         # 系统提示词
  schemas/         # 请求、响应与输入校验
  ocr/             # OCR 引擎资源、监理日记识别与模板
  resources/intent/ # 业务页面／功能目录源数据
interfaces/        # 对外接口契约、待确认草案与业务指南
docs/              # 开发、配置、架构、部署及算法专题
scripts/           # 开发运维、模型准备、契约检查与验收工具
tests/             # 离线测试及版本化回归数据
data/              # 本地业务样本与 OCR 数据池，内容按 Git 忽略规则管理
docker/            # 容器入口与生产变量模板
```

依赖声明见 [pyproject.toml](pyproject.toml)，生产编排见 [compose.prod.yml](compose.prod.yml)。

## 4、开发与验证

在项目根目录使用 Python 3.12 项目环境执行常用检查。以下为 macOS 命令；Windows PowerShell 将首行替换为 `$env:UV_CACHE_DIR = "$PWD/.cache/uv"`，其余 uv 命令相同：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev --extra ocr-cpu
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pyright
uv run --locked python -m scripts.docs.check_openapi
uv run --locked pytest -v --cov=app --cov-fail-under=85
```

`ocr-cpu` 与 `ocr-gpu` 互斥，GPU 开发环境改用对应 extra；重新同步时必须带上所需 extra。

离线测试不依赖运行中的模型推理服务。修改提示词、模型配置、推理协议或 Agent 流程后，还需重启目标算法服务并执行真实业务验收；Agent 与 OCR 分别验证。具体命令、样本和验收边界见 [测试与验收](docs/testing.md)。

开发与 AI 协作规范统一见 [AGENTS.md](AGENTS.md)。新增或变更接口须遵循 API-First 流程，用户确认契约后再实现；运行时 Swagger 是实现投影，不能替代正式契约。

## 5、文档导航

| 场景 | 文档 |
| --- | --- |
| macOS 安装、启动、调试、网络排障 | [macOS 本地开发](docs/macos-dev.md) |
| 模型、回退、OCR 设备与数据路径配置 | [配置说明](docs/configuration.md) |
| 理解模块、维护 Agent 与扩展能力 | [架构与扩展](docs/architecture.md) |
| 离线检查、真实模型与照片验收 | [测试与验收](docs/testing.md) |
| 系统接口对接 | [接口文档与契约](interfaces/README.md) |
| 维护 OCR 与模板 | [OCR 说明](docs/ocr.md)、[监理日记模板识别](docs/journal-template-recognition.md) |
| 生产部署 | [Docker](docs/docker.md)、[Linux 非容器](docs/deployment-linux.md) |
| 查找脚本与详细专题 | [脚本索引](scripts/README.md)、[完整文档索引](docs/README.md) |
