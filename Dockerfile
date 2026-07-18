# --- Stage 1: build the React SPA ---
FROM node:24-alpine AS web-builder

WORKDIR /web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build


# --- Stage 2: Python runtime serving API + SPA ---
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY api/ ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=web-builder /web/dist /app/web/dist
ENV SILO_WEB_DIST_DIR=/app/web/dist

ENV SILO_HOST=0.0.0.0 SILO_PORT=9550
EXPOSE 9550

VOLUME ["/data", "/games"]

CMD ["sh", "-c", "exec fastapi run --host \"$SILO_HOST\" --port \"$SILO_PORT\""]
