FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup --system contextpr \
    && adduser --system --ingroup contextpr contextpr

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scripts/action-entrypoint.sh /action-entrypoint.sh

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && chown -R contextpr:contextpr /app /action-entrypoint.sh

USER contextpr

ENTRYPOINT ["/action-entrypoint.sh"]
