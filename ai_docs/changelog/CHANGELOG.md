# Changelog

## [Unreleased]

### Added

- Единая цепочка lookup для BY, RU, KZ, KG (`ChainedRegistryProvider`, `build_lookup_chain` в `chained.py`)
- Стратегия EAEU-first: по умолчанию сначала OData [tech.eaeunion.org](https://tech.eaeunion.org), затем национальный реестр; переключается через `LOOKUP_EAEU_FIRST`
- Fallback на OData ЕАЭС для России (RU) и Кыргызстана (KG) — по аналогии с BY/KZ
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

### Changed

- Bootstrap: BY/KZ/RU/KG собираются через `build_lookup_chain` вместо прямых провайдеров и обёрток
- Trace lookup: строка «Провайдер» отражает порядок цепочки (EAEU-first или national-first)
- UI: подсказки ожидания для BY, RU, KZ, KG показывают порядок источников (EAEU → национальный реестр)
- Production deploy: `Caddyfile` встроен в образ `caddy` (без bind mount) — совместимость с Coolify
- Production deploy: Caddy вынесен в профиль `standalone` (для Coolify поднимается только `web:8000`)
- PDF: разделены extract (`/api/extract-pdf`) и extract+lookup (`/api/lookup-pdf`); UI использует потоковый extract
- Excel: извлечение номеров отделено от lookup (`/api/extract-xlsx` → `/api/lookup`)

### Removed

- Обёртки `BelarusProvider` и `KazakhstanProvider` — логика цепочки перенесена в `ChainedRegistryProvider`

## [0.2.0]

- FastAPI-приложение с веб-UI и батч-lookup по национальным реестрам ЕАЭС
- SQLite-кэш, trace-логирование шагов поиска
