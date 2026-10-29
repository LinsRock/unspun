FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /workspace/server
ENV UV_PROJECT_ENVIRONMENT=/opt/test-venv UV_LINK_MODE=copy \
    PYTHONPATH=/workspace/server/src:/workspace/server \
    PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache" \
    UNSPUN_OPENROUTER_API_KEY=""
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-install-project
CMD ["uv", "run", "--no-sync", "pytest"]
