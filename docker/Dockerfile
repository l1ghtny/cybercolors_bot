FROM python:3.14-alpine

COPY --from=ghcr.io/astral-sh/uv:0.11.30 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PATH="/home/discord-bot/.venv/bin:$PATH"

WORKDIR /home/discord-bot/
RUN mkdir logs

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY api ./api
COPY alembic ./alembic
COPY scripts ./scripts
COPY main.py .
COPY alembic.ini .

CMD ["python", "main.py"]
