# 配置说明

应用配置定义在 [app/config.py](../app/config.py) 的 `Settings`；开发模板为 [.env.example](../.env.example)，Linux 生产模板为 [scripts/prod/api.env.example](../scripts/prod/api.env.example)。本文描述配置用途，具体默认值和校验以源码为依据。

## 1、加载与生效

读取顺序为算法服务进程环境变量、仓库根目录 `.env`、源码默认值。修改后重启算法服务；已有 `.env` 不应被模板覆盖，密钥不提交 Git。

launchd 后台任务不保证继承当前终端的临时 `export`。Ollama 的 `OLLAMA_*` 和 vLLM 的 `VLLM_*` 属于模型进程或部署脚本，不由业务 `Settings` 加载，须在各自实际启动环境设置。

Docker 使用 `docker/prod.env` 与 Compose 向容器传入环境，并包含宿主机挂载、构建等专用变量；其用途与应用根目录 `.env` 不完全相同，见 [Docker 部署](docker.md)。

## 2、应用配置表

按读取配置的服务分组。算法服务列出 `Settings` 源码默认值；模型推理服务与系统运行部分分别注明脚本或 Compose 的配置来源。生产模板可覆盖默认值，例如生产 OCR 默认使用 `cuda`。

### 2.1、算法服务

由 `Settings` 读取，通常配置在根目录 `.env`；Docker 通过 Compose 映射注入。`LLM_*` 控制算法服务如何调用模型，Ollama／vLLM 自身的配置见 2.2。

**模型调用与 Agent 执行**

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI 兼容模型 API，包含 `/v1` |
| `LLM_MODEL` | `qwen3.5:9b-q4_K_M` | 服务端模型名称 |
| `LLM_API_KEY` | `ollama` | Ollama 占位值；远端服务按需填写真实 key |
| `LLM_TIMEOUT_SECONDS` | `180` | 本地模型单次调用超时；启用回退时总预算再加回退超时 |
| `LLM_MAX_TOKENS` | `2048` | 模型输出长度限制 |
| `LLM_CONTEXT_TOKENS` | `8192` | 实际模型推理服务的上下文容量，含输入和输出 |
| `LLM_CONTEXT_MARGIN_TOKENS` | `256` | 历史裁剪预算额外余量 |
| `CONVERSATION_MAX_INPUT_CHARACTERS` | `1000000` | 历史及序列化当前输入总字符上限，超出返回422 |
| `LLM_REASONING_EFFORT` | `none` | 关闭当前 Qwen 服务的思考输出；不支持的服务可设为空 |
| `AGENT_RECURSION_LIMIT` | `8` | Agent 运行步数上限，包含工具调用循环 |
| `MAIN_WORK_SPLIT_TIMEOUT_SECONDS` | `30` | 新版监理日志 `mainWork` 规则不足后全文生成的总预算（含并发排队），超时返回受控 `502` |
| `MAIN_WORK_SPLIT_CONCURRENCY` | `1` | `mainWork` 生成的并发上限；OCR 推理仍按应用串行加锁 |

**云端回退**

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `LLM_FALLBACK_ENABLED` | `false` | 云端回退总开关；`true` 且回退密钥非空时才启用 |
| `LLM_FALLBACK_BASE_URL` | `https://api.deepseek.com` | 本地 Ollama/vLLM 调用失败时的云端 OpenAI 兼容地址 |
| `LLM_FALLBACK_MODEL` | `deepseek-flash` | 回退模型名称 |
| `LLM_FALLBACK_API_KEY` | 空 | 回退密钥；留空不启用回退，已配置时仍受总开关控制 |
| `LLM_FALLBACK_TIMEOUT_SECONDS` | `60` | 回退调用超时，叠加在 `LLM_TIMEOUT_SECONDS` 之上 |
| `LLM_FALLBACK_REASONING_EFFORT` | `none` | 关闭回退模型思考；不支持的服务可设为空 |

**OCR 与数据池**

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `TEMPLATES_ROOT` | `data/ocr/templates` | 旧模板资源目录，当前由静态诊断引用 |
| `ADMIN_ROOT` | `data/ocr/admin` | 管理端资料目录，当前由静态诊断引用 |
| `ASSET_ROOT` | `data/ocr/assets` | 规范资料目录，当前由静态诊断引用 |
| `PROJECTS_ROOT` | `data/ocr/projects` | 与 Java 共用的业务数据池，限制文件读写边界 |
| `OCR_MODEL_ROOT` | `.cache/models/ocr` | RapidOCR ONNX 模型目录；首次使用可自动下载；离线部署需预置模型 |
| `OCR_DEVICE` | `cpu` | OCR 推理设备：`cpu`（默认，适合无 NVIDIA GPU 的开发/Mac 环境）或 `cuda`（需 CUDA 12 + cuDNN 9，同时通过 `--extra ocr-gpu` 安装 onnxruntime-gpu）；cuda 不可用时接口返回 503 |
| `OCR_CUDA_ROOT` | `.cache/cuda` | 仅 cuda 模式：Windows 可将 NVIDIA redist 解压到此目录免系统安装，需 CUDA 12 + cuDNN 9 |

