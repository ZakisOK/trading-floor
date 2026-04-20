FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip \
 && pip install hatchling \
 && pip install \
        "anthropic>=0.30" \
        "langgraph>=0.2" \
        "ccxt>=4.3" \
        "httpx>=0.27" \
        "alpaca-py>=0.26" \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "sqlalchemy[asyncio]>=2.0" \
        "asyncpg>=0.29" \
        "alembic>=1.13" \
        "redis>=5.0" \
        "structlog>=24.1" \
        "opentelemetry-api>=1.25" \
        "opentelemetry-sdk>=1.25" \
        "pydantic>=2.7" \
        "pydantic-settings>=2.3" \
        "hmmlearn>=0.3" \
        "numpy>=1.26" \
        "pandas>=2.2" \
        "scipy>=1.13" \
        "yfinance>=0.2" \
        "uuid6>=2024.7"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
