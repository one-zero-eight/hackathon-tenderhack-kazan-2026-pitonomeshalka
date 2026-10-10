# Контекст сборки — корень репозитория (backend импортирует пакет experiments):
#   docker build -f backend/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Сначала только манифесты — слой с зависимостями пересобирается редко
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Каталоги, которые сервис пишет сам (evidence запусков, кэш каталога)
RUN mkdir -p backend/results experiments/results

COPY backend/src/ backend/src/
COPY experiments/ experiments/

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Каталог КТРУ (data/) и кэш (experiments/results/) монтируются из compose,
# в образ не копируются. Один воркер — требование backend/README.md.
CMD ["uvicorn", "backend.src.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
