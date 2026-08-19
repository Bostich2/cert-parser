FROM python:3.12-slim

WORKDIR /app

ARG APP_VERSION=0.2.0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY src ./src

ENV PYTHONPATH=/app/src
ENV SERT_PARSER_VERSION=${APP_VERSION}
ENV CACHE_PATH=/app/data/cache.sqlite
ENV HOST=0.0.0.0
ENV PORT=8000

RUN mkdir -p /app/data
EXPOSE 8000

CMD ["uvicorn", "sert_parser.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
