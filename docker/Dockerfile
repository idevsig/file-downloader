### === Build stage === ###
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN <<EOF
    apt-get update -y
    apt-get install -y curl bash xz-utils
    curl -L fx4.cn/cnmirror | bash -s -- os uv
    apt-get install -y aria2 jq
EOF

RUN . /etc/environment && \
    uv lock --no-upgrade && \
    uv sync --locked --no-install-project --no-editable && \
    uv pip install .

RUN curl -L fx4.cn/vsd | bash

### === Runtime stage === ###
FROM python:3.13-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /usr/local/bin/vsd /usr/local/bin/vsd

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends aria2 ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
    
CMD ["fetcher"]