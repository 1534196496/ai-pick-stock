FROM node:24.15.0-bookworm-slim AS codex-runtime

RUN npm install --global --ignore-scripts --no-audit --no-fund @openai/codex@0.147.0

ARG TARGETARCH
ARG CODEX_NPM_REGISTRY=https://registry.npmjs.org
RUN --mount=type=cache,target=/root/.npm set -eu; \
    case "$TARGETARCH" in \
        arm64) CODEX_PLATFORM="linux-arm64" ;; \
        amd64) CODEX_PLATFORM="linux-x64" ;; \
        *) echo "不支持的 Codex 架构: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    npm install --prefix /tmp/codex-native --ignore-scripts --no-audit --no-fund \
        --registry="$CODEX_NPM_REGISTRY" \
        "@openai/codex@0.147.0-${CODEX_PLATFORM}"; \
    cp -R /tmp/codex-native/node_modules/@openai/codex/vendor \
        /usr/local/lib/node_modules/@openai/codex/vendor

FROM python:3.12.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_ROOT_USER_ACTION=ignore \
    UV_COMPILE_BYTECODE=1 \
    UV_HTTP_TIMEOUT=300 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    CODEX_HOME="/home/app/.codex"

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && pip install --no-cache-dir uv==0.11.6

WORKDIR /app

COPY --from=codex-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-runtime /usr/local/lib/node_modules/@openai/codex /usr/local/lib/node_modules/@openai/codex
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
COPY apps/api/agent_skills ./agent_skills
COPY docs/ai-investment-analysis-prompt-spec.md ./docs/ai-investment-analysis-prompt-spec.md

RUN mkdir -p /home/app/.codex \
    && chown -R app:app /app /home/app/.codex

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
