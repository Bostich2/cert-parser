# API: `POST /api/lookup`

Endpoint для поиска карточки сертификата по регистрационному номеру(ам).

Принимает батч номеров и возвращает массив `results` с результатом по каждому элементу.

Поиск по **наименованию продукции** — отдельные маршруты `POST /api/search-product` и `POST /api/search-product/stream` ([search-product.md](search-product.md)). Контракт lookup не менялся.

Остальные endpoint'ы (PDF, Excel, export, cache, reload, health) — см. [endpoints.md](endpoints.md).

## Request

`POST /api/lookup`

Content-Type: `application/json`

Тело запроса:

```json
{
  "numbers": ["ЕАЭС BY/112 02.01. ТР018 010.02 00276", "ЕАЭС BY/..."]
}
```

Правила:

- `numbers` — массив строк.
- Внутри сервиса пустые/пробельные строки отфильтровываются.
- Если после фильтрации не осталось элементов — `400` с `detail`.
- Максимальный размер батча: `MAX_BATCH_SIZE` (дефолт `100`).

Пример ошибок HTTP:

```json
{
  "detail": "Передайте хотя бы один номер сертификата"
}
```

## Response

Успешный ответ (всегда `200` при валидном запросе):

```json
{
  "results": [
    {
      "query": "…",
      "normalized": "…",
      "country_code": "BY",
      "url": "https://tsouz.belgiss.by/#!/tsouz/certifs/<id>/view",
      "pdf_url": "http://127.0.0.1:8000/api/certificate-pdf?source=eaeu&registry_id=<id>",
      "valid_from": "2024-05-29",
      "valid_until": "2029-05-29",
      "status": "действует",
      "status_code": "01",
      "registry_id": "3345084",
      "official_number": "…",
      "error": null,
      "error_code": null,
      "cached": false,
      "trace": [
        "Поиск: «…»",
        "Нормализован: …, страна BY",
        "Провайдер: Беларусь, tech.eaeunion.org, при отсутствии — api.belgiss.by",
        "BY: tech.eaeunion.org — не найден, пробуем api.belgiss.by"
      ]
    }
  ]
}
```

### Поля `results[]`

- `query`: исходная строка элемента из запроса
- `normalized`: нормализованное представление номера (или `null` при ошибке парсинга)
- `country_code`: код страны (`BY`, `RU`, `KZ`, `AM`, `KG`) или `null`
- `url`: ссылка на карточку реестра (или `null`)
- `pdf_url`: ссылка на PDF сертификата из реестра (или `null`). Для ЕАЭС и FSA — proxy `GET /api/certificate-pdf`; для KG (SWIS) — прямая ссылка на `/Doc/{uuid}`
- `valid_from`: дата начала действия в ISO-формате `YYYY-MM-DD` или `null`
- `valid_until`: дата окончания действия в ISO-формате `YYYY-MM-DD` или `null`
- `status`: человекочитаемый статус (например, `действует`) или `null`
- `status_code`: код статуса реестра или `null`
- `registry_id`: идентификатор записи реестра или `null`
- `official_number`: номер в реестре или `null`
- `error`: текст ошибки или `null`
- `error_code`: код ошибки или `null`
- `cached`: `true`, если результат получен из SQLite-кэша (`CACHE_PATH`)
- `trace`: шаги поиска (разбор номера, провайдер/цепочка, HTTP, fallback между источниками). Те же строки пишутся в консоль.

При `LOOKUP_EAEU_FIRST=false` строка «Провайдер» меняет порядок: «Беларусь, api.belgiss.by, при отсутствии — tech.eaeunion.org».

## error_code

В `error_code` возвращаются следующие значения:

- `invalid_number` — не удалось распарсить формат номера
- `unsupported_country` — страна распознана, но соответствующий реестр не подключён (сейчас поддержаны `BY`, `RU`, `KZ`, `KG`, `AM`)
- `not_found` — в реестре не найдено соответствие
- `source_unavailable` — внешний источник (OData ЕАЭС или национальный реестр) недоступен или вернул ошибку; при цепочке fallback срабатывает только если оба источника недоступны или последний шаг цепочки упал
- `ambiguous` — найдены несколько кандидатов; требуется указать номер целиком

