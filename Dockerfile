# DQ Sentinel — single Cloud Run container: uvicorn + the agent loop + the
# pre-baked Fivetran MCP server.
FROM python:3.11-slim

# git: required to install the Fivetran MCP server from its GitHub repo.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# uv (pinned installer) for fast, lockfile-faithful installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_TOOL_BIN_DIR=/usr/local/bin \
    PYTHONUNBUFFERED=1

# Pre-install the Fivetran MCP server at build time so call_tool spawns the
# local `fivetran-mcp` binary instead of cold-cloning from GitHub on every
# Fivetran call. The app picks it up via the env overrides below.
RUN uv tool install git+https://github.com/fivetran/fivetran-mcp
ENV FIVETRAN_MCP_COMMAND=fivetran-mcp \
    FIVETRAN_MCP_ARGS=""

WORKDIR /app

# Install deps from the committed lockfile first (layer-cached), then the app.
COPY pyproject.toml uv.lock README.md ./
COPY dq_sentinel ./dq_sentinel
RUN uv sync --frozen --no-dev

# Vertex / Gemini config (global is mandatory for Gemini 3.x; regional 403s).
ENV GOOGLE_GENAI_USE_VERTEXAI=true \
    GOOGLE_CLOUD_PROJECT=agent-era \
    GOOGLE_CLOUD_LOCATION=global

# Shell-form CMD so $PORT (Cloud Run injects it, default 8080) expands.
CMD uv run --no-dev uvicorn dq_sentinel.web.app:app --host 0.0.0.0 --port ${PORT:-8080}
