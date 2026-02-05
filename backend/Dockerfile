FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md /app/
COPY src /app/src

RUN uv sync --frozen

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "magi.webui_backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
