# Docker 生产部署（业务 API + vLLM）

本说明描述用容器部署生产环境：业务 API 与 vLLM 模型服务是**两个镜像、两个环境**，通过 Compose 编排在同一台 GPU 主机上。业务镜像不含模型和 GPU 依赖；模型镜像不含业务依赖。宿主机预置权重，容器只读挂载，构建阶段不下载模型。

非容器部署方式见 [Linux + NVIDIA 部署](deployment-linux.md)。

## 1. 前置条件

- Linux + NVIDIA GPU，驱动可见：`nvidia-smi`。
- Docker 24+ 与 Compose v2，已安装并验证 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)：

  ```bash
  docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
  ```

- 宿主机已准备 Python 3.12 环境仅供**验收脚本**使用；镜像构建本身不需要本机 Python。

## 2. 准备权重

`qwen3.5:9b-q4_K_M` 是 Ollama 风格的标签，vLLM 需要具体的 GGUF 文件或 Hugging Face 仓库。

### 用脚本下载（推荐）

仓库自带下载脚本，只看 ModelScope，不需要 GPU 或 vLLM：

```bash
# 在仓库检出目录执行；默认 Q4_K_M，落到 .cache/models/qwen3.5-9b-q4_k_m/
uv run --locked python -m scripts.models.download_qwen35_gguf
# 离线校验已有目录（大小、sha256、GGUF 架构、config/tokenizer 是否齐全）
uv run --locked python -m scripts.models.download_qwen35_gguf --check
# 查看仓库里的量化版本与体积
uv run --locked python -m scripts.models.download_qwen35_gguf --list
```

脚本下载 `unsloth/Qwen3.5-9B-GGUF` 的 `Qwen3.5-9B-Q4_K_M.gguf`（约 5.3 GiB），再从 `Qwen/Qwen3.5-9B` 补齐 `config.json`、`tokenizer.json`、`tokenizer_config.json`、`vocab.json`、`merges.txt`、`chat_template.jinja` 等文件，逐个比对 ModelScope 给出的 sha256，并写 `MANIFEST.json` 记录来源与提交号。中断后重跑会从 `.part` 续传。

目录内必须是「一个 `.gguf` + config + tokenizer」：

- vLLM 的 GGUF 加载器用 `check_gguf_file()` 判断格式，`--model` 指到**目录**会当成普通 HF 模型加载并失败；
- 判定为 GGUF 后，vLLM 取 `Path(model).parent` 作为 config/tokenizer 所在目录，所以两者必须与 `.gguf` 同级。

把该目录整体拷到 GPU 主机的 `VLLM_MODEL_DIR` 即可（例如 `rsync -avh .cache/models/qwen3.5-9b-q4_k_m/ gpu-host:/srv/models/qwen3.5-9b-q4_k_m/`）。`--vision` 下载的 `mmproj-F16.gguf` 放在 `vision/` 子目录，文本推理用不到，也不放进模型根目录。

GGUF 只含语言权重。若所用分支把该文件按多模态类 `Qwen3_5ForConditionalGeneration` 加载、因缺少视觉张量报错，按官方 README 的 Text-Only 配方追加 `--language-model-only`；该参数需要分支支持。

### 手工准备

把以下文件放到一个宿主机目录（下称 `VLLM_MODEL_DIR`）：

| 文件 | 说明 |
| --- | --- |
| `*.gguf` | Q4_K_M 权重，例如 `Qwen3.5-9B-Q4_K_M.gguf` |
| `config.json` | 来自生成该 GGUF 的原始 Qwen3.5-9B 仓库 |
| tokenizer 文件 | `tokenizer.json`、`tokenizer_config.json`、`special_tokens_map.json` 等 |

GGUF 文件与 tokenizer/`config.json` 必须来自同一模型版本。文件名必须与 `VLLM_MODEL_PATH` 一致。权重不提交到 Git，也不打进镜像。

> 部分 GGUF 仓库（例如 `daniloreddy/Qwen3.5-9B_GGUF` 或 `unsloth/Qwen3.5-9B-GGUF`）只发布量化权重；`config.json` 和 tokenizer 需从对应的上游仓库单独获取。使用前确认模型许可证与量化来源。