### 2.2、模型推理服务

以下配置不由算法服务的 `Settings` 读取，需在模型服务进程或对应部署配置中设置。

**Ollama（macOS 开发）**

默认值来自 [start-ollama.sh](../scripts/dev/start-ollama.sh)，仅对该脚本启动的进程生效；已运行的 Ollama 沿用其原启动环境。

| 变量 | 脚本默认值 | 用途 |
| --- | --- | --- |
| `OLLAMA_HOST` | `127.0.0.1:11434` | 模型推理服务监听地址 |
| `OLLAMA_CONTEXT_LENGTH` | `8192` | 上下文长度，与算法服务 `LLM_CONTEXT_TOKENS` 对齐 |
| `OLLAMA_NUM_PARALLEL` | `1` | 模型并行请求数 |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | 同时加载的模型数量 |
| `OLLAMA_NOPRUNE` | `true` | 启动时保留未引用的模型文件 |
| `OLLAMA_MODELS` | 脚本不设置 | 可显式指定模型存储目录，否则沿用 Ollama 标准目录 |

**vLLM（Docker 生产）**

配置在 `docker/prod.env`，以下值依据 [Compose](../compose.prod.yml) 与 [生产模板](../docker/env.example)。Linux 非容器部署使用 [start-vllm.sh](../scripts/prod/start-vllm.sh)，需额外设置独立环境的 `VLLM_BIN` 绝对路径；模型长度、显存预算等通过该脚本的命令行参数传入，不自动读取下表的 Compose 变量。

