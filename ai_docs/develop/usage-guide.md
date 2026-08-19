# Usage Guide: Парсер сертификатов ЕАЭС

Этот сервис — веб-приложение (FastAPI + HTML/JS), которое по регистрационному номеру ищет карточку сертификата соответствия в национальном реестре и возвращает ссылку и срок действия.

Текущая реализация ищет сертификаты **Беларуси (BY)**, **России (RU)**, **Казахстана (KZ)**, **Кыргызстана (KG)** и **Армении (AM)**. Номер можно вставить из буфера, загрузить из Excel (столбец A) или извлечь из PDF.

## Основной запуск

### Требования

- Python **3.12+**
- Убедитесь, что порт `8000` свободен (или поменяйте `PORT` в `.env`).

### Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Для OCR в PDF нужны `rapidocr` и `onnxruntime` (уже в `requirements.txt`). При первом запуске RapidOCR может скачать модели.

### Конфигурация

```bash
copy .env.example .env
```

Сервис читает `.env` автоматически (через `pydantic-settings`).

### Запуск FastAPI

```bash
set PYTHONPATH=src
uvicorn sert_parser.api.app:app --reload --host 127.0.0.1 --port 8000
```

Откройте в браузере: `http://127.0.0.1:8000`

### Docker

```bash
docker compose up --build
```

Сервис: `http://localhost:8000`.

## Использование через UI

На главной странице три карточки источника:

| Карточка | Описание |
|----------|----------|
| **Из буфера** | Один или несколько номеров, по одному на строку. Кнопка вставки из буфера обмена. |
| **Из Excel** | Загрузка `.xlsx`/`.xlsm`; номера читаются из столбца A первого листа. |
| **Из PDF** | Файлы или папка (клик, drag-and-drop). Текстовый слой, при необходимости OCR. |

### Результаты

Таблица: номер, страна (флаги в шапке), ссылка, «действует с» / «действует до», статус, ошибка.

- **Пагинация** — выбор «записей на страницу» (10 / 20 / 50).
- **Экспорт в Excel** — скачивает текущие результаты через `POST /api/export-xlsx`.

### Ход поиска

Блок «Ход поиска» показывает шаги текущего запроса (разбор номера, GET/POST, сколько строк). Те же строки пишутся в консоль uvicorn. Для Казахстана (eokno.gov.kz) ответ часто занимает 10–30 секунд — кнопки в это время неактивны.

UI для одиночных запросов и PDF использует **потоковые** endpoint'ы (`/api/lookup/stream`, `/api/extract-pdf/stream`), чтобы шаги появлялись сразу.

### Настройки (шестерёнка в шапке)

- **Сбросить кэш** — `POST /api/cache/clear` (SQLite-кэш lookup).
- **Полная перезагрузка сервиса** — `POST /api/reload` (HTTP-сессии, провайдеры, OCR; кэш не трогается).

## Использование через API

Полный список endpoint'ов: [api/endpoints.md](api/endpoints.md). Детали lookup: [api/lookup.md](api/lookup.md).

### Типичный сценарий (батч)

```bash
curl -X POST http://127.0.0.1:8000/api/lookup ^
  -H "Content-Type: application/json" ^
  -d "{\"numbers\":[\"ЕАЭС BY/112 02.01. ТР018 010.02 00276\"]}"
```

### Excel (двухшаговый)

1. `POST /api/extract-xlsx` — извлечь номера из файла.
2. `POST /api/lookup` — поиск по списку.

### PDF

- Только извлечение: `POST /api/extract-pdf` → затем `/api/lookup`.
- Извлечение + поиск: `POST /api/lookup-pdf`.
- Потоковое извлечение (как UI): `POST /api/extract-pdf/stream`.

## Переменные окружения

Сервис использует `Settings` из `src/sert_parser/config.py`. Все значения имеют дефолты (см. `.env.example`).

| Переменная | Назначение |
|------------|------------|
| `HOST`, `PORT` | Адрес uvicorn |
| `BELGISS_API_URL`, `BELGISS_PUBLIC_URL` | Беларусь |
| `FSA_BASE_URL` | Россия (с не-РФ IP часто 403 — задайте `HTTPS_PROXY`) |
| `EOKNO_REGISTER_URL` | Казахстан |
| `SWIS_BASE_URL` | Кыргызстан |
| `EAEU_ODATA_URL`, `EAEU_REGISTER_VIEW_URL` | Армения (OData ЕАЭС) |
| `REQUEST_TIMEOUT_SECONDS` | Таймаут HTTP |
| `LOOKUP_CONCURRENCY` | Параллельность внутри батча |
| `LOOKUP_DELAY_SECONDS` | Задержка после успешного lookup |
| `CACHE_PATH`, `CACHE_TTL_SECONDS` | SQLite-кэш |
| `MAX_BATCH_SIZE` | Лимит номеров в батче (по умолчанию 100) |
| `PDF_MAX_BYTES`, `PDF_OCR_MAX_PAGES`, `PDF_OCR_ENABLED`, `PDF_OCR_REC_LANG` | PDF/OCR |
| `XLSX_MAX_BYTES` | Максимальный размер Excel (по умолчанию 15 МБ) |
| `HTTP_SSL_VERIFY` | TLS для всех исходящих запросов к реестрам |
| `BELGISS_SSL_VERIFY` | Устаревший alias для `HTTP_SSL_VERIFY` |
| `LOG_LEVEL` | Уровень логов (`INFO` по умолчанию) |

## Ограничения и допущения

- Парсер номера извлекает страну из кода в строке (`BY`, `RU`, `KZ`, `AM`, `KG`).
- Армения: национальный реестр [ARMNAB](https://armnab.am/ru/eaeu/certificates); автоматический поиск — OData [tech.eaeunion.org](https://tech.eaeunion.org) (часто 5–15 с).
- PDF: текстовый слой, затем OCR (`PDF_OCR_ENABLED`, язык `eslav` по умолчанию).
- Excel: первый лист, столбец A; первая строка отбрасывается, если похожа на заголовок.
- Ошибки одного элемента батча не прерывают обработку остальных.
- Поле `results[].trace` — шаги поиска; в кэш не сохраняется.

## Тесты

```bash
pip install -r requirements-dev.txt
set PYTHONPATH=src
pytest
```
