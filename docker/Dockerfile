# Stage 1: Builder
FROM python:3.13-alpine AS builder
LABEL org.opencontainers.image.description="A discord bot built on discord.py with a FastAPI app providing a healthcheck endpoint"
LABEL org.opencontainers.image.source=https://github.com/cyberops7/discord_bot

# Install build dependencies
RUN apk add --no-cache binutils

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

# Set up build directory
WORKDIR /build

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-cache --no-default-groups

# Strip debug symbols to reduce size
RUN find .venv -name "*.so" -exec strip --strip-debug {} \; || true

# Stage 2: Runtime
FROM python:3.13-alpine

# Set up default env vars
ENV API_PORT=8080 \
    APP_HOME=/app \
    LOG_DIR=/app/log \
    LOG_FILE=bot.log \
    LOG_LEVEL_FILE=INFO \
    LOG_LEVEL_STDOUT=INFO \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Update base packages and install essential tools (vim and bash for debugging)
RUN apk -U upgrade --no-cache && \
    apk add --no-cache bash vim

# Create user and group
RUN addgroup --system --gid 10001 appgroup && \
    adduser --system --uid 10001 --ingroup appgroup --home $APP_HOME appuser && \
    mkdir -p $LOG_DIR

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appgroup /build/.venv /app/.venv

# Copy application code
COPY --chown=appuser:appgroup ./ $APP_HOME

# Set working directory
WORKDIR $APP_HOME

# Switch to non-root user
USER appuser

# Use full path to venv python to ensure venv is used
CMD ["/app/.venv/bin/python", "main.py"]

# Python-based healthcheck using stdlib
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD /app/.venv/bin/python docker/healthcheck.py