### 基础镜像与权重格式必须匹配

| 权重 | `VLLM_BASE_IMAGE` | 说明 |
| --- | --- | --- |
| Q4_K_M GGUF | `ghcr.io/efschu/shvllm-qwen35-gguf:cu129` | vLLM 已移除内置 GGUF 加载；该分支镜像提供 Qwen3.5 GGUF 支持。第三方镜像，升级前需自行验证 |
| BF16 / 反量化权重 | `vllm/vllm-openai:v0.32.0`（默认） | 官方镜像。`exolabs/Qwen3.5-9B-Q4KM-dequant-bf16-vllm` 是 Q4_K_M 反量化版本，显存约 18–20GB |

用官方镜像加载 `.gguf` 会失败。若组织内禁止第三方镜像，改用反量化 BF16 权重并把 `VLLM_BASE_IMAGE` 切回官方镜像。

## 3. 配置

```bash
cp docker/env.example docker/prod.env
chmod 600 docker/prod.env
```

至少填写：

```dotenv
VLLM_MODEL_DIR=/srv/models/qwen3.5-9b-q4_k_m
VLLM_MODEL_PATH=/models/Qwen3.5-9B-Q4_K_M.gguf
VLLM_API_KEY=<与业务 LLM_API_KEY 相同的随机密钥>
OCR_TEMPLATES_DIR=/srv/highway-agent/data/ocr/templates
OCR_ADMIN_DIR=/srv/highway-agent/data/ocr/admin
OCR_ASSETS_DIR=/srv/highway-agent/data/ocr/assets
OCR_PROJECTS_DIR=/srv/highway-agent/data/ocr/projects
```

要点：

- `VLLM_MODEL_DIR` 与四个 `OCR_*_DIR` 必须是**已存在的宿主机绝对路径**；Compose 配置了 `create_host_path: false`，路径不存在会直接报错，而不是静默创建空目录。
- `VLLM_MODEL_PATH` 指向 `.gguf` 文件而不是目录，且必须与 `VLLM_MODEL_DIR` 里的文件名一致；换量化版本（`--quant Q5_K_M` 等）后要同步修改。
- `VLLM_MAX_MODEL_LEN` 必须与 `LLM_CONTEXT_TOKENS` 一致（默认 8192）。vLLM 默认上下文远大于业务预算，会浪费显存。
- `LLM_MODEL` 固定为 `VLLM_SERVED_MODEL_NAME`（默认 `highway-agent`），`/ready` 以此校验服务端模型列表。
- `LLM_REASONING_EFFORT` 留空；思考模式由 `--default-chat-template-kwargs '{"enable_thinking": false}'` 关闭。
- 业务容器以 UID/GID `10001` 运行。挂载目录需对该用户可读，`OCR_PROJECTS_DIR` 需可写：

  ```bash
  sudo chown -R 10001:10001 /srv/highway-agent/data/ocr/projects
  sudo chmod -R a+rX /srv/highway-agent/data/ocr/{templates,admin,assets}
  ```

- 容器启动时会执行 `scripts/prod/check_config.py`，拒绝 Ollama 地址、`qwen3.5:*` 开发模型名和 `CHANGE_ME`/`ollama` 占位密钥。
- RapidOCR 首次识别时从 ModelScope 下载 PP-OCRv6 Medium（检测/识别）与 PP-OCRv5 Server（方向分类）模型，保存在命名卷 `ocr-models`（容器内 `/app/data/ocr/models`）。完全离线的部署需先把这些 ONNX 文件导入该卷（`docker cp` 或临时挂载宿主机目录）；缺少模型时 `/ocr/*` 返回 503，其他接口不受影响。

## 4. 构建与启动

```bash
docker compose -f compose.prod.yml --env-file docker/prod.env build
docker compose -f compose.prod.yml --env-file docker/prod.env up -d
docker compose -f compose.prod.yml --env-file docker/prod.env ps
```

首次启动需要加载模型，健康检查 `start_period` 默认 15 分钟，按权重体积和磁盘速度调整 `VLLM_START_PERIOD`。

查看日志与停止：

