# YouTube2SlackThread Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create app user
RUN useradd -m -u 1000 app

# Set working directory
WORKDIR /app

# Copy all application files first
COPY --chown=app:app . .

# Create necessary directories
RUN mkdir -p downloads logs && chown -R app:app downloads logs

# Install dependencies (as root for caching, then fix permissions)
RUN uv sync --frozen --no-dev && chown -R app:app .venv

# Link onnxruntime shared library for sherpa-onnx (fail-fast if not found)
RUN .venv/bin/python3 - <<'PY' \
import pathlib, sysconfig \
site = pathlib.Path(".venv/lib").glob("python*/site-packages") \
site = next(site) \
capi = site / "onnxruntime" / "capi" \
lib = next(capi.glob("libonnxruntime.so.*"), None) \
if lib is None: \
    raise SystemExit("onnxruntime shared library not found") \
sherpa_lib = site / "sherpa_onnx" / "lib" \
target = sherpa_lib / "libonnxruntime.so" \
if not target.exists(): \
    target.symlink_to(lib) \
print(f"linked {target} -> {lib}") \
PY

# Set library path for sherpa-onnx + onnxruntime
ENV LD_LIBRARY_PATH="/app/.venv/lib/python3.11/site-packages/onnxruntime/capi:/app/.venv/lib/python3.11/site-packages/sherpa_onnx/lib:${LD_LIBRARY_PATH}"

# Verify sherpa-onnx can be imported
RUN .venv/bin/python3 -c "import sherpa_onnx"

# Create models directory for ReazonSpeech
RUN mkdir -p models && chown -R app:app models

# Switch to app user
USER app

# Expose ports (Slack server: 42389, Web UI: 42390)
EXPOSE 42389 42390

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:42389/health || exit 1

# Default command - run Slack server
CMD ["uv", "run", "youtube2slack", "serve", "--port", "42389"]
