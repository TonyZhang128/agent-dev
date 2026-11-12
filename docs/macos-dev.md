# macOS 本地开发

本文面向 macOS 开发维护。项目使用 Python 3.12、uv、Ollama 和 CPU 版 OCR；应用变量见 [配置说明](configuration.md)。以下命令均在 agent-dev 仓库根目录执行。

## 1、首次安装

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

## 2、已有工具与模型

已安装 uv、Ollama 且模型已准备好时，只安装项目依赖。例如同步协作组代码，只需要允许以下命令：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev --extra ocr-cpu
test -f .env || cp .env.example .env
```

缓存齐全时 uv 命令可追加 `--offline`。`ocr-cpu` 和 `ocr-gpu` 不能同时安装；不带 extra 的 `uv sync` 会移除已装的 OCR 运行时。依赖管理及互斥关系见 [pyproject.toml](../pyproject.toml)。

## 3、后台运行

```zsh
zsh scripts/dev/services.sh start
zsh scripts/dev/services.sh status
# 修改代码或 .env 后更新算法服务。
zsh scripts/dev/services.sh restart-api
# 停止本项目注册的算法服务和 Ollama 任务。
zsh scripts/dev/services.sh stop
```

脚本按需注册 `local.highway-agent.ollama` 和 `local.highway-agent.agent-service` launchd 用户会话任务，复用已运行服务，不修改 shell profile。任务持续到停止或退出登录，重新登录后运行 `start`。

算法服务默认地址 `http://127.0.0.1:8309`，日志在 `.logs/agent-service.out.log` 和 `.logs/agent-service.err.log`；Ollama 日志仍为 `.logs/ollama-service.*.log`。launchd 不保证继承当前终端的临时变量，持久业务配置写入根目录 `.env` 并重启算法服务；Ollama 自身的变量要在其实际启动环境中设置。

脚本不会停止其他方式启动的进程。若重启时提示端口占用，先确认进程归属并通过原启动方式管理；临时端口验证不表示默认端口的服务已更新。

## 4、前台开发

先停止本项目后台任务，再在两个终端分别启动模型推理服务和算法服务；已有 Ollama 服务可直接复用：

```zsh
zsh scripts/dev/start-ollama.sh
```

```zsh
zsh scripts/dev/start-api.sh --reload
```

Ollama 脚本默认上下文为 8192、单模型、单并发。Apple Silicon GPU 由 Ollama 自动选择，可用 `ollama ps` 的 `PROCESSOR` 列检查。前后台算法服务 不要同时占用端口 8309。

## 5、断点调试

安装 VS Code 的 **Python** 和 **Python Debugger** 扩展，配置根目录的 [`.vscode/launch.json`](../.vscode/launch.json)，解释器使用 `.venv/bin/python`。`.vscode/` 不纳入 Git，新环境需自行配置。调试前确保模型推理服务可用，并在 Python 代码中设置断点。

### 5.1、Launch：由 VS Code 启动调试

1. 通过原启动方式停止占用 `8309` 端口的算法服务。
2. 在 **Run and Debug（运行和调试）** 中选择 `Debug agent-service (launch)`，按 **F5** 开始调试（部分 Mac 键盘需按 `Fn + F5`）。
3. 通过 `http://127.0.0.1:8309/docs` 或 HTTP 客户端发送对应请求，触发断点。

修改代码后点击调试工具栏的“重新启动”，结束时点击“停止”。

### 5.2、Attach：连接脚本启动的调试进程

选择一种方式启动调试服务；前台方式需先停止占用 `8309` 端口的算法服务：

```zsh
# 前台启动
zsh scripts/dev/start-api.sh --debug
# 或重启本项目后台服务，启用调试
zsh scripts/dev/services.sh debug-api
```

在 VS Code 中选择 `Debug agent-service (attach)`，按 **F5** 连接 `127.0.0.1:5678`，再向 `8309` 端口发送对应请求触发断点。

Attach 断开后服务仍运行；修改代码需重启调试服务并重新连接。调试时不使用 `--reload`，需要调试启动阶段时使用 Launch。结束后台调试后，执行 `zsh scripts/dev/services.sh restart-api` 恢复普通服务。

### 5.3、搭配 REST Client 发送请求

1. 在 VS Code 扩展中安装 [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client)（`humao.rest-client`）。
2. 按 5.1 或 5.2 启动调试，打开 [tests/http-test/demo.http](../tests/http-test/demo.http)，确认 `@baseUrl = http://127.0.0.1:8309`。
3. 先使用 `POST {{baseUrl}}/agents/chat` 示例，在对应接口或业务代码中设置断点，点击请求上方的 **Send Request**。
4. 命中断点后查看变量、单步执行，按 **F5** 继续；请求完成后在响应面板查看状态码和 JSON。

文件用 `###` 分隔请求，可分别修改请求体后发送。若未显示 **Send Request**，将文件语言模式切换为 **HTTP**。部分 OCR/WBS 示例为历史接口，使用前以 [当前接口清单](../interfaces/README.md) 为准。

## 6、代理与下载排障

若遇到网络故障需要代理可进行如下配置，注意将下面示例**端口**替换为实际代理配置。
即使开启 TUN，也应检查终端和模型推理服务的下载连通性：

```zsh
zsh scripts/dev/check-network.sh http://127.0.0.1:10808
HTTPS_PROXY=http://127.0.0.1:10808 \
https_proxy=http://127.0.0.1:10808 \
NO_PROXY=localhost,127.0.0.1,::1 \
no_proxy=localhost,127.0.0.1,::1 \
zsh scripts/dev/setup.sh
```

模型下载由 Ollama 服务进程发起，新启动服务继承的代理与已运行服务可能不同；复用服务时需检查其实际网络环境。安装命令不会修改 `.zshrc`。HTTP 401/403 仅表示收到响应，不能证明有下载权限。

## 7、检查服务

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/health
curl --noproxy '*' -fsS http://127.0.0.1:8309/ready
curl --noproxy '*' -fsS http://127.0.0.1:8309/diagnostics
```

Swagger UI 为 <http://127.0.0.1:8309/docs>，ReDoc 为 `/redoc`，运行时 OpenAPI 为 `/openapi.json`。接口调试示例从 [接口索引](../interfaces/README.md) 进入，完整脚本入口见 [脚本说明](../scripts/README.md)。

健康、就绪和静态诊断均不能证明真实业务质量；修改推理流程后按 [测试与验收](testing.md) 运行对应检查。纯文档修改不需要重启服务或调用模型。

uv 的环境与依赖管理参考 [官方项目指南](https://docs.astral.sh/uv/guides/projects/)。
