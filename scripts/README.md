# 脚本使用说明

所有脚本可从其他工作目录调用，脚本内部定位仓库根目录。Python 验收以模块方式运行时，先进入仓库根目录。

| 场景 | 入口 | 说明 |
| --- | --- | --- |
| Mac 完整开发安装 | `zsh scripts/dev/setup.sh` | Homebrew/uv、dev 依赖、Ollama 模型、本项目服务及真实验收 |
| Mac 前台 API | `zsh scripts/dev/start-api.sh --reload` | 仅用于 macOS 开发 |
| Mac 前台 Ollama | `zsh scripts/dev/start-ollama.sh` | 复用本机模型存储 |
| Mac 后台任务 | `zsh scripts/dev/services.sh start\|stop\|status\|restart-api` | launchd；仅管理本项目注册任务 |
| Mac 下载网络检查 | `zsh scripts/dev/check-network.sh [proxy_url]` | Homebrew、PyPI、Ollama 连通性 |
| Mac 真实模型及 GPU | `uv run --locked python -m scripts.dev.verify_live` | 通用推理验收 + 本机 Ollama Q4_K_M/GPU 分配 |
| Linux 业务环境安装 | `bash scripts/prod/setup.sh` | Python 3.12、锁定运行依赖、保留已有 `.env` |
| Linux 前台 API | `bash scripts/prod/start-api.sh` | 不同步依赖，拒绝 reload；允许传入其他 uvicorn 参数 |
| Linux 前台模型服务 | `bash scripts/prod/start-vllm.sh [vLLM 参数]` | NVIDIA 检查、独立 vLLM 环境；不安装驱动或模型 |
| Linux 完整验收 | `bash scripts/prod/verify.sh` | NVIDIA 信息、运行中 API 的 8 个案例、通用真实推理 |
| 通用业务验收 | `uv run --locked python -m scripts.common.verify_agents` | Mac/Linux；调用运行中的 API |
| 通用推理验收 | `uv run --locked python -m scripts.common.verify_live` | Mac/Linux；直调 Agent、ASGI、TCP；不检查硬件 |

Linux 完整步骤、配置和后台托管见 [部署说明](../docs/deployment-linux.md)。Mac 步骤见 [项目 README](../README.md#环境与安装)。

`dev/` 使用 zsh，只接受 macOS；`prod/` 使用 Bash，只接受 Linux。Linux API 可以独立运行在没有 GPU 的主机；模型服务和硬件验收需要 NVIDIA。通用 Python 验收不依赖 Homebrew、Ollama 或 `nvidia-smi`。

原有 `scripts/setup.sh`、`services.sh`、`start-api.sh`、`start-ollama.sh`、`check-network.sh` 保留为 Mac 开发兼容入口，不会自动切到生产环境。原有 `python -m scripts.verify_agents` 转到通用验收；`python -m scripts.verify_live` 保留 Mac Ollama/GPU 验收语义。新命令请使用明确的环境目录。

开发安装通过 `uv sync --locked --group dev` 安装 pytest / pytest-asyncio，并使用 `uv run --locked pytest -v` 执行离线单元测试。生产 `--no-dev` 环境不安装这些测试工具。

真实验收会调用模型，报告写入忽略提交的 `verification/`。设置 `BUSINESS_API_URL` 可验证其他地址的 API，模型直调仍读取当前进程及根目录 `.env` 的 `LLM_*` 配置，二者需对应同一部署。Linux 验收使用 `--no-sync --no-dev`，避免安装开发工具或在验收时修改环境。
