# API Endpoints

Базовый URL: `http://127.0.0.1:8000` (или хост из `HOST`/`PORT`).

Версия приложения определяется **git-тегами** (`v0.2.0`) через `setuptools-scm` (`src/cert_parser/version.py`). В Docker можно задать `CERT_PARSER_VERSION` / `APP_VERSION`.

## Поиск по номеру

### `POST /api/lookup`

Батч-поиск по массиву номеров. Подробный контракт — [lookup.md](lookup.md).

### `POST /api/lookup/stream`

Потоковый поиск **одного** номера. Content-Type ответа: `application/x-ndjson`.

Ограничение: в `numbers` допускается ровно один непустой элемент, иначе `400`.

События NDJSON:

- `{ "type": "step", "text": "…" }` — шаг обработки (те же строки, что в `trace` и консоли)
- `{ "type": "done", "result": { … } }` — финальный результат (поля как у элемента `results[]` в `/api/lookup`)

UI использует этот endpoint для одиночных запросов из буфера, чтобы шаги появлялись сразу.

## Поиск по наименованию продукции

Контракт, источники, поля хита и коды ошибок — [search-product.md](search-product.md). Поиск по номеру не затронут.

### `POST /api/search-product`

Батч-поиск по массиву наименований.

```json
{
  "queries": ["шины легковые"],
  "limit_per_query": 25
}
```

Ответ: `{ "results": [ … ] }` — плоский список хитов (несколько записей на один запрос). Пустой батч после фильтрации пробелов — `400`. Больше `MAX_BATCH_SIZE` — `400`. `limit_per_query` по умолчанию 25, максимум 50.

Поля сверх lookup: `product_name`, `doc_kind` (`certificate` \| `declaration`), `source` (`fsa_cert` \| `fsa_decl` \| `eaeu_ru` \| `eaeu_other`).

### `POST /api/search-product/stream`

Потоковый поиск **одного** наименования. Content-Type ответа: `application/x-ndjson`.

В `queries` ровно один непустой элемент, иначе `400`.

События NDJSON:

- `{ "type": "step", "text": "…" }` — шаг обработки
- `{ "type": "done", "results": [ … ] }` — массив хитов (**не** `"result"`, как у `/api/lookup/stream`)

UI вызывает поток по одной строке подряд (батч в интерфейсе последовательный). На сервере четыре источника по одному запросу идут параллельно.

## PDF

### `POST /api/extract-pdf`

Извлекает номера из PDF **без** обращения к реестрам.

`multipart/form-data`, поле `file`.

Успех:

```json
{
  "numbers": ["ЕАЭС BY/112 02.01. ТР018 010.02 00276"],
  "error": null,
  "error_code": null,
  "extract_trace": ["…"]
}
```

Если номеров нет: `200`, `error_code=no_numbers_in_pdf`. Повреждённый файл — `400` (`invalid_pdf`).

При превышении `MAX_BATCH_SIZE` список обрезается; в ответе добавляются поля `truncated: true`, `total_found` и `warning`.

### `POST /api/extract-pdf/stream`

Тот же сценарий, но ответ — NDJSON (`step` / `done` или `error`). UI использует его для PDF.

### `POST /api/lookup-pdf`

Извлечение + поиск в реестрах за один запрос.

```json
{
  "extracted_numbers": ["…"],
  "results": [ … ],
  "error": null,
  "error_code": null,
  "extract_trace": ["…"]
}
```

Если номеров нет: `error_code=no_numbers_in_pdf`, `results=[]`.

### `GET /api/certificate-pdf`

Скачивание PDF сертификата из реестра (proxy для источников с сессионным экспортом).

Query-параметры:

- `source` — `eaeu` или `fsa`
- `registry_id` — идентификатор записи в соответствующем реестре

Успех: `200`, `Content-Type: application/pdf`, `Content-Disposition: attachment`.

Ошибки: `400` (неизвестный source), `404` (PDF не найден), `502` (реестр недоступен).

## Excel

### `POST /api/extract-xlsx`

Извлекает непустые строки из столбца A первого листа (`.xlsx`/`.xlsm`) — номера сертификатов или наименования продукции. Поиск в реестрах не выполняется.

```json
{
  "numbers": ["…"],
  "error": null,
  "error_code": null
}
```

Поле ответа по-прежнему `numbers`. Первая строка отбрасывается, если похожа на заголовок (`номер`, `number`, `сертификат`, `наименован`, `товар`, `продукц`, `product`). Пустой столбец A — `error_code=no_numbers_in_xlsx`. Повреждённый файл — `400` (`invalid_xlsx`). Файл больше `XLSX_MAX_BYTES` — `400`. Больше `MAX_BATCH_SIZE` строк в столбце A — `400`.

