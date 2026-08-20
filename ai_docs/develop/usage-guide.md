# Usage Guide: Парсер сертификатов ЕАЭС

**Дата обновления:** 2026-08-20

Этот сервис — веб-приложение (FastAPI + HTML/JS). Два режима на главной странице:

- **Поиск по сертификату** — по регистрационному номеру: карточка в национальном реестре, ссылка и срок действия (BY, RU, KZ, KG, AM).
- **Поиск по товару** — по фрагменту формулировки продукции из документа (не артикул магазина): сертификаты и декларации FSA плюс OData ЕАЭС.

Номер или наименование можно вставить из буфера или загрузить из Excel (столбец A). Для режима по сертификату номера также извлекаются из PDF.

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
uvicorn cert_parser.api.app:app --reload --host 127.0.0.1 --port 8000
```

Откройте в браузере: `http://127.0.0.1:8000`

### Docker

```bash
docker compose up --build
```

Сервис: `http://localhost:8000`.

## Использование через UI

Две вкладки вверху страницы.

### Вкладка «Поиск по сертификату»

Три карточки источника (как раньше):

| Карточка | Описание |
|----------|----------|
| **Из буфера** | Один или несколько номеров, по одному на строку. Кнопка вставки из буфера обмена. |
| **Из Excel** | Загрузка `.xlsx`/`.xlsm`; номера читаются из столбца A первого листа (`POST /api/extract-xlsx`). |
| **Из PDF** | Файлы или папка (клик, drag-and-drop). Текстовый слой, при необходимости OCR. |

### Вкладка «Поиск по товару»

| Карточка | Описание |
|----------|----------|
| **Наименования из буфера** | Одно наименование на строку; вставка из буфера. |
| **Из списка Excel** | Столбец A первого листа; тот же `POST /api/extract-xlsx`, затем поиск по строкам. |

PDF в этой вкладке нет. Строки обрабатываются **последовательно**; по каждому имени четыре источника на сервере идут параллельно. Ищется фрагмент формулировки из документа.

### Результаты

Таблица: запрос, номер, страна (флаги в шапке), **продукция**, **вид** (сертификат / декларация), ссылка на карточку, **PDF**, «действует с» / «действует до», статус, ошибка.

- **Пагинация** — выбор «записей на страницу» (10 / 20 / 50).
- **Экспорт в Excel** — `POST /api/export-xlsx`. Для поиска по товару в файл попадают колонки «Запрос», «Продукция», «Вид».
- **Повторить** — у строк с ошибкой реестра в режиме по сертификату: меню «⋮» по наведению; повторяет lookup только для этого номера.

### Ход поиска

Блок «Ход поиска» показывает шаги текущего запроса (разбор номера, GET/POST, сколько строк). Те же строки пишутся в консоль uvicorn.

