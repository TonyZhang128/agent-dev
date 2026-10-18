# Linux + NVIDIA 部署

业务 API 与模型服务使用两个独立环境。业务项目由 uv 管理 Python 3.12 和锁定依赖；vLLM 由服务器管理员按 NVIDIA GPU、驱动和 CUDA 兼容性安装到单独环境。本仓库不自动安装系统驱动或为未知硬件选择 vLLM 版本。

## 1. 准备业务 API

在目标 Linux 检查 `uv --version`，缺少时按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)准备工具，然后在仓库根目录执行：

```bash
bash scripts/prod/setup.sh
```

安装固定依赖的命令为 `uv sync --locked --no-dev`。无根目录 `.env` 时复制生产模板，权限为 `600`；已有 `.env` 不覆盖。编辑 `.env`，至少确认：

```dotenv
LLM_BASE_URL=http://127.0.0.1:8001/v1
LLM_MODEL=qwen-business
LLM_API_KEY=your-server-key
LLM_REASONING_EFFORT=
```

其他变量与开发共用同一 `Settings`，见 README。进程变量优先于 `.env`。生产 API 入口会拒绝 Ollama 开发地址/模型和未修改的密钥占位符；请勿直接复制 Mac 的 `.env` 上线。

## 2. 准备独立模型服务

先通过 `nvidia-smi` 确认设备及驱动可见。参考 [vLLM GPU 安装说明](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)和 [Qwen3.5 部署配方](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md)，在业务项目之外安装适配目标 GPU 的固定版本，并准备兼容权重。显存、量化、上下文、张量并行参数需按服务器确定。

模型入口只读取进程变量，不会将业务 `.env` 当作 Shell 脚本加载：

| 变量 | 要求 |
| --- | --- |
| `VLLM_BIN` | 必填，独立 vLLM 可执行文件的绝对路径，例如 `/opt/vllm/bin/vllm` |
| `VLLM_MODEL_PATH` | 必填，本地模型目录或 Hugging Face 模型 ID |
| `VLLM_API_KEY` | 必填，由运行环境注入，与业务 `LLM_API_KEY` 一致 |
| `CUDA_VISIBLE_DEVICES` | 可选，vLLM 原生变量，选择可见 GPU |

这些变量属于部署脚本/vLLM，不是应用 `Settings`。`VLLM_API_KEY` 是 [vLLM 原生鉴权变量](https://docs.vllm.ai/en/latest/configuration/env_vars/)，脚本不把密钥拼入命令参数。

```bash
export VLLM_BIN=/opt/vllm/bin/vllm
export VLLM_MODEL_PATH=/srv/models/your-qwen-model
# VLLM_API_KEY 由运行环境注入。
bash scripts/prod/start-vllm.sh \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

此 Qwen3.5 示例使用 [官方关闭思考配置](https://github.com/vllm-project/recipes/blob/main/Qwen/Qwen3.5.md#configuration-tips)，需匹配所安装 vLLM 版本。默认监听 `127.0.0.1:8001`、模型名称 `qwen-business`。额外 CLI 参数原样传递；修改端口或 `--served-model-name` 后必须同步修改业务 `.env`。不要使用 `--api-key` 传入真实密钥。

## 3. 启动及托管 API

```bash
bash scripts/prod/start-api.sh
```

默认 `127.0.0.1:8000`，可追加 uvicorn 参数，例如 `--workers 2`。每个 worker 有独立模型客户端，先验证模型并发容量。生产入口禁止 `--reload`，启动时使用 `uv run --locked --no-sync --no-dev`。升级代码或 `.env` 后由服务管理器重启 API。

后台托管可采用 systemd。以下示例假定代码在 `/opt/agent-dev`、运行用户为 `qwen`、uv 位于 `/home/qwen/.local/bin`，安装前替换为服务器实际路径：

```ini
# /etc/systemd/system/qwen-business-api.service
[Unit]
Description=Qwen business API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=qwen
WorkingDirectory=/opt/agent-dev
Environment="PATH=/home/qwen/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/bin/bash /opt/agent-dev/scripts/prod/start-api.sh
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
UMask=0077

[Install]
WantedBy=multi-user.target
```

运行用户需要读取代码、`.env` 和 `.venv`，并能写入项目 `.cache/uv`；在该用户下先完成 `setup.sh`。模型服务也可由独立 systemd 单元托管，其 `ExecStart` 调用 `start-vllm.sh` 并带上经过验证的 CLI 参数；通过权限受控的 `EnvironmentFile` 或部署平台注入上述 `VLLM_*` 变量。模型进程可使用单独用户，不依赖 API 虚拟环境。

在 Linux 安装并审核单元文件后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qwen-business-api
sudo systemctl restart qwen-business-api
sudo systemctl status qwen-business-api
journalctl -u qwen-business-api -n 100 --no-pager
```

模型服务可晚于 API 就绪，`/health` 仍检查进程存活，`/ready` 返回模型可用状态。默认仅绑定回环地址；如 API 和模型分机部署，配置模型监听地址、网络访问限制及业务 `LLM_BASE_URL`，外部业务入口按部署平台配置鉴权和 TLS。

## 4. 真实验收

API 与模型均运行后，在拥有 NVIDIA 设备的部署主机执行：

```bash
bash scripts/prod/verify.sh
```

输出在 `verification/`：`agents-live-result.json`（8 个业务案例）、`live-result.json`（Agent 直调、ASGI、TCP）、`nvidia-smi.txt`（驱动/显存信息）。验证不会调用 Ollama。硬件可见不等于模型已使用 GPU，结合 `nvidia-smi` 进程显存及 vLLM 日志确认实际分配。

API 主机没有 GPU 时，在该主机执行通用业务验收：

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked --no-sync --no-dev python -m scripts.common.verify_agents
```

Linux CI 只执行离线测试和静态检查；不安装 vLLM、不下载模型、不执行真实推理。Mac 上的离线测试只能验证脚本分流、参数传递及错误路径，不能代替 Linux + NVIDIA 实机验收。
