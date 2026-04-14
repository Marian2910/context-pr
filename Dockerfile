FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scripts/action-entrypoint.sh /action-entrypoint.sh

RUN python -m pip install --upgrade pip \
    && python -m pip install .

ENTRYPOINT ["/action-entrypoint.sh"]
