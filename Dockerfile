FROM ghcr.io/astral-sh/uv:0.9.26 AS uv

FROM python:3.14-slim AS builder

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --frozen --no-dev --no-install-project
COPY cc_logger ./cc_logger
RUN uv sync --frozen --no-dev --no-editable

FROM builder AS dev-builder
RUN uv sync --frozen --extra dev

FROM python:3.14-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system --gid 10001 cc_logger \
    && useradd --uid 10001 --gid cc_logger --no-create-home \
        --shell /usr/sbin/nologin cc_logger

WORKDIR /app
EXPOSE 8080

FROM runtime AS prod

COPY --from=builder --chown=cc_logger:cc_logger /opt/venv /opt/venv
USER cc_logger
CMD ["cc-logger"]

FROM runtime AS dev

COPY --from=dev-builder --chown=cc_logger:cc_logger /opt/venv /opt/venv
COPY --chown=cc_logger:cc_logger cc_logger ./cc_logger
COPY --chown=cc_logger:cc_logger tests ./tests
USER cc_logger
CMD ["cc-logger"]
