# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS web-builder

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build


FROM python:3.12-slim-bookworm AS python-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /build
RUN python -m venv /opt/venv
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install .


FROM python:3.12-slim-bookworm AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    TMPDIR=/tmp \
    AGENT_WEB_HOST=0.0.0.0 \
    AGENT_WEB_PORT=8000 \
    AGENT_WEB_DATABASE_PATH=/data/agent-web.sqlite3 \
    BABYBUDDY_AUDIT_PATH=/data/audit/events.jsonl

RUN groupadd --gid 10001 jarvis \
    && useradd --uid 10001 --gid jarvis --no-create-home --shell /usr/sbin/nologin jarvis \
    && install --directory --owner=jarvis --group=jarvis /app /data /data/audit

WORKDIR /app
COPY --from=python-builder /opt/venv /opt/venv
COPY --from=web-builder /build/web/dist ./web/dist

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

ENTRYPOINT ["agent-web"]
