FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
RUN pip install --no-cache-dir uv==0.11.8 \
    && uv sync --frozen --no-dev --no-editable \
    && useradd --create-home --uid 10001 app

ENV PATH="/app/.venv/bin:$PATH"
USER app
CMD ["uvicorn", "backend_app.runtimes.platform_admin_api:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