```bash
docker compose -f compose.prod.yml --env-file docker/prod.env logs -f model
docker compose -f compose.prod.yml --env-file docker/prod.env logs -f api
docker compose -f compose.prod.yml --env-file docker/prod.env down
```

`down` 不会删除权重或数据池目录（都是宿主机 bind mount）。不要加 `-v`，也不要对宿主机目录做批量清理。

### 只重新部署业务 API

```bash
docker compose -f compose.prod.yml --env-file docker/prod.env build api
docker compose -f compose.prod.yml --env-file docker/prod.env up -d --no-deps api
```

模型服务不随业务代码变更重启。

## 5. 验证

```bash
curl -fsS http://127.0.0.1:8309/health
curl -fsS http://127.0.0.1:8309/ready
curl -fsS http://127.0.0.1:8309/health/deps
```

`/health` 只表示 API 进程存活；`/ready` 会请求 vLLM 的 `/models`，只有模型已加载且名称一致才返回 200。`/health/deps` 检查 OCR、PDF、Excel、图像库与推理设备导入。

真实业务验收在仓库检出目录执行，指向容器暴露的 API：

```bash
BUSINESS_API_URL=http://127.0.0.1:8309 \
  uv run --locked --no-sync --no-dev python -m scripts.common.verify_agents
```

报告写入 `verification/`。`nvidia-smi` 或容器可见 GPU 只说明驱动正常，是否实际占用显存需结合 vLLM 日志与 `nvidia-smi` 进程查看。

## 6. 变量与端口

| 变量 | 作用 |
| --- | --- |
| `VLLM_MODEL_DIR` / `VLLM_MODEL_PATH` | 宿主机权重目录 / 容器内模型路径 |
| `VLLM_BASE_IMAGE` | 模型服务基础镜像，需与权重格式匹配 |
| `VLLM_API_KEY` | vLLM 原生鉴权变量，同时注入业务 API 的 `LLM_API_KEY` |
| `VLLM_MAX_MODEL_LEN` | vLLM 上下文上限，必须等于 `LLM_CONTEXT_TOKENS` |
| `VLLM_GPU_COUNT` / `VLLM_GPU_MEMORY_UTILIZATION` | GPU 数量与显存占比 |
| `API_BIND_ADDRESS` / `API_HOST_PORT` | 业务 API 对外绑定，默认仅 `127.0.0.1:8309` |
| `OCR_*_DIR` | OCR 数据池宿主机路径 |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` | 默认关闭；开启后追踪可能包含业务输入 |

模型服务只在 Compose 内部网络暴露 `8001`，不发布宿主机端口。业务 API 默认只绑定回环地址；对外入口由部署平台的反向代理负责 TLS 与访问控制。**主应用没有自定义身份认证**，`user_id`/`session_id` 不是权限凭据，不要直接把 8309 暴露到公网。

## 7. 升级与回滚

- 业务代码：重新构建 `api` 镜像并 `up -d --no-deps api`；镜像标签默认取 `APP_VERSION`，建议每次发布显式传 `APP_VERSION=<git describe>` 以便回滚。
- 模型或 vLLM：修改 `VLLM_BASE_IMAGE`/`VLLM_MODEL_PATH` 后重建 `model` 服务；切换模型名时同步 `VLLM_SERVED_MODEL_NAME`，否则 `/ready` 失败。
- 回滚到旧镜像：把 `APP_VERSION` 改回旧值并 `up -d`，不要删除旧镜像前先确认新版本验收通过。

## 8. 已知限制

- 当前仓库的配置校验与启动脚本沿用 `scripts/prod/`；容器没有内置真实验收脚本，验收需在仓库检出目录运行。
- `ghcr.io/efschu/shvllm-qwen35-gguf:cu129` 是社区分支镜像，未经本项目维护者验证；生产使用前应在目标 GPU 与驱动上完成加载、结构化输出和长上下文测试。
- 本仓库未在 Linux + NVIDIA 实机执行过本 Compose 部署；已执行的验证见交付说明。Mac 上的离线测试不能替代 GPU 验收。
- 业务镜像按 `API_WORKERS=1` 启动。提高 worker 数会让每个进程各自加载 OCR 引擎，需先评估内存。
