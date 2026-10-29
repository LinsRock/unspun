FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
# Keep the complete shared runtime packages; offline evaluation uses the test image.
COPY server/src/unspun/__init__.py ./src/unspun/
COPY server/src/unspun/api/ ./src/unspun/api/
COPY server/src/unspun/core/ ./src/unspun/core/
COPY server/src/unspun/pipeline/ ./src/unspun/pipeline/
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
WORKDIR /app
RUN groupadd -r app && useradd -r -g app app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --chown=app:app server/alembic.ini /app/alembic.ini
COPY --chown=app:app server/alembic/ /app/alembic/
COPY --chown=app:app config/media_groups.yml config/r1-reader.yml config/r2-hybrid.yml \
    config/scoring.yml config/sources.yml /app/config/
ENV PATH="/app/.venv/bin:$PATH" UNSPUN_CONFIG_DIR=/app/config
USER app
EXPOSE 8000
CMD ["uvicorn", "unspun.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
