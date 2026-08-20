# API: поиск по наименованию продукции

**Дата:** 2026-08-20

Поиск документов соответствия по фрагменту формулировки продукции из реестра (не по артикулу магазина). Поиск по регистрационному номеру не менялся — см. [lookup.md](lookup.md).

Остальные endpoint'ы — [endpoints.md](endpoints.md).

## `POST /api/search-product`

Батч-поиск. Content-Type: `application/json`.

```json
{
  "queries": ["шины легковые"],
  "limit_per_query": 25
}
```

Правила:

- `queries` — массив строк; пустые/пробельные отфильтровываются.
- Если после фильтрации список пуст — `400` (`«Передайте хотя бы один запрос»`).
- Размер батча — не больше `MAX_BATCH_SIZE` (дефолт `100`).
- `limit_per_query` — сколько хитов оставить после объединения источников (дефолт `25`, диапазон 1…50).

Ответ всегда `200` при валидном теле:

```json
{
  "results": [
    {
      "query": "шины легковые",
      "official_number": "…",
      "country_code": "RU",
      "doc_kind": "certificate",
      "product_name": "…",
      "url": "…",
      "pdf_url": "…",
      "valid_from": "2024-05-29",
      "valid_until": "2029-05-29",
      "status": "действует",
      "status_code": "01",
      "registry_id": "…",
      "source": "fsa_cert",
      "error": null,
      "error_code": null,
      "trace": ["Поиск по продукции: «шины легковые»", "…"]
    }
  ]
}
```

`results` — плоский список хитов по всем запросам батча (не один объект на строку запроса). Если по запросу ничего нет или все источники недоступны, в список попадает одна запись-ошибка с тем же `query`.

На уровне сервиса запросы батча идут параллельно (семафор `LOOKUP_CONCURRENCY`). UI вызывает поток **по одной строке подряд**.

## `POST /api/search-product/stream`

Потоковый поиск **одного** наименования. Content-Type ответа: `application/x-ndjson`.

В `queries` допускается ровно один непустой элемент, иначе `400` (`«Поток поддерживает один запрос»`).

События NDJSON:

- `{ "type": "step", "text": "…" }` — шаг (те же строки, что в `trace`)
- `{ "type": "done", "results": [ … ] }` — массив хитов

В отличие от `/api/lookup/stream`, финал — поле **`results`** (массив), а не `result` (один объект).

UI использует этот endpoint для каждой строки из буфера/Excel.

## Поля хита

Общие с lookup: `query`, `official_number`, `country_code`, `url`, `pdf_url`, `valid_from`, `valid_until`, `status`, `status_code`, `registry_id`, `error`, `error_code`, `trace`.

Дополнительно:

| Поле | Значения |
|------|----------|
| `product_name` | формулировка продукции из реестра или `null` |
| `doc_kind` | `certificate` или `declaration` (или `null` на ошибке) |
| `source` | `fsa_cert`, `fsa_decl`, `eaeu_ru`, `eaeu_other` |

Нет полей `normalized` и `cached`: SQLite-кэш lookup к поиску по продукции не применяется.

## Источники

На один запрос четыре провайдера вызываются параллельно (`asyncio.gather`), с каждого не больше 10 записей (`PER_SOURCE_CAP`):

| `source` | Реестр |
|----------|--------|
| `fsa_cert` | Росаккредитация, сертификаты (`pub.fsa.gov.ru`) |
| `fsa_decl` | Росаккредитация, декларации |
| `eaeu_ru` | OData [tech.eaeunion.org](https://tech.eaeunion.org), страна `RU` |
| `eaeu_other` | OData ЕАЭС, страна не `RU` |

Дубликаты снимаются по компактному `official_number`. Ранжирование: сначала `country_code=RU`, затем вхождение нормализованной фразы в `product_name`, затем число совпавших токенов, затем действующий статус. Срез — `limit_per_query`.

Нормализация запроса: минимум 4 символа после сжатия пробелов; иначе `query_too_short`. Ищется фрагмент формулировки из документа.

## error_code

| Код | Когда |
|-----|--------|
| `query_too_short` | строка короче минимума после нормализации |
| `not_found` | источники ответили, совпадений нет |
| `source_unavailable` | все четыре источника недоступны или упали |

Коды пишутся в элемент `results[]` (HTTP 200), как у lookup.

## Excel

Извлечение строк из столбца A — тот же `POST /api/extract-xlsx`, что и для номеров. Первая строка отбрасывается, если похожа на заголовок (`номер`, `number`, `сертификат`, `наименован`, `товар`, `продукц`, `product`). Дальше клиент вызывает `/api/search-product` или `/api/search-product/stream`.

`POST /api/export-xlsx`: если в строках есть `product_name` или `doc_kind`, в файл добавляются колонки **Продукция** и **Вид** (`Сертификат` / `Декларация`). Колонка **Запрос** есть всегда.

## Пример (curl)

```bash
curl -X POST http://127.0.0.1:8000/api/search-product ^
  -H "Content-Type: application/json" ^
  -d "{\"queries\":[\"шины легковые\"],\"limit_per_query\":25}"
```

Код: `src/cert_parser/application/product_search_service.py`, `src/cert_parser/api/app.py`.
