# Docker 生产部署：Agent + OCR

无 GPU 主机请直接使用[第 10 节：CPU OCR + 云端 LLM](#10cpu-ocr--云端-llm)。
以下第 1–9 节描述现有 NVIDIA + 本地 vLLM 方案。

算法服务与 vLLM 是两个镜像、两个 Python 环境；通过 Compose 内部网络通信。
本方案面向 Linux x86_64 + NVIDIA GPU，当前目标为 RTX 5090 Laptop GPU、
Qwen3.5 9B Q4_K_M。LLM 权重提前下载并从宿主机只读挂载；OCR 权重可预置，也可首次使用时自动下载。

算法服务镜像基于 `nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04`，安装 Python 3.12，
通过锁文件的 `ocr-gpu` extra 安装 `onnxruntime-gpu==1.24.4`。
builder/runtime 使用同一基础环境，镜像包含 CUDA 12.9.1 与 cuDNN 9 用户态库。
宿主机提供 NVIDIA 驱动与 Container Toolkit，无需另行挂载 CUDA 库。
构建阶段校验 OpenCV、ONNX Runtime 和 CUDA/cuDNN 动态库能否加载，真实 CUDA EP
初始化仍必须在服务器执行。`ocr-cpu` 与 `ocr-gpu` 不得同时安装。

非容器方式见 [Linux 部署](deployment-linux.md)。

## 1、服务器前置检查

```bash
uname -m
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
docker version
docker compose version
```

- CPU 架构应为 `x86_64`。Compose 显式使用 `linux/amd64`；当前 GPU wheel 不支持 Linux ARM64。
- 显存以 `nvidia-smi` 为准，不使用桌面版 RTX 5090 的显存数据估算 Laptop GPU。
- 安装支持该 GPU、满足 CUDA 12.9 镜像要求的驱动。`nvidia-smi` 的 CUDA Version 是驱动
  支持的上限，不代表宿主机或容器已经安装对应 Toolkit。
- 使用当前维护的 Docker Engine 与 Compose 插件。
  Ubuntu 安装见 [Docker 官方说明](https://docs.docker.com/engine/install/ubuntu/)，
  GPU 容器支持见 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)。
- Blackwell 对应的 CUDA/cuDNN 组合见 [NVIDIA 支持矩阵](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.7.0/reference/support-matrix.html)。
  ONNX Runtime 的版本要求见 [CUDA EP 文档](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)。

新装主机安装 Toolkit 后执行；已有容器的主机应在维护窗口重启 Docker：

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
```

后续命令在服务器项目根目录执行，除非标为“开发机”。服务器只构建和运行容器时，
不需要在宿主机安装 Python、uv 或 vLLM。

## 2、准备权重

在已安装项目环境的开发机执行；已有正确文件会复用，不使用 `--force`：

```bash
uv run --locked --no-sync python -m scripts.models.download_qwen35_gguf
uv run --locked --no-sync python -m scripts.models.download_qwen35_gguf --check
uv run --locked --no-sync python -m scripts.models.download_ocr_models
uv run --locked --no-sync python -m scripts.models.download_ocr_models --check
```

首次准备开发环境使用 `uv sync --locked --group dev --extra ocr-cpu`。
下载结果不进 Git，也不打进镜像：

```text
.cache/models/
├── qwen3.5-9b-q4_k_m/
│   ├── Qwen3.5-9B-Q4_K_M.gguf
│   ├── config.json
│   ├── tokenizer.json / tokenizer_config.json
│   ├── vocab.json / merges.txt / chat_template.jinja
│   └── LICENSE / MANIFEST.json / 其他配置文件
└── ocr/
    ├── PP-OCRv6_det_medium.onnx
    ├── PP-OCRv6_rec_medium.onnx
    └── ch_PP-LCNet_x1_0_textline_ori_cls_server.onnx
```

GGUF 约 5.3 GiB，OCR 三个模型约 139 MiB。下载脚本按来源 sha256 校验；GGUF 清单记录
ModelScope 来源和修订。`qwen3.5:9b-q4_K_M` 是 Ollama 标签，vLLM 使用具体 GGUF 文件。
GGUF 必须与 config/tokenizer 同级。只部署文本模型，不需要 `--vision` 的 mmproj。

校验成功后，在开发机生成迁移清单（Mac 自带 `shasum`）：

```bash
(cd .cache/models && shasum -a 256 qwen3.5-9b-q4_k_m/* ocr/*.onnx > SHA256SUMS)
```

此命令面向上述仅含文件的默认目录。若另下载了 `vision/`，应单独为其生成清单。

服务器先创建新的模型目录和数据池，给部署账号授予模型目录写权限。共享已有 Java
数据池时保留原属主，按现有权限方案授权，不批量重置属主：

```bash
sudo mkdir -p /srv/models/qwen3.5-9b-q4_k_m /srv/models/ocr
sudo mkdir -p /srv/highway-agent/data/ocr/{templates,admin,assets,projects}
# 仅适用于上面新建的独立模型目录：
sudo chown "$USER:$(id -gn)" /srv/models /srv/models/qwen3.5-9b-q4_k_m /srv/models/ocr
```

从开发机上传（把 `user@server` 替换为实际 SSH 目标）：

```bash
rsync -avh .cache/models/qwen3.5-9b-q4_k_m/ user@server:/srv/models/qwen3.5-9b-q4_k_m/
rsync -avh .cache/models/ocr/ user@server:/srv/models/ocr/
rsync -avh .cache/models/SHA256SUMS user@server:/srv/models/SHA256SUMS
```

服务器校验，所有条目必须为 `OK`：

```bash
cd /srv/models
sha256sum --check SHA256SUMS
```

权重齐全只表示可以开始推理验收，不表示识别或分类质量已通过。

## 3、代码、模板和配置

部署与开发机验收对应的 Git 版本。获取代码后进入仓库根目录：

```bash
git clone https://github.com/TonyZhang128/agent-dev.git
cd agent-dev
git rev-parse --short HEAD
test -f docker/prod.env || cp docker/env.example docker/prod.env
chmod 600 docker/prod.env
```

已有 `docker/prod.env` 时保留它并逐项补充，不覆盖真实密钥。
当前监理日记模板是代码中的 `app/ocr/journal/templates/journal.json`，随镜像发布；
本地 `data/ocr/resources/` 的源 PDF、照片及业务输出不进镜像。
`templates/admin/assets` 挂载仍服务于现有诊断；不是新版 journal 的模板来源。

至少核对：

```dotenv
VLLM_BASE_IMAGE=ghcr.io/efschu/shvllm-qwen35-gguf:cu129
VLLM_MODEL_DIR=/srv/models/qwen3.5-9b-q4_k_m
VLLM_MODEL_PATH=/models/Qwen3.5-9B-Q4_K_M.gguf
VLLM_SERVED_MODEL_NAME=highway-agent
VLLM_API_KEY=替换为随机长密钥
HF_HUB_OFFLINE=1
VLLM_GPU_COUNT=1
VLLM_GPU_MEMORY_UTILIZATION=0.75
VLLM_MAX_MODEL_LEN=8192
LLM_CONTEXT_TOKENS=8192
LLM_REASONING_EFFORT=
OCR_DEVICE=cuda
OCR_GPU_COUNT=1
OCR_MODEL_DIR=/srv/models/ocr
OCR_TEMPLATES_DIR=/srv/highway-agent/data/ocr/templates
OCR_ADMIN_DIR=/srv/highway-agent/data/ocr/admin
OCR_ASSETS_DIR=/srv/highway-agent/data/ocr/assets
OCR_PROJECTS_DIR=/srv/highway-agent/data/ocr/projects
API_BIND_ADDRESS=127.0.0.1
API_HOST_PORT=8309
JOURNAL_TIMEOUT_SECONDS=30
JOURNAL_CONCURRENCY=1
```

- vLLM 与 OCR 共享单卡时，`0.75` 是保守起始预算，仍需按实际显存和并发调整；它不是
  显存隔离。若为 24 GiB，vLLM 的初始目标约 18 GiB，余量还需容纳 OCR、桌面及其他进程。
- `VLLM_MAX_MODEL_LEN` 与 `LLM_CONTEXT_TOKENS` 保持一致。模型思考由服务端 chat template 关闭。
- 算法服务的 `LLM_MODEL` 自动取 `VLLM_SERVED_MODEL_NAME`，密钥自动取 `VLLM_API_KEY`。
  容器不读取宿主机根目录 `.env`；只有 Compose 明确转发的变量进入容器。
- 所有挂载源目录必须已存在；`create_host_path: false` 会拒绝不存在的路径。
  算法服务以 UID/GID `10001` 运行，需能遍历目录、读取模型与照片；按共享数据池约定配置写权限。
- 云端回退默认关闭；只在明确需要时设置 `LLM_FALLBACK_ENABLED=true` 与对应密钥。
- 当前 GGUF 方案使用第三方插件镜像。标签存在不等于目标 GPU 验收通过，确认后应记录
  镜像 digest。改用 BF16 权重时才选择对应官方 vLLM 镜像和模型目录。
  [vLLM GGUF 文档](https://docs.vllm.ai/en/latest/features/quantization/gguf/)说明其插件依赖与限制。
- 如果 GGUF 加载报缺视觉张量，先核对插件和模型配置，再检查该分支是否支持
  `--language-model-only`；不要通过下载不匹配的视觉权重掩盖错误。

## 4、构建与启动

```bash
dc() {
  docker compose -f compose.prod.yml --env-file docker/prod.env "$@"
}

dc config --quiet
dc build
dc up -d
dc ps
dc logs --tail=100 model agent-service
```

首次模型加载可能较慢，`VLLM_START_PERIOD` 默认 15 分钟。算法服务可以提前启动，
不等待模型健康；模型未就绪前 `/ready` 应失败。使用 `config --quiet` 避免把展开的密钥
打印到终端记录。构建上下文通过 `.dockerignore` 排除生产变量、模型和业务样本。

当前机器是 ARM Mac 时只允许进行 `linux/amd64` 仿真构建/CPU 冒烟验证，不在 Mac
执行整套需要 NVIDIA 的 Compose。服务器完全离线时，还需在联网环境构建对应 amd64
镜像并用 `docker save` / `docker load` 迁移；只有权重预下载不能让镜像构建离线完成。

## 5、分层验收

### 5.1、存活、模型就绪与静态诊断

```bash
curl -fsS http://127.0.0.1:8309/health
curl -fsS http://127.0.0.1:8309/ready
curl -fsS http://127.0.0.1:8309/diagnostics
```

`/health` 不访问模型，`/ready` 只检查上游模型列表；`/diagnostics` 不初始化引擎，
即使 `data.ok=false` 也返回 200。缺少旧表样库时诊断可能失败，需逐项判断，不能
把该结果等同于新版 journal 定位失败，也不能用 provider 名称证明 CUDA 实际初始化。

### 5.2、OCR CUDA EP 真实初始化（服务器）

```bash
dc exec -T agent-service python - <<'PY'
import onnxruntime as ort
from app.config import Settings

settings = Settings()
assert settings.ocr_device == "cuda", "当前不是 GPU OCR 配置"
for name in (
    "PP-OCRv6_det_medium.onnx",
    "PP-OCRv6_rec_medium.onnx",
    "ch_PP-LCNet_x1_0_textline_ori_cls_server.onnx",
):
    session = ort.InferenceSession(
        str(settings.ocr_model_root / name), providers=["CUDAExecutionProvider"]
    )
    assert session.get_providers()[0] == "CUDAExecutionProvider", name
    print(name, session.get_providers())
    del session
PY
```

上述命令分别检查三个实际 ONNX 会话的 CUDA provider；缺库、设备不可见或回退 CPU 都不能算通过。
排查时可以将 `OCR_DEVICE=cpu` 并重建算法服务容器，但必须把这次结果标为 CPU 验证。
整个 Compose 的 vLLM 服务仍需要 NVIDIA GPU。

### 5.3、Agent 业务回归（开发机通过 SSH 隧道）

开发机保留项目依赖和验收数据，服务器无需为验收额外装开发依赖：

```bash
ssh -N -L 18309:127.0.0.1:8309 user@server
```

另开开发机终端，在仓库根目录执行：

```bash
BUSINESS_API_URL=http://127.0.0.1:18309 LLM_MODEL=highway-agent \
  uv run --locked --no-sync python -m scripts.common.verify_agents
```

报告位于 `verification/agents-live-result.json`。该脚本验证 Agent，**不验证照片 OCR**；
若还运行模型直调验收，其 `LLM_*` 必须同样指向这次服务器部署。

### 5.4、真实 OCR 照片与并发验收

把独立标注的同版式照片放到服务器数据池 `projects/acceptance/journal.jpg`，确保 UID
10001 可读；在服务器执行（开发机则把端口改为 SSH 隧道的 18309）：

```bash
mkdir -p verification/ocr
curl --fail-with-body http://127.0.0.1:8309/ocr/journal \
  -H 'Content-Type: application/json' \
  -d '{"path":"acceptance/journal.jpg","taskId":"deploy-check-001"}' \
  -o verification/ocr/deploy-check-001.json
```

逐项核对日期、项目名、编号、数值单位及施工/旁站/巡视内容，不以 HTTP 200 或非空字段
数量代替内容验收。另测空白纸、错误版式、无效路径和 Agent/OCR 同时请求；记录样本数、
字段正确率、失败案例、耗时和 `nvidia-smi` 显存峰值。无可用真实标注样本时标记未验证。
无效表格应返回既有 400，不能全空成功；API 路径必须位于 PROJECTS_ROOT 内。

## 6、更新、访问与回滚

算法服务的 Compose 服务名与镜像名统一为 `agent-service`，模型推理服务保留 `model`。已有部署若仍使用 `docsvc` 或 `api`，先按旧版编排文件停止旧算法服务，再使用新编排构建、启动 `agent-service`，避免旧容器继续占用 8309；不要将模型推理服务或数据卷作为命名迁移的一部分删除。

### 6.1、配置修改与生效

Docker 部署修改 `docker/prod.env`，由 `compose.prod.yml` 的 `environment` 映射到容器；宿主机根目录 `.env` 不会自动传入容器。新增变量需同时检查 Compose 是否已映射，终端同名环境变量优先于 `--env-file`。

以下命令沿用第 4 节定义的 `dc` 函数，等同于 `docker compose -f compose.prod.yml --env-file docker/prod.env`。修改后先校验配置：

```bash
dc config --quiet
```

仅修改算法服务的运行配置（如超时、云端回退开关），重新创建算法服务容器，保留模型服务运行：

```bash
dc up -d --no-deps --force-recreate agent-service
```

修改模型推理服务配置，或两个服务共用的 `VLLM_API_KEY`、`VLLM_SERVED_MODEL_NAME`、`VLLM_PORT` 等变量时，让 Compose 更新所有受影响的服务：

```bash
dc up -d
```

单独执行 `dc restart` 不会载入新环境变量。普通运行配置修改不需要重新构建镜像。

### 6.2、代码、依赖与 OCR 设备更新

修改业务代码、依赖或切换 `OCR_DEVICE` 后，重新构建镜像并更新算法服务：

```bash
dc up -d --build --no-deps agent-service
```

`OCR_DEVICE` 同时决定构建时安装的 OCR 依赖，不能只重建容器；设备切换要求见 [OCR CPU/CUDA 依赖切换](#8ocr-cpucuda-依赖切换)。

### 6.3、更新后检查与回滚

使用默认端口时，更新后检查容器状态、进程存活和模型就绪：

```bash
dc ps
curl -fsS http://127.0.0.1:8309/health
curl -fsS http://127.0.0.1:8309/ready
```

模型重新加载期间 `/ready` 可能暂时失败。就绪检查不验证业务效果，仍需按第 5 节执行对应的 Agent 或 OCR 验收。

多个 worker 会各自加载 OCR 模型，默认保持一个。当前应用无身份认证，8309 保留回环
绑定，对外访问由反向代理提供 TLS 和访问控制；模型 8001 仅在 Compose 内部网络开放。

每次发布使用独立 `APP_VERSION` 并记录模型镜像 digest，确认新版本验收后再处理旧镜像。
回滚时恢复旧配置与镜像标签，使用 `dc up -d --no-build`，避免重新构建覆盖旧标签。
`dc down` 停止本项目容器，宿主机 bind mount 中的模型与数据不删除。

## 7、验证边界

本地检查、amd64 仿真构建、动态库加载和 CPU OCR 都不能替代 RTX 5090 Laptop 的实际
CUDA 推理、GGUF 模型加载、结构化输出、长上下文及双服务并发验收。每次发布应分别
记录本地检查与服务器验收结果，不能只根据容器 `healthy` 标记宣布功能可用。


## 8、OCR CPU/CUDA 依赖切换

统一保留 CUDA 12.9.1 + cuDNN 9 基础镜像。`docker/prod.env` 的 `OCR_DEVICE`
同时传入构建参数和容器环境：`cpu` 仅安装 `ocr-cpu`（onnxruntime），`cuda` 仅安装
`ocr-gpu`（onnxruntime-gpu）。未设置时默认 cuda，空值或其他值在构建时失败。
沿用 pyproject.toml 中已有的互斥 extra，不在容器启动时同步或安装依赖。

修改配置后执行：

```bash
docker compose -f compose.prod.yml --env-file docker/prod.env up -d --build --no-deps agent-service
```

仅 restart 不会更新依赖或容器环境；不要跳过重新构建。终端导出的 OCR_DEVICE
优先于 env-file，部署前应确认没有旧值。手动构建使用 --build-arg OCR_DEVICE=cpu
或 cuda，并确保容器运行环境的 OCR_DEVICE 与构建一致。

CPU 模式也保留 CUDA 库、API 的 GPU reservation 和原镜像标签；它适用于已有 NVIDIA
部署上切换 OCR 推理设备，不使当前 Compose 成为无 GPU 部署方案。vLLM 配置不变，
两种模式共用 ONNX 模型文件。目标服务器仍需分别构建镜像并执行真实 OCR 验收。


## 9、OCR 权重可选与自动下载

`OCR_MODEL_DIR` 不再必填。留空或删除该配置时，Compose 创建 `ocr-models` 命名卷挂载到
`/app/data/ocr/models`。镜像中该目录归 UID 10001 所有，空命名卷首次挂载继承目录权限，
RapidOCR 在首次 OCR 请求时自动下载缺失模型，之后复用缓存；API 启动本身不会下载。
容器重建保留命名卷，`docker compose down -v` 会删除缓存。

若填写宿主机路径，则以可读写方式挂载并允许 Docker 创建缺失目录。Docker 自动创建的
宿主机目录可能归 root 所有，因此推荐无预置权重时留空使用命名卷；使用自定义宿主机目录
时，由部署账号提前创建并按现有权限策略授予容器 UID 10001 写权限，不批量修改已有数据属主。
已有完整权重直接复用，缺失权重需要目录可写且容器能访问模型下载源。离线部署仍需预置。

```dotenv
# 自动下载到命名卷，无需宿主机权重目录
OCR_MODEL_DIR=
```

修改后执行 `docker compose -f compose.prod.yml --env-file docker/prod.env up -d --no-deps agent-service`
重建容器挂载；同时修改 OCR_DEVICE 时需追加 `--build`。下载失败沿用现有 OCR 错误处理，
不影响 `/health` 进程存活检查，首次 OCR 包含下载耗时。

## 10、CPU OCR + 云端 LLM

`Dockerfile.cpu` 使用 Python 3.12 slim 多阶段构建，仅安装锁定的 `ocr-cpu` 运行依赖，
不包含 CUDA/cuDNN、GPU ONNX Runtime 或 LLM 权重。`compose.cpu.yml` 仅启动算法服务，
不申请 GPU，不需要 NVIDIA 驱动或 Container Toolkit，也不启动 Ollama/vLLM。
它是独立编排文件，不能与 `compose.prod.yml` 叠加使用。

在仓库根目录执行：

```bash
test -f docker/cpu.env || cp docker/cpu.env.example docker/cpu.env
chmod 600 docker/cpu.env
# 编辑 docker/cpu.env，替换 LLM_BASE_URL、LLM_MODEL、LLM_API_KEY 三个占位值。
```

`LLM_BASE_URL` 填供应商的 OpenAI 兼容端点，`LLM_MODEL` 填其实际模型 ID，
`LLM_API_KEY` 填云端密钥；云端是主模型，直接配置 `LLM_*`，无需启用 `LLM_FALLBACK_*`。
模型需支持 `ProviderStrategy(strict=True)` 使用的原生 JSON Schema 结构化输出；
仅兼容普通聊天不够。`LLM_REASONING_EFFORT` 默认留空，按供应商支持情况配置。
按模型实际上下文限制调整 `LLM_CONTEXT_TOKENS` 和输出预算。
`/ready` 还要求云端提供兼容的模型列表接口并返回配置模型；它不验证结构化输出效果。

```bash
docker compose -f compose.cpu.yml --env-file docker/cpu.env config --quiet
docker compose -f compose.cpu.yml --env-file docker/cpu.env build
docker compose -f compose.cpu.yml --env-file docker/cpu.env up -d
docker compose -f compose.cpu.yml --env-file docker/cpu.env ps
curl -fsS http://127.0.0.1:8309/health
curl -fsS http://127.0.0.1:8309/ready
curl -fsS http://127.0.0.1:8309/diagnostics
```

镜像标签为 `agent-service:<APP_VERSION>-cpu`，与 GPU 镜像区分。Compose 固定
`OCR_DEVICE=cpu`，不会继承终端的 CUDA 设备配置。默认构建宿主机架构；跨架构发布时，
单独构建示例为 `docker build --platform linux/amd64 -f Dockerfile.cpu -t agent-service:0.1.0-cpu .`，
在目标架构进行真实验收后再发布。

OCR 权重默认缓存到本方案的 `ocr-models` 命名卷，首次 OCR 请求联网下载；离线使用
`OCR_MODEL_DIR` 指向预置目录，权限要求和缓存规则同第 9 节。内置 journal 模板随代码发布。
base64 照片无需宿主机数据池；使用文件路径或写出结果时，需通过额外的 Compose 覆盖文件
将已有项目数据池挂载到 `/app/data/ocr/projects`，并授予 UID 10001 必要的读写权限。例如：

```yaml
# compose.cpu.data.yml；source 替换为已有的宿主机项目数据池。
services:
  agent-service:
    volumes:
      - type: bind
        source: /srv/highway-agent/data/ocr/projects
        target: /app/data/ocr/projects
        bind:
          create_host_path: false
```

使用该覆盖文件时，在上述每条 Compose 命令的 `-f compose.cpu.yml` 后追加
`-f compose.cpu.data.yml`。不要挂载包含 Ollama 开发默认值的根目录 `.env`。
`docker/cpu.env` 已同时排除 Git 与镜像构建上下文；不要将真实密钥写入 Dockerfile。

默认只绑定回环地址，仍由部署边界提供 TLS 和访问控制。存活检查通过后，按第 5 节和
[测试与验收](testing.md) 分别执行真实云端 Agent 与 CPU OCR 业务验收；云端请求会携带
相应业务内容。无可用云端凭据或业务照片时，这两项应记录为未验证，不能用配置解析
或镜像构建通过代替。
