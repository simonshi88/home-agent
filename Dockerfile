# syntax=docker/dockerfile:1.7


# ============================================================
# Build stage
# ============================================================

FROM ubuntu:26.04 AS build

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装 Python 3.14 + Node.js 22
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        python3 \
        python3-venv \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install --yes --no-install-recommends nodejs \
    && npm config set registry https://registry.npmmirror.com \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build


# ============================================================
# Python build
# ============================================================

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN python3 -m venv /opt/venv

RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install .


# ============================================================
# Web build
# ============================================================

COPY web/package.json web/package-lock.json ./web/

RUN --mount=type=cache,target=/root/.npm \
    npm --prefix web ci --no-audit --no-fund

COPY web ./web

RUN npm --prefix web run build


# ============================================================
# Runtime stage
# ============================================================

FROM ubuntu:26.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    TMPDIR=/tmp \
    AGENT_WEB_HOST=0.0.0.0 \
    AGENT_WEB_PORT=8000 \
    AGENT_WEB_DATABASE_PATH=/data/agent-web.sqlite3 \
    BABYBUDDY_AUDIT_PATH=/data/audit/events.jsonl


# Python runtime + 非 root 用户
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 jarvis \
    && useradd \
        --uid 10001 \
        --gid jarvis \
        --no-create-home \
        --shell /usr/sbin/nologin \
        jarvis \
    && install \
        --directory \
        --owner=jarvis \
        --group=jarvis \
        /app \
        /data \
        /data/audit

WORKDIR /app


# ============================================================
# Copy build artifacts
# ============================================================

COPY --from=build /opt/venv /opt/venv
COPY --from=build /build/src ./src
COPY --from=build /build/web/dist ./web/dist


# ============================================================
# Runtime
# ============================================================

USER 10001:10001

EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=15s \
    --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

ENTRYPOINT ["agent-web"]