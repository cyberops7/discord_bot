# Stage 1: Build Stage
FROM python:3.13-alpine
LABEL org.opencontainers.image.description="A discord bot built on discord.py with a FastAPI app providing a healthcheck endpoint"
LABEL org.opencontainers.image.source=https://github.com/cyberops7/discord_bot

# Set up default env vars
ENV API_PORT=8080 \
    APP_HOME=/app \
    LOG_DIR=/app/log \
    LOG_FILE=bot.log \
    LOG_LEVEL_FILE=INFO \
    LOG_LEVEL_STDOUT=INFO \
    PATH="/root/.local/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Update base packages and install Alpine dependencies
RUN apk -U upgrade --no-cache && \
    apk add --no-cache \
        bash \
        curl \
        jq

# Install `uv`
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy project files
COPY ./ $APP_HOME

# Create application directory and set permissions
RUN addgroup --system --gid 10001 appgroup && \
    adduser --system --uid 10001 --ingroup appgroup --home $APP_HOME appuser && \
    mkdir -p $LOG_DIR && \
    chown -R appuser:appgroup $APP_HOME

# Set working directory
WORKDIR $APP_HOME

# Switch to non-root user
USER appuser

# Create the venv and install runtime dependencies
RUN uv sync --frozen --no-cache --no-default-groups

# Run the bot
CMD ["uv", "run", "--no-default-groups", "main.py"]

# Placeholder healthcheck until a real one is ready
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -s http://localhost:8080/healthcheck | jq -e '.status == "ok"' > /dev/null || exit 1
