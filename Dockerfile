FROM python:3.12-slim

WORKDIR /app

ARG APP_VERSION=0.2.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libgomp1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "from rapidocr import RapidOCR, LangRec, ModelType, OCRVersion; \
RapidOCR(params={'Rec.lang_type': LangRec('eslav'), 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE}); \
RapidOCR(params={'Rec.lang_type': LangRec('latin'), 'Rec.ocr_version': OCRVersion.PPOCRV5, 'Rec.model_type': ModelType.MOBILE}); \
print('OCR warmup OK')"

COPY pyproject.toml .
COPY src ./src

ENV PYTHONPATH=/app/src
ENV CERT_PARSER_VERSION=${APP_VERSION}
ENV CACHE_PATH=/app/data/cache.sqlite
ENV HOST=0.0.0.0
ENV PORT=8000

RUN mkdir -p /app/data \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

CMD ["uvicorn", "cert_parser.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
