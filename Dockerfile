FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH=/srv/.venv/bin:$PATH
COPY app app
WORKDIR /srv/app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8787"]
