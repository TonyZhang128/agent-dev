# syntax=docker/dockerfile:1.7
# 生产业务 API 镜像。模型服务使用 Dockerfile.vllm 单独部署，二者不合并环境。
# 构建与运行说明见 docs/docker.md。

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.19

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_CACHE_DIR=/root/.cache/uv
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
# 先安装锁定依赖，改业务代码时复用该层；生产不安装 dev 依赖。
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="highway-agent-api" \
      org.opencontainers.image.description="公路工程业务智能体 API（不含模型服务）"

# opencv-python 依赖 libGL/libglib，onnxruntime 依赖 libgomp；curl 供健康检查。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libgomp1 libsm6 libxext6 curl tini \
 && rm -rf /var/lib/apt/lists/*

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
COPY app ./app
# 生产启动前的配置自检，拒绝 Mac/Ollama 默认值与占位密钥。
COPY scripts/prod/check_config.py ./scripts/prod/check_config.py
COPY docker/entrypoint-api.sh /usr/local/bin/entrypoint-api.sh
RUN chmod 0755 /usr/local/bin/entrypoint-api.sh \
 && mkdir -p data/ocr/templates data/ocr/admin data/ocr/assets data/ocr/projects data/ocr/models \
 && chown -R app:app data scripts

EXPOSE 8309
USER app

# 只检查进程存活；模型可用性由 /ready 或编排健康检查单独确认。
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${API_PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint-api.sh"]
