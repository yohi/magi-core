# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

RUN pip install --no-cache-dir uv

# Pre-create necessary directories to ensure ownership
RUN mkdir -p /app/src /app/templates /app/plugins /app/frontend/dist && chown -R appuser:appgroup /app

# Copy application files and frontend dist
# Use --chown directly with COPY for efficiency
COPY --chown=appuser:appgroup pyproject.toml uv.lock README.md /app/
COPY --chown=appuser:appgroup src /app/src
COPY --chown=appuser:appgroup templates /app/templates
COPY --chown=appuser:appgroup plugins /app/plugins
COPY --from=frontend-build --chown=appuser:appgroup /app/frontend/dist /app/frontend/dist

USER appuser

RUN uv sync --frozen

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "magi.webui_backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