Дальше клиент вызывает `/api/lookup` или `/api/search-product` / `/api/search-product/stream`.

### `POST /api/export-xlsx`

Экспорт таблицы результатов в `.xlsx`.

`application/json`:

```json
{
  "results": [
    {
      "query": "…",
      "country_code": "BY",
      "url": "…",
      "valid_from": "2024-05-29",
      "valid_until": "2029-05-29",
      "status": "действует",
      "product_name": "…",
      "doc_kind": "certificate",
      "error_code": null
    }
  ]
}
```

Ответ: бинарный файл `cert-parser-results.xlsx` (`Content-Disposition: attachment`). Колонка «Запрос» всегда. Если хотя бы в одной строке есть `product_name` или `doc_kind`, добавляются «Продукция» и «Вид».

## Сервис

### `GET /health/live`

Публичный liveness-endpoint (без ping провайдеров). Используется Docker healthcheck и UI для синхронизации версии.

```json
{
  "status": "ok",
  "version": "0.2.0",
  "generation": 1
}
```

### `GET /health`

Полный healthcheck: ping всех провайдеров реестров (национальные, OData по стране, составные цепочки).

```json
{
  "status": "ok | degraded",
  "version": "0.2.0",
  "generation": 1,
  "belgiss": "ok | unavailable",
  "eaeu_by": "ok | unavailable",
  "belarus": "ok | unavailable",
  "fsa": "ok | unavailable",
  "eaeu_ru": "ok | unavailable",
  "russia": "ok | unavailable",
  "eokno": "ok | unavailable",
  "eaeu_kz": "ok | unavailable",
  "kazakhstan": "ok | unavailable",
  "swis": "ok | unavailable",
  "eaeu_kg": "ok | unavailable",
  "kyrgyzstan": "ok | unavailable",
  "eaeu": "ok | unavailable"
}
```

`version` — semver релиза (git-тег `vX.Y.Z` через setuptools-scm). `generation` увеличивается после `POST /api/reload`. Ключ `eaeu` — провайдер Армении (`ArmeniaProvider`). Составные ключи (`belarus`, `russia`, `kazakhstan`, `kyrgyzstan`) — цепочки `ChainedRegistryProvider`: `ok`, если ping успешен хотя бы у одного шага.

При `AUTH_ENABLED=true` endpoint доступен только пользователям с ролью `admin`.

### `POST /api/reload`

Перезапуск рантайма без остановки uvicorn: закрывает HTTP-клиенты, перечитывает `.env`, пересоздаёт провайдеры, сбрасывает OCR. SQLite-кэш **не** очищается. Во время reload новые lookup-запросы получают `503`; текущие должны завершиться (ожидание до 30 с). Если активные lookup не завершились — `409` с текстом «активны запросы поиска».

```json
{
  "version": "0.2.0",
  "generation": 2,
  "message": "Сервис перезапущен (v0.2.0, generation 2): HTTP-сессии, провайдеры и OCR сброшены"
}
```

### `POST /api/cache/clear`

Очищает SQLite-кэш поиска (`CACHE_PATH`). Во время reload — `503`. При `AUTH_ENABLED=true` — только роль `admin`.

```json
{
  "deleted": 42,
  "message": "Кэш очищен (42 записей)"
}
```

## Авторизация

При `AUTH_ENABLED=true` (production) все маршруты кроме `/login`, `/health/live` и `/static/*` требуют session-cookie после входа.

| Метод | Путь | Доступ |
|-------|------|--------|
| `GET/POST` | `/login` | публичный |
| `POST` | `/logout` | авторизованный |

Пользователи задаются JSON в `AUTH_USERS` (bcrypt-хеши паролей). Генерация: `python scripts/hash_password.py 'password' --username name --role admin|user`.

Админ-действия (`POST /api/cache/clear`, `POST /api/reload`, `GET /health`) — только роль `admin`.

## Коды ошибок (`error_code`)

| Код | Где встречается |
|-----|-----------------|
| `invalid_number` | lookup |
| `unsupported_country` | lookup |
| `query_too_short` | search-product |
| `not_found` | lookup, search-product |
| `source_unavailable` | lookup, search-product |
| `ambiguous` | lookup |
| `no_numbers_in_pdf` | extract-pdf, lookup-pdf |
| `invalid_pdf` | extract-pdf (HTTP 400) |
| `no_numbers_in_xlsx` | extract-xlsx |
| `invalid_xlsx` | extract-xlsx (HTTP 400) |

Правила кэширования lookup — см. [lookup.md](lookup.md). Поиск по продукции кэш не использует.

## Настройки

См. `src/cert_parser/config.py` и `.env.example`.
