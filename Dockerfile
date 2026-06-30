# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — Aria + vLLM serving stack
#
# Build variants:
#   CUDA/CPU:  docker build --build-arg BASE_IMAGE=vllm/vllm-openai:latest -t aria .
#   ROCm:      docker build --build-arg BASE_IMAGE=vllm/vllm-openai-rocm:latest -t aria-rocm .
#
# Run:
#   docker run -p 9876:9876 \
#     -v ./data:/app/data \
#     --env-file .env \
#     ghcr.io/malvavisc0/aria-ai-cuda:latest
# ─────────────────────────────────────────────────────────────────────────────

ARG BASE_IMAGE=vllm/vllm-openai:latest
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.source="https://github.com/malvavisc0/aria-ai"
LABEL org.opencontainers.image.description="Aria — AI Assistant with web UI and local LLM support"
LABEL org.opencontainers.image.licenses="MIT"

# ── Install Aria ──────────────────────────────────────────────────────────────
# `--no-config` prevents Aria's [tool.uv] pytorch-cpu index (which pins CPU
# torch for the source-tree venv) from leaking into this image. The vLLM base
# image already ships GPU torch for vLLM inference; aria-ai's torch dep is
# satisfied by that preinstalled copy and must NOT be downgraded to CPU.
RUN uv pip install --no-config --system --break-system-packages --no-cache aria-ai

# ── Runtime configuration ─────────────────────────────────────────────────────
ENV ARIA_HOME=/app/data

# ── Create data directory for persistent storage ──────────────────────────────
RUN mkdir -p /app/data
WORKDIR /app

# ── Expose Chainlit web UI port ───────────────────────────────────────────────
EXPOSE 9876

# ── Entrypoint ────────────────────────────────────────────────────────────────
ENTRYPOINT ["aria", "server", "run"]