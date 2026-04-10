# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md /app/
COPY src /app/src
COPY templates /app/templates
COPY plugins /app/plugins

# Copy frontend dist from Stage 1
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

RUN uv sync --frozen

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "magi.webui_backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
