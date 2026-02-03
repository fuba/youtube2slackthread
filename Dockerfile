# YouTube2SlackThread Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create app user
RUN useradd -m -u 1000 app

# Set working directory
WORKDIR /app

# Copy dependency files first for better caching
COPY --chown=app:app pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application files
COPY --chown=app:app . .

# Create necessary directories
RUN mkdir -p downloads logs && chown -R app:app downloads logs

# Switch to app user
USER app

# Expose ports (Slack server: 42389, Web UI: 42390)
EXPOSE 42389 42390

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:42389/health || exit 1

# Default command - run Slack server
CMD ["uv", "run", "youtube2slack", "serve", "--port", "42389"]
