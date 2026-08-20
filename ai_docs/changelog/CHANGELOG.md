# Changelog

## [Unreleased]

## [0.2.0]

### Fixed

- Поиск по товару: FSA ищет в колонке `productFullName` («Наименование продукции»), а не в `fullName`; у деклараций сортировка списка — `declDate`
- Поиск по товару: один OData-запрос вместо двух (RU / не-RU); таймаут шага не запускает такой же повтор; неудачный вход FSA не дублируется декларациями
- Автосчёт версии: git-хуки копируют `run-write-version.sh`, пишутся с LF и вызывают тот же Python, что ставил хуки; UI берёт живую версию из git, а не устаревший `_version.py`

### Added

- UI: вкладки «Поиск по сертификату» (буфер, Excel, PDF) и «Поиск по товару» (наименования из буфера и столбца A Excel)
- API: `POST /api/search-product` — батч-поиск по наименованию продукции (`queries`, `limit_per_query`)
- API: `POST /api/search-product/stream` — один запрос, NDJSON `step`/`done` с массивом `"results"` (не `"result"`, как у lookup)
- Поиск по товару: параллельно FSA сертификаты (`fsa_cert`), FSA декларации (`fsa_decl`) и один OData ЕАЭС (`eaeu_ru` / `eaeu_other` по стране записи); в выдаче сначала записи с `country_code=RU`
- Поля хита `product_name`, `doc_kind` (`certificate` \| `declaration`), `source`; коды `query_too_short`, `not_found`, `source_unavailable`
- Единая цепочка lookup для BY, RU, KZ, KG (`ChainedRegistryProvider`, `build_lookup_chain` в `chained.py`)
- Стратегия EAEU-first: по умолчанию сначала OData [tech.eaeunion.org](https://tech.eaeunion.org), затем национальный реестр; переключается через `LOOKUP_EAEU_FIRST`
- Fallback на OData ЕАЭС для России (RU) и Кыргызстана (KG) — по аналогии с BY/KZ
- GitHub Action `.github/workflows/release.yml`: push тега `v*.*.*` публикует GitHub Release; notes — из `CHANGELOG.md` (`scripts/release_notes.py`)
- Git hooks для автообновления `src/cert_parser/_version.py` (`scripts/install_git_hooks.py`, `scripts/write_version.py`)
- Session-авторизация (`AUTH_ENABLED`, логин/пароль, роли user/admin)
- Production deploy: `docker-compose.prod.yml`, Caddy reverse proxy, TLS
- API: `GET /health/live` (публичный liveness)
- Security: rate limiting (slowapi), security headers, TrustedHost, отключение OpenAPI в production
- Скрипт `scripts/hash_password.py` для генерации bcrypt-хешей
- Автоверсионирование из git-тегов (`setuptools-scm`) и скрипт `scripts/release.py patch|minor|major`
- Версионность: поле `version` в `GET /health` и `POST /api/reload`
- UI: бейдж версии в шапке (`v0.2.0 · gen N`), cache-bust статики (`?v=…`), подсветка при рассинхроне с сервером
- UI: три источника ввода — «Из буфера», «Из Excel», «Из PDF» (drag-and-drop, выбор папки для PDF)
- UI: пагинация результатов, экспорт в Excel, меню настроек (сброс кэша, полная перезагрузка сервиса)
- Поле `pdf_url` в результатах lookup (карточка — в `url`, PDF — отдельно)
- UI: колонка «PDF» со ссылкой на скачивание; экспорт Excel включает колонку «PDF»
- API: `POST /api/extract-pdf`, `POST /api/extract-pdf/stream`
- API: `GET /api/certificate-pdf` — скачать PDF сертификата из реестра (EAEU/FSA)
- API: `POST /api/extract-xlsx`, `POST /api/export-xlsx`
- API: `POST /api/lookup/stream` (NDJSON, один номер)
- API: `POST /api/cache/clear`, `POST /api/reload`
- Поддержка стран: BY, RU, KZ, KG, AM
- Поле `extract_trace` в ответах PDF-endpoint'ов
- Поле `generation` в `GET /health`
- FastAPI-приложение с веб-UI и батч-lookup по национальным реестрам ЕАЭС
- SQLite-кэш, trace-логирование шагов поиска

### Changed

- Поиск по товару: FSA сужает выдачу до статуса «действует» и `endDate` от сегодня; при таймауте широкого запроса повтор с `idTechReg` по словарю ключевых слов (шина → ТР ТС 018 и т.п.). Lookup по номеру без этих фильтров.
- UI: вкладка «Поиск по товару» помечена beta; подсказка, что реестр заточен под номер, а не под артикул магазина
- Excel: `POST /api/extract-xlsx` читает столбец A и для номеров, и для наименований (заголовок также `наименован` / `товар` / `продукц` / `product`)
- Поиск по товару: длинные SKU не сканируются целиком (`contains` по 1–2 словам); таймаут шага не валит весь источник; вход в FSA не держит общую сессию 30 с
- Excel-экспорт: при наличии `product_name`/`doc_kind` добавляются колонки «Продукция» и «Вид»; колонка «Запрос» всегда
- UI: в таблице результатов колонки «Запрос», «Продукция», «Вид»
- Bootstrap: BY/KZ/RU/KG собираются через `build_lookup_chain` вместо прямых провайдеров и обёрток
- Trace lookup: строка «Провайдер» отражает порядок цепочки (EAEU-first или national-first)
- UI: подсказки ожидания для BY, RU, KZ, KG показывают порядок источников (EAEU → национальный реестр)
- Production deploy: `Caddyfile` встроен в образ `caddy` (без bind mount) — совместимость с Coolify
- Production deploy: Caddy вынесен в профиль `standalone` (для Coolify поднимается только `web:8000`)
- PDF: разделены extract (`/api/extract-pdf`) и extract+lookup (`/api/lookup-pdf`); UI использует потоковый extract
- Excel: извлечение номеров отделено от lookup (`/api/extract-xlsx` → `/api/lookup`)

### Removed

- Обёртки `BelarusProvider` и `KazakhstanProvider` — логика цепочки перенесена в `ChainedRegistryProvider`
