# syntax=docker/dockerfile:1.7
# 生产业务 API 镜像。模型服务使用 Dockerfile.vllm 单独部署，二者不合并环境。
# 构建与运行说明见 docs/docker.md。

ARG CUDA_IMAGE=nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.19

FROM ${UV_IMAGE} AS uv

# builder/runtime 共用发行版与解释器路径，避免复制 venv 后链接到不存在的 Python。
# CUDA/cuDNN 用户态库随镜像发布；宿主机只需 NVIDIA 驱动与 Container Toolkit。
FROM ${CUDA_IMAGE} AS python-base
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3.12 python3.12-venv ca-certificates \
      libgl1 libglib2.0-0 libgomp1 libsm6 libxext6 curl tini \
 && rm -rf /var/lib/apt/lists/*

FROM python-base AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_CACHE_DIR=/root/.cache/uv
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
# 先安装锁定依赖，改业务代码时复用该层；生产不安装 dev 依赖，OCR 使用 GPU CUDA EP。
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --extra ocr-gpu --python /usr/bin/python3.12

FROM python-base AS runtime

LABEL org.opencontainers.image.title="highway-agent-api" \
      org.opencontainers.image.description="公路工程业务智能体 API（不含模型服务）"

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/tmp \
    API_HOST=0.0.0.0 \
    API_PORT=8309

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
# 无 GPU 的构建机也能检查用户态库；驱动与 CUDA EP 实际初始化仍需在目标 GPU 验收。
RUN python -c 'import ctypes, cv2, onnxruntime; [ctypes.CDLL(name) for name in ("libcudart.so.12", "libcublas.so.12", "libcublasLt.so.12", "libcufft.so.11", "libcurand.so.10", "libcudnn.so.9")]'
COPY app ./app
# 生产启动前的配置自检，拒绝 Mac/Ollama 默认值与占位密钥。
COPY scripts/prod/check_config.py ./scripts/prod/check_config.py
COPY docker/entrypoint-api.sh /usr/local/bin/entrypoint-api.sh
# 只创建运行时目录与挂载点；LLM 与 OCR 模型都不打进镜像，由宿主机预置后只读挂载。
RUN chmod 0755 /usr/local/bin/entrypoint-api.sh \
 && mkdir -p data/ocr/templates data/ocr/admin data/ocr/assets data/ocr/projects data/ocr/models \
 && chown -R app:app data scripts

EXPOSE 8309
USER app

# 只检查进程存活；模型可用性由 /ready 或编排健康检查单独确认。
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${API_PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint-api.sh"]
