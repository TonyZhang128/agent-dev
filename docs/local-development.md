# 本地开发

本文面向 macOS 开发维护。项目使用 Python 3.12、uv、Ollama 和 CPU 版 OCR；Linux 生产见 [部署说明](deployment-linux.md)，应用变量见 [配置说明](configuration.md)。以下命令均在仓库根目录执行。

## 首次安装

先准备 Homebrew，再获取代码并执行安装脚本：

```zsh
git clone https://github.com/TonyZhang128/agent-dev.git
cd agent-dev
zsh scripts/dev/setup.sh
zsh scripts/dev/services.sh status
```

脚本复用已有工具，缺少 uv 或 Ollama 时通过 Homebrew 安装；通过 uv 准备 Python 3.12、锁定依赖及开发工具，使用互斥 extra `ocr-cpu` 安装 ONNX Runtime。已有 `.env` 保留，不存在时复制 `.env.example`。

随后脚本执行离线测试、启动本项目用户会话服务、拉取默认模型，并运行真实推理检查。首次模型下载耗时取决于网络与缓存；安装完成不表示 OCR 照片内容已通过验收，参见 [测试与验收](testing.md)。

模型通常保存在 `~/.ollama/models`；显式配置的 `OLLAMA_MODELS` 由实际 Ollama 启动环境决定。Python 虚拟环境为仓库 `.venv/`，不使用系统 Python 或其他项目环境。

## 已有工具与模型

已安装 uv、Ollama 且模型已准备好时，只安装项目依赖：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev --extra ocr-cpu
test -f .env || cp .env.example .env
```

缓存齐全时 uv 命令可追加 `--offline`。`ocr-cpu` 和 `ocr-gpu` 不能同时安装；不带 extra 的 `uv sync` 会移除已装的 OCR 运行时。依赖管理及互斥关系见 [pyproject.toml](../pyproject.toml)。

## 后台运行

```zsh
zsh scripts/dev/services.sh start
zsh scripts/dev/services.sh status
# 修改代码或 .env 后更新算法服务。
zsh scripts/dev/services.sh restart-api
# 停止本项目注册的算法服务和 Ollama 任务。
zsh scripts/dev/services.sh stop
```

脚本按需注册 `local.highway-agent.ollama` 和 `local.highway-agent.agent-service` launchd 用户会话任务，复用已运行服务，不修改 shell profile。任务持续到停止或退出登录，重新登录后运行 `start`。

旧版本使用 `local.highway-agent.api`。升级前可用旧版本脚本停止本项目任务；升级后若旧任务仍存在，确认归属后用 `launchctl remove local.highway-agent.api` 注销，再运行 `start`。新脚本不会自动接管旧标签，保留已有端口占用进程。

算法服务默认地址 `http://127.0.0.1:8309`，日志在 `.logs/agent-service.out.log` 和 `.logs/agent-service.err.log`；Ollama 日志仍为 `.logs/ollama-service.*.log`。launchd 不保证继承当前终端的临时变量，持久业务配置写入根目录 `.env` 并重启算法服务；Ollama 自身的变量要在其实际启动环境中设置。

脚本不会停止其他方式启动的进程。若重启时提示端口占用，先确认进程归属并通过原启动方式管理；临时端口验证不表示默认端口的服务已更新。

## 前台开发

先停止本项目后台任务，再在两个终端分别启动模型推理服务和算法服务；已有 Ollama 服务可直接复用：

```zsh
zsh scripts/dev/start-ollama.sh
```

```zsh
zsh scripts/dev/start-api.sh --reload
```

Ollama 脚本默认上下文为 8192、单模型、单并发。Apple Silicon GPU 由 Ollama 自动选择，可用 `ollama ps` 的 `PROCESSOR` 列检查。前后台算法服务 不要同时占用端口 8309。

## 断点调试

前台启动 debugpy：

```zsh
zsh scripts/dev/start-api.sh --debug
```

后台调试：

```zsh
zsh scripts/dev/services.sh debug-api
```

默认监听 `127.0.0.1:5678`，在 VS Code 配置 Python Attach 连接该地址。调试模式不支持 `--reload`，改代码后重新启动调试；`zsh scripts/dev/services.sh restart-api` 恢复普通后台算法服务。

若本机已有 `.vscode/launch.json`，可选 `Debug API (launch)` 直接启动，或配合上述命令选择 `Debug API (attach)`。本地 `.vscode/` 不纳入 Git，新环境需自行配置，解释器选择项目 Python 3.12 `.venv`。

## 代理与下载排障

将下面示例端口替换为实际代理配置。即使开启 TUN，也应检查终端和模型推理服务的下载连通性：

```zsh
zsh scripts/dev/check-network.sh http://127.0.0.1:10808
HTTPS_PROXY=http://127.0.0.1:10808 \
https_proxy=http://127.0.0.1:10808 \
NO_PROXY=localhost,127.0.0.1,::1 \
no_proxy=localhost,127.0.0.1,::1 \
zsh scripts/dev/setup.sh
```

模型下载由 Ollama 服务进程发起，新启动服务继承的代理与已运行服务可能不同；复用服务时需检查其实际网络环境。安装命令不会修改 `.zshrc`。HTTP 401/403 仅表示收到响应，不能证明有下载权限。

## 检查服务

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/health
curl --noproxy '*' -fsS http://127.0.0.1:8309/ready
curl --noproxy '*' -fsS http://127.0.0.1:8309/diagnostics
```

Swagger UI 为 <http://127.0.0.1:8309/docs>，ReDoc 为 `/redoc`，运行时 OpenAPI 为 `/openapi.json`。接口调试示例从 [接口索引](../interfaces/README.md) 进入，完整脚本入口见 [脚本说明](../scripts/README.md)。

健康、就绪和静态诊断均不能证明真实业务质量；修改推理流程后按 [测试与验收](testing.md) 运行对应检查。纯文档修改不需要重启服务或调用模型。

uv 的环境与依赖管理参考 [官方项目指南](https://docs.astral.sh/uv/guides/projects/)。
