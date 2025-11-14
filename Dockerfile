FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Create app user
RUN useradd -m -u 1000 app
USER app
WORKDIR /app

# Copy application files
COPY --chown=app:app . .

# Install Python dependencies
RUN uv pip install -e .

# Create necessary directories
RUN mkdir -p downloads logs

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

# Run application
CMD ["uv", "run", "python", "-m", "youtube2slack"]