Примечание про кэш:

- Успешные lookup-и кэшируются.
- Ошибки `not_found` кэшируются.
- `unsupported_country` в кэш не сохраняется; устаревшие записи из кэша игнорируются.
- Ошибки `invalid_number`, `ambiguous`, `source_unavailable` в кэше не сохраняются.
- Запись кэша без ключа `valid_from` считается устаревшей и запрашивается заново.

## `POST /api/extract-xlsx`

Извлекает строки из столбца A без обращения к реестрам (номера или наименования продукции).

`multipart/form-data`, поле `file`. Первый лист, столбец A. Пустые ячейки пропускаются. Первая строка отбрасывается, если похожа на заголовок (`номер`, `number`, `сертификат`, `наименован`, `товар`, `продукц`, `product`).

Успех:

```json
{
  "numbers": ["ЕАЭС BY/112 02.01. ТР018 010.02 00276"],
  "error": null,
  "error_code": null
}
```

Если столбец A пустой — `200` с `error_code=no_numbers_in_xlsx`. Повреждённый или пустой файл — `400` (`invalid_xlsx`).

Дальше клиент вызывает `POST /api/lookup` (номера) или `POST /api/search-product` (наименования). Поиск по продукции — [search-product.md](search-product.md).

UI использует потоковые варианты, чтобы шаги появлялись сразу, а не пачкой в конце:

- `POST /api/extract-pdf/stream` — NDJSON: `{ "type": "step", "text": "…" }` и финальный `{ "type": "done", "numbers": [...] }`
- `POST /api/lookup/stream` — один номер, те же события `step`/`done` с `{ "type": "done", "result": { … } }`

Синхронные PDF-endpoint'ы (`/api/extract-pdf`, `/api/lookup-pdf`) дополнительно возвращают `extract_trace` — шаги извлечения номера из PDF (аналог `trace` для lookup).

## `POST /api/reload`

Перезапускает рантайм без остановки процесса uvicorn: закрывает HTTP-клиенты, перечитывает `.env`, заново создаёт провайдеры и сбрасывает OCR. SQLite-кэш поиска не очищается (для этого есть `POST /api/cache/clear`).

Ответ:

```json
{
  "generation": 2,
  "message": "Сервис перезапущен: HTTP-сессии, провайдеры и OCR сброшены"
}
```

`GET /health` возвращает поле `generation` и статус ping каждого провайдера из `bootstrap.py` (отдельные национальные, OData по стране и составные цепочки):

```json
{
  "status": "ok | degraded",
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

Составные ключи (`belarus`, `russia`, …) — `ChainedRegistryProvider`: `ok`, если доступен хотя бы один шаг цепочки.

## Пример запроса (curl)

```bash
curl -X POST http://127.0.0.1:8000/api/lookup ^
  -H "Content-Type: application/json" ^
  -d "{\"numbers\":[\"ЕАЭС BY/112 02.01. ТР018 010.02 00276\"]}"
```

## Настройки, влияющие на поведение

См. `src/cert_parser/config.py`, основные параметры:

- `LOOKUP_EAEU_FIRST`: порядок цепочки для BY/RU/KZ/KG (`true` — сначала OData ЕАЭС, по умолчанию)
- `MAX_BATCH_SIZE`: ограничение размера массива `numbers`
- `LOOKUP_CONCURRENCY`: ограничение параллельности внутри батча
- `LOOKUP_DELAY_SECONDS`: задержка после успешного lookup
- `CACHE_PATH`, `CACHE_TTL_SECONDS`: SQLite-кэш
- `HTTP_SSL_VERIFY` (alias `BELGISS_SSL_VERIFY`): TLS-проверка для исходящих запросов к реестрам