| 变量 | 默认值／要求 | 用途 |
| --- | --- | --- |
| `VLLM_MODEL_DIR` | 必填 | 宿主机模型目录，只读挂载到容器 `/models` |
| `VLLM_MODEL_PATH` | 必填 | 容器内模型路径；当前 GGUF 方案必须指向 `.gguf` 文件 |
| `VLLM_SERVED_MODEL_NAME` | `highway-agent` | 对外模型名称，Compose 同步映射为算法服务 `LLM_MODEL` |
| `VLLM_API_KEY` | 必填 | 模型服务密钥，Compose 同步映射为算法服务 `LLM_API_KEY` |
| `VLLM_PORT` | `8001` | 容器内监听端口，Compose 同步用于算法服务 `LLM_BASE_URL` |
| `VLLM_MAX_MODEL_LEN` | `8192` | 最大上下文长度，与算法服务 `LLM_CONTEXT_TOKENS` 对齐 |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.75` | GPU 显存使用预算，需为共享 GPU 的 OCR 留出空间 |
| `VLLM_GPU_COUNT` | `1` | 模型服务容器申请的 GPU 数量 |
| `VLLM_START_PERIOD` | `15m` | 容器启动后的健康检查宽限期 |
| `VLLM_LOGGING_LEVEL` | `INFO` | 模型服务日志级别 |
| `HF_HUB_OFFLINE` | `1` | 使用本地权重；需联网加载 Hugging Face 模型 ID 时设为 `0` |

### 2.3、系统运行与部署

这些配置用于服务暴露、镜像发布、资源挂载和追踪。除 `LANGSMITH_TRACING` 外，均不属于业务 `Settings` 字段。

| 变量 | 默认值／要求 | 来源与用途 |
| --- | --- | --- |
| `API_BIND_ADDRESS` | `127.0.0.1` | Compose：宿主机绑定地址 |
| `API_HOST_PORT` | `8309` | Compose：宿主机访问端口，映射到算法服务容器的 `8309` |
| `APP_VERSION` | `0.1.0` | Compose：算法服务与模型服务的镜像标签 |
| `VLLM_BASE_IMAGE` | 模板：`ghcr.io/efschu/shvllm-qwen35-gguf:cu129` | vLLM 构建基础镜像；Compose 未设置时兜底为 `vllm/vllm-openai:v0.32.0`，GGUF 需使用支持它的插件镜像 |
| `OCR_GPU_COUNT` | `1` | Compose：算法服务容器申请的 GPU 数量 |
| `OCR_MODEL_DIR` | 空 | Compose：OCR 模型的宿主机目录，留空使用命名卷；区别于容器内的 `OCR_MODEL_ROOT` |
| `LANGSMITH_TRACING` | `false` | `Settings`：是否启用算法服务的 LangSmith 追踪 |
| `LANGSMITH_API_KEY` | 空 | 启用追踪时通过进程环境或 Compose 提供，不提交真实密钥 |

Docker 配置更新、容器重建和检查命令见 [更新、访问与回滚](docker.md#6更新访问与回滚)。

## 3、模型与上下文

`LLM_BASE_URL` 与 `LLM_MODEL` 必须匹配实际模型推理服务；默认开发端为 Ollama，Linux 使用独立 vLLM。模型推理服务需提供 Chat Completions 和主模型原生 JSON Schema 输出，具体部署组合通过真实业务验收确认。

`LLM_CONTEXT_TOKENS` 必须与实际服务容量一致；应用为输出和安全余量预留预算，按保守 UTF-8 字节估算裁剪最早完整历史回合。它不是精确 tokenizer；完整输入上限由 `CONVERSATION_MAX_INPUT_CHARACTERS` 另外限制。会话行为见 [用户与会话](sessions.md)。

`LLM_REASONING_EFFORT=none` 是当前 Qwen 配置；不支持该参数的模型推理服务可留空。修改模型及提示词后，需重启服务并执行 [真实验收](testing.md#3真实依赖与业务验收)。

## 4、云端回退

默认关闭，仅在 `LLM_FALLBACK_ENABLED=true` 且 `LLM_FALLBACK_API_KEY` 非空时启用。只有密钥、没有开关，或开关开启但密钥为空／纯空白，均不会启用。

```dotenv
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_API_KEY=<云端服务密钥>
```

本地模型调用连接失败、超时或上游 HTTP 错误时，允许回退的 Agent 尝试云端模型一次。总预算为 `LLM_TIMEOUT_SECONDS + LLM_FALLBACK_TIMEOUT_SECONDS`；关闭后仅使用本地预算。回退不重试已返回但未通过 Schema 校验的输出，`/ready` 仍只检查本地模型。

当前 DeepSeek 适配将严格 `json_schema` 请求转换为 JSON 模式，再由 Pydantic 校验结构化结果；不使用宽松文本解析。业务专属预算仍可能更短，例如 `MAIN_WORK_SPLIT_TIMEOUT_SECONDS` 包含排队和生成时间；mainWork 生成失败或超时返回受控 502，见 [mainWork 处理](journal-mainwork-split.md)。

启用回退会将本次业务输入发送到云端，应按业务数据要求决定是否启用。已有部署若仅配置回退密钥，升级后需补充开关。Mac/Linux 修改部署根目录 `.env` 后重启算法服务。

Docker 修改 `docker/prod.env` 后，使用以下命令重建算法服务容器并加载环境；仅 `restart` 不更新容器环境变量：

```bash
docker compose --env-file docker/prod.env -f compose.prod.yml up -d agent-service
```

## 5、OCR 设备、模型与数据池

- macOS／无 NVIDIA GPU 环境：`OCR_DEVICE=cpu`，依赖同步使用 `--extra ocr-cpu`。
- NVIDIA GPU 环境：`OCR_DEVICE=cuda`，依赖同步使用 `--extra ocr-gpu`，并准备 CUDA 12 + cuDNN 9。CUDA 不可用时接口返回 503，不静默切换 CPU。
- 两个 extra 互斥且共用同一组 ONNX 模型；不带 extra 重新同步会移除已安装的 OCR 运行时。

OCR 相对路径均以仓库根目录解析。新版监理日记模板随代码发布在 `app/ocr/journal/templates/journal.json`，`TEMPLATES_ROOT`、`ADMIN_ROOT`、`ASSET_ROOT` 仍用于静态诊断，不参与新版日记字段定位。照片路径受 `PROJECTS_ROOT` 数据池限制。

`OCR_MODEL_ROOT` 指向 RapidOCR 模型缓存，首次识别可自动下载；离线部署需预置：

```zsh
uv run --locked python -m scripts.models.download_ocr_models
uv run --locked python -m scripts.models.download_ocr_models --check
```

Docker 的 `OCR_MODEL_DIR` 是宿主机挂载变量，留空时使用命名卷，指定目录需允许容器 UID 10001 写入。设备切换会改变构建的 OCR extra，需重建算法服务镜像；迁移与权重准备见 [Docker 部署](docker.md)。

`OCR_CUDA_ROOT` 仅用于 CUDA 模式的项目本地运行库，Windows 可将 NVIDIA redist 解压到该目录；容器已提供的运行库与宿主机驱动要求见部署专题。算法资源和路径细节见 [OCR 说明](ocr.md)。

## 6、追踪与敏感信息

`LANGSMITH_TRACING=false` 为默认值。启用时需在进程环境提供 LangSmith 凭据，追踪可能包含输入与模型输出。`SecretStr` 不代替日志、错误和提交内容的脱敏；`.env`、`.secrets/` 和真实业务追踪不提交。
