# Changelog

## [Unreleased]

### Added

- Автоверсионирование из git-тегов (`setuptools-scm`) и скрипт `scripts/release.py patch|minor|major`
- Версионность: поле `version` в `GET /health` и `POST /api/reload`
- UI: бейдж версии в шапке (`v0.2.0 · gen N`), cache-bust статики (`?v=…`), подсветка при рассинхроне с сервером
- UI: три источника ввода — «Из буфера», «Из Excel», «Из PDF» (drag-and-drop, выбор папки для PDF)
- UI: пагинация результатов, экспорт в Excel, меню настроек (сброс кэша, полная перезагрузка сервиса)
- API: `POST /api/extract-pdf`, `POST /api/extract-pdf/stream`
- API: `POST /api/extract-xlsx`, `POST /api/export-xlsx`
- API: `POST /api/lookup/stream` (NDJSON, один номер)
- API: `POST /api/cache/clear`, `POST /api/reload`
- Поддержка стран: BY, RU, KZ, KG, AM
- Поле `extract_trace` в ответах PDF-endpoint'ов
- Поле `generation` в `GET /health`

### Changed

- PDF: разделены extract (`/api/extract-pdf`) и extract+lookup (`/api/lookup-pdf`); UI использует потоковый extract
- Excel: извлечение номеров отделено от lookup (`/api/extract-xlsx` → `/api/lookup`)

## [0.2.0]

- FastAPI-приложение с веб-UI и батч-lookup по национальным реестрам ЕАЭС
- SQLite-кэш, trace-логирование шагов поиска
