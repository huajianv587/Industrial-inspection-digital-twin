ARG PYTHON_IMAGE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

FROM ${PYTHON_IMAGE} AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

RUN python -m pip install --no-cache-dir uv==0.13.4
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY migrations ./migrations
COPY certs ./certs
COPY alembic.ini ./
COPY configs ./configs
COPY scripts/slurm ./scripts/slurm
COPY scripts/container-entrypoint.sh /usr/local/bin/container-entrypoint

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && chmod 0755 /usr/local/bin/container-entrypoint \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

ENTRYPOINT ["/usr/local/bin/container-entrypoint"]
EXPOSE 8000

CMD ["uvicorn", "inspection_system.platform.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
