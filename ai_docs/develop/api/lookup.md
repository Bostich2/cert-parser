# API: `POST /api/lookup`

Endpoint для поиска карточки сертификата по регистрационному номеру(ам).

Принимает батч номеров и возвращает массив `results` с результатом по каждому элементу.

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
        "Провайдер: Беларусь, api.belgiss.by"
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
- `valid_from`: дата начала действия в ISO-формате `YYYY-MM-DD` или `null`
- `valid_until`: дата окончания действия в ISO-формате `YYYY-MM-DD` или `null`
- `status`: человекочитаемый статус (например, `действует`) или `null`
- `status_code`: код статуса реестра или `null`
- `registry_id`: идентификатор записи реестра или `null`
- `official_number`: номер в реестре или `null`
- `error`: текст ошибки или `null`
- `error_code`: код ошибки или `null`
- `cached`: `true`, если результат получен из SQLite-кэша (`CACHE_PATH`)
- `trace`: шаги поиска (разбор номера, провайдер, HTTP, сколько строк). Те же строки пишутся в консоль.

## error_code

В `error_code` возвращаются следующие значения:

- `invalid_number` — не удалось распарсить формат номера
- `unsupported_country` — страна распознана, но соответствующий реестр не подключён (сейчас поддержаны `BY`, `RU`, `KZ`, `KG`, `AM`)
- `not_found` — в реестре не найдено соответствие
- `source_unavailable` — внешний источник (БелГИСС) недоступен или вернул ошибку
- `ambiguous` — найдены несколько кандидатов; требуется указать номер целиком

Примечание про кэш:

- Успешные lookup-и кэшируются.
- Ошибки `not_found` кэшируются.
- `unsupported_country` в кэш не сохраняется; устаревшие записи из кэша игнорируются.
- Ошибки `invalid_number`, `ambiguous`, `source_unavailable` в кэше не сохраняются.
- Запись кэша без ключа `valid_from` считается устаревшей и запрашивается заново.

## `POST /api/extract-xlsx`

Извлекает номера из Excel без обращения к реестрам.

`multipart/form-data`, поле `file`. Первый лист, столбец A. Пустые ячейки пропускаются. Первая строка отбрасывается, если похожа на заголовок (`номер`, `number`, `сертификат`).

Успех:

```json
{
  "numbers": ["ЕАЭС BY/112 02.01. ТР018 010.02 00276"],
  "error": null,
  "error_code": null
}
```

Если столбец A пустой — `200` с `error_code=no_numbers_in_xlsx`. Повреждённый или пустой файл — `400` (`invalid_xlsx`).

Дальше клиент вызывает `POST /api/lookup` с полученным списком.

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

`GET /health` возвращает то же поле `generation`:

```json
{
  "status": "ok | degraded",
  "generation": 1,
  "belgiss": "ok | unavailable",
  "fsa": "ok | unavailable",
  "eokno": "ok | unavailable",
  "swis": "ok | unavailable",
  "eaeu": "ok | unavailable"
}
```

## Пример запроса (curl)

```bash
curl -X POST http://127.0.0.1:8000/api/lookup ^
  -H "Content-Type: application/json" ^
  -d "{\"numbers\":[\"ЕАЭС BY/112 02.01. ТР018 010.02 00276\"]}"
```

## Настройки, влияющие на поведение

См. `src/cert_parser/config.py`, основные параметры:

- `MAX_BATCH_SIZE`: ограничение размера массива `numbers`
- `LOOKUP_CONCURRENCY`: ограничение параллельности внутри батча
- `LOOKUP_DELAY_SECONDS`: задержка после успешного lookup
- `CACHE_PATH`, `CACHE_TTL_SECONDS`: SQLite-кэш
- `BELGISS_SSL_VERIFY`: управление TLS-проверкой для БелГИСС

