FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[db,telegram,research]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

CMD ["python", "-m", "t212ai", "run", "bot"]
