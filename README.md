# Парсер сертификатов ЕАЭС

Веб-сервис ищет сертификат соответствия по регистрационному номеру в национальном реестре и возвращает ссылку на карточку и срок действия.

Поддерживаются:

- **Беларусь (BY)** — [БелГИСС](https://tsouz.belgiss.by/#!/tsouz/certifs)
- **Россия (RU)** — [Росаккредитация](https://pub.fsa.gov.ru/rss/certificate)
- **Казахстан (KZ)** — [eokno.gov.kz](https://eokno.gov.kz/public-register/register-ktrm.xhtml)
- **Кыргызстан (KG)** — [swis.trade.kg](https://swis.trade.kg/Registry/CertificateOfConformity)
- **Армения (AM)** — [armnab.am](https://armnab.am/ru/eaeu/certificates) (поиск через OData [tech.eaeunion.org](https://tech.eaeunion.org/tech/registers/35-1/ru/registryList/conformityDocs))

Примеры номеров:

```
ЕАЭС BY/112 02.01. ТР018 010.02 00276
ЕАЭС RU С-CN.СБ21.А.00039/19
ЕАЭС KZ 1100317.05.01.05103
ЕАЭС KG417/016.ru.02.04561
ЕАЭС AM-008/S.A-0175-2018
```

Страна берётся из кода в номере. Номер можно извлечь из PDF (текстовый слой, при необходимости OCR) или из Excel (столбец A).

## Быстрый старт

Нужен Python **3.12+**.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
set PYTHONPATH=src
uvicorn sert_parser.api.app:app --reload --host 127.0.0.1 --port 8000
```

Для сканов PDF нужен OCR: пакеты `rapidocr` и `onnxruntime` уже в `requirements.txt`. Распознавание сначала идёт кириллицей (`eslav`), если номер не собрался — латиницей.

Откройте `http://127.0.0.1:8000`.

На Linux/macOS: `source .venv/bin/activate`, `cp .env.example .env`.

## Docker

```bash
docker compose up --build
```

Сервис: `http://localhost:8000`.

Версия в образ подставляется из git-тега: `APP_VERSION=$(git describe --tags --abbrev=0 | tr -d v) docker compose up --build` (на Windows — задайте `APP_VERSION` вручную или через `$env:APP_VERSION`).

## Версии и релизы

Версия берётся **из git-тегов** (`v0.2.0`, `v0.2.1`, …) через [setuptools-scm](https://github.com/pypa/setuptools-scm). Ручное редактирование `version.py` не нужно.

```bash
# следующий patch-релиз (v0.2.0 → v0.2.1)
python scripts/release.py patch --push

# minor / major
python scripts/release.py minor --dry-run
```

После тега обновите `ai_docs/changelog/CHANGELOG.md` и запушьте коммиты (если `--push` не использовали).

**Первый релиз** (если тегов ещё нет): `git tag -a v0.2.0 -m "sert-parser v0.2.0"` и `git push origin v0.2.0`.

Приоритет источников версии:

1. `SERT_PARSER_VERSION` — явная переопределение (Docker, CI)
2. git-тег + setuptools-scm (локально и в editable install)
3. метаданные пакета после `pip install .`

Коммиты после тега получают dev-версию вида `0.2.1.dev3+gabc1234`.

## Как пользоваться (UI)

Три источника ввода:

- **Из буфера** — один или несколько номеров (по строке), вставка из буфера обмена.
- **Из Excel** — `.xlsx`/`.xlsm`, столбец A первого листа.
- **Из PDF** — файлы или папка (выбор, drag-and-drop); OCR при необходимости.

Таблица результатов: ссылка, срок действия, статус, ошибка. Есть пагинация и **экспорт в Excel**.

Блок «Ход поиска» показывает шаги (разбор номера, GET/POST, сколько строк). Те же строки пишутся в консоль uvicorn.

Для Казахстана eokno.gov.kz отвечает медленно (JSF). Пока идёт запрос, кнопки неактивны.

В шапке — меню настроек: сброс кэша и полная перезагрузка сервиса (без перезапуска uvicorn).

## API

| Метод | Путь | Назначение |
|-------|------|------------|
| `POST` | `/api/lookup` | Батч-поиск по номерам |
| `POST` | `/api/lookup/stream` | Потоковый поиск одного номера (NDJSON) |
| `POST` | `/api/extract-pdf` | Извлечь номера из PDF |
| `POST` | `/api/extract-pdf/stream` | То же, потоково (NDJSON) |
| `POST` | `/api/lookup-pdf` | PDF → извлечение + поиск |
| `POST` | `/api/extract-xlsx` | Извлечь номера из Excel |
| `POST` | `/api/export-xlsx` | Скачать результаты как `.xlsx` |
| `POST` | `/api/cache/clear` | Очистить SQLite-кэш |
| `POST` | `/api/reload` | Перезагрузить HTTP-сессии и провайдеры |
| `GET` | `/health/live` | Liveness (публичный): `status`, `version`, `generation` |
| `GET` | `/health` | Детальный статус провайдеров (admin при включённой auth) |
| `GET/POST` | `/login` | Страница входа (публичная при включённой auth) |
| `POST` | `/logout` | Выход из сессии |

Подробнее: [ai_docs/develop/api/endpoints.md](ai_docs/develop/api/endpoints.md).

### Пример: батч lookup

```json
POST /api/lookup
{ "numbers": ["ЕАЭС BY/112 02.01. ТР018 010.02 00276"] }
```

Ответ: `{ "results": [ … ] }`. Ошибки по одному номеру не роняют весь запрос.

### Пример: health

```json
{
  "status": "ok | degraded",
  "version": "0.2.0",
  "generation": 1,
  "belgiss": "ok | unavailable",
  "fsa": "ok | unavailable",
  "eokno": "ok | unavailable",
  "swis": "ok | unavailable",
  "eaeu": "ok | unavailable"
}
```

Коды ошибок lookup: `invalid_number`, `unsupported_country`, `not_found`, `source_unavailable`, `ambiguous`. Для PDF/Excel: `no_numbers_in_pdf`, `invalid_pdf`, `no_numbers_in_xlsx`, `invalid_xlsx`.

## Переменные окружения

См. `.env.example`. Важно:

- `FSA_BASE_URL` — реестр РФ. С не-российского IP часто 403; задайте `HTTPS_PROXY`.
- `EOKNO_REGISTER_URL`, `SWIS_BASE_URL` — реестры KZ и KG.
- `EAEU_ODATA_URL`, `EAEU_REGISTER_VIEW_URL` — единый реестр ЕАЭС для AM.
- `PDF_MAX_BYTES`, `PDF_OCR_MAX_PAGES`, `PDF_OCR_REC_LANG` — лимиты и язык OCR.
- `XLSX_MAX_BYTES` — максимальный размер загружаемого Excel (по умолчанию 15 МБ).
- `CACHE_PATH`, `CACHE_TTL_SECONDS`, `MAX_BATCH_SIZE`, `LOOKUP_CONCURRENCY`.
- `HTTP_SSL_VERIFY` — проверка TLS для всех исходящих HTTP-запросов к реестрам (`BELGISS_SSL_VERIFY` — устаревший alias).
- `LOG_LEVEL`.
- `SERT_PARSER_VERSION` — явная версия, если нет git-тега (Docker задаёт через `APP_VERSION`).
- `AUTH_ENABLED`, `AUTH_SECRET_KEY`, `AUTH_USERS` — session-авторизация (см. Production deploy).
- `ALLOWED_HOSTS`, `ENV=production` — hardening для публичного деплоя.

## Production deploy (VPS + Docker)

1. DNS A-запись домена → IP сервера.
2. Скопируйте [`deploy/.env.prod.example`](deploy/.env.prod.example) в `.env.prod` в корне проекта.
3. Укажите домен в [`deploy/Caddyfile`](deploy/Caddyfile) (`example.com` → ваш домен).
4. Сгенерируйте секрет: `python -c "import secrets; print(secrets.token_hex(32))"` → `AUTH_SECRET_KEY`.
5. Сгенерируйте пользователей:
   ```bash
   python scripts/hash_password.py 'your-password' --username admin --role admin
   ```
   Результат JSON вставьте в `AUTH_USERS`.
6. Запуск:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
7. Откройте `https://your.domain` — войдите под созданным пользователем.

Caddy получает TLS-сертификат Let's Encrypt автоматически. Приложение слушает только внутри Docker-сети (`web:8000`); снаружи доступен HTTPS через Caddy.

**Роли:** `admin` — сброс кэша и перезагрузка сервиса; `user` — поиск и экспорт.

Rate limiting включён в приложении (`RATE_LIMIT_*`). OpenAPI (`/docs`) отключён при `ENV=production`.

## Тесты

```bash
pip install -r requirements-dev.txt
set PYTHONPATH=src
pytest
```

## Документация

- [Usage Guide](ai_docs/develop/usage-guide.md)
- [API: lookup](ai_docs/develop/api/lookup.md)
- [API: все endpoint'ы](ai_docs/develop/api/endpoints.md)
- [Changelog](ai_docs/changelog/CHANGELOG.md)