Для **BY, RU, KZ, KG** поиск идёт **цепочкой из двух источников**. По умолчанию (`LOOKUP_EAEU_FIRST=true`) сначала OData [tech.eaeunion.org](https://tech.eaeunion.org), при `not_found` или недоступности источника — национальный реестр. При `LOOKUP_EAEU_FIRST=false` порядок обратный. Армения (AM) использует только OData ЕАЭС.

В trace первый шаг цепочки выглядит так: «Провайдер: Беларусь, tech.eaeunion.org, при отсутствии — api.belgiss.by». При fallback в trace появятся строки вида «BY: tech.eaeunion.org — не найден, пробуем api.belgiss.by».

Для Казахстана (eokno.gov.kz) ответ часто занимает 10–30 секунд — кнопки в это время неактивны.

UI для одиночных запросов по номеру и PDF использует **потоковые** endpoint'ы (`/api/lookup/stream`, `/api/extract-pdf/stream`). Для поиска по товару — `/api/search-product/stream` (в `done` массив `results`, не объект `result`).

### Настройки (шестерёнка в шапке)

- **Сбросить кэш** — `POST /api/cache/clear` (SQLite-кэш lookup).
- **Полная перезагрузка сервиса** — `POST /api/reload` (HTTP-сессии, провайдеры, OCR; кэш не трогается).

## Использование через API

Полный список endpoint'ов: [api/endpoints.md](api/endpoints.md). Lookup по номеру: [api/lookup.md](api/lookup.md). Поиск по продукции: [api/search-product.md](api/search-product.md).

### Типичный сценарий (батч)

```bash
curl -X POST http://127.0.0.1:8000/api/lookup ^
  -H "Content-Type: application/json" ^
  -d "{\"numbers\":[\"ЕАЭС BY/112 02.01. ТР018 010.02 00276\"]}"
```

### Excel (двухшаговый)

1. `POST /api/extract-xlsx` — строки из столбца A.
2. `POST /api/lookup` — поиск по номерам **или** `POST /api/search-product` / `/api/search-product/stream` — по наименованиям.

### Поиск по продукции

```bash
curl -X POST http://127.0.0.1:8000/api/search-product ^
  -H "Content-Type: application/json" ^
  -d "{\"queries\":[\"шины легковые\"],\"limit_per_query\":25}"
```

Потоковый вариант (один запрос): `POST /api/search-product/stream`, NDJSON `step` / `done` с `"results": [ … ]`.

### PDF

- Только извлечение: `POST /api/extract-pdf` → затем `/api/lookup`.
- Извлечение + поиск: `POST /api/lookup-pdf`.
- Потоковое извлечение (как UI): `POST /api/extract-pdf/stream`.

## Переменные окружения

Сервис использует `Settings` из `src/cert_parser/config.py`. Все значения имеют дефолты (см. `.env.example`).

| Переменная | Назначение |
|------------|------------|
| `HOST`, `PORT` | Адрес uvicorn |
| `BELGISS_API_URL`, `BELGISS_PUBLIC_URL` | Беларусь |
| `FSA_BASE_URL` | Россия (с не-РФ IP часто 403 — задайте `HTTPS_PROXY`) |
| `EOKNO_REGISTER_URL` | Казахстан |
| `SWIS_BASE_URL` | Кыргызстан |
| `EAEU_ODATA_URL`, `EAEU_REGISTER_VIEW_URL` | Армения (OData ЕАЭС) |
| `EAEU_PLATFORM_URL`, `EAEU_CARD_PDF_PROCESS_ID` | Экспорт PDF карточки через tech.eaeunion.org |
| `REQUEST_TIMEOUT_SECONDS` | Таймаут HTTP |
| `LOOKUP_CONCURRENCY` | Параллельность внутри батча |
| `LOOKUP_DELAY_SECONDS` | Задержка после успешного lookup |
| `LOOKUP_EAEU_FIRST` | Порядок цепочки для BY/RU/KZ/KG: `true` — сначала OData ЕАЭС, `false` — сначала национальный реестр (по умолчанию `true`) |
| `CACHE_PATH`, `CACHE_TTL_SECONDS` | SQLite-кэш |
| `MAX_BATCH_SIZE` | Лимит номеров в батче (по умолчанию 100) |
| `PDF_MAX_BYTES`, `PDF_OCR_MAX_PAGES`, `PDF_OCR_ENABLED`, `PDF_OCR_REC_LANG` | PDF/OCR |
| `XLSX_MAX_BYTES` | Максимальный размер Excel (по умолчанию 15 МБ) |
| `HTTP_SSL_VERIFY` | TLS для всех исходящих запросов к реестрам |
| `BELGISS_SSL_VERIFY` | Устаревший alias для `HTTP_SSL_VERIFY` |
| `LOG_LEVEL` | Уровень логов (`INFO` по умолчанию) |

### Git hooks для версии

После `git commit` / `merge` / `checkout` можно автоматически перегенерировать `src/cert_parser/_version.py`:

```bash
python scripts/install_git_hooks.py
```

Подробнее — раздел «Версионирование» в [README.md](../../README.md).

## Ограничения и допущения

- Парсер номера извлекает страну из кода в строке (`BY`, `RU`, `KZ`, `AM`, `KG`).
- **BY, RU, KZ, KG** — цепочка OData ЕАЭС + национальный реестр (`ChainedRegistryProvider`, см. `src/cert_parser/infrastructure/registries/chained.py`). Национальные источники: БелГИСС (BY), pub.fsa.gov.ru (RU), eokno.gov.kz (KZ), swis.trade.kg (KG).
- **Армения (AM)** — только OData [tech.eaeunion.org](https://tech.eaeunion.org) (карточки ARMNAB; часто 5–15 с).
- PDF: текстовый слой, затем OCR (`PDF_OCR_ENABLED`, язык `eslav` по умолчанию).
- Excel: первый лист, столбец A; первая строка отбрасывается, если похожа на заголовок (в том числе «продукция» / «товар»).
- Поиск по товару: минимум 4 символа в запросе; источники FSA (сертификаты и декларации) и OData ЕАЭС (RU и не-RU); в выдаче сначала Россия. Кэш lookup не используется.
- Ошибки одного элемента батча не прерывают обработку остальных.
- Поле `results[].trace` — шаги поиска; в кэш lookup не сохраняется.

## Тесты

```bash
pip install -r requirements-dev.txt
set PYTHONPATH=src
pytest
```
