---
type: entity
tags: [config]
updated: 2026-08-23
sources: 2
status: stable
---

# Система конфигов (config_system)

Конфигурация хранится в INI-файле (configparser). Путь и источник выбираются по приоритету, обрабатываются и редактируются через `SessionManager`. → `entities/session_manager.md`

## Приоритет конфигов
1. **Личный** — `~/.config/botinok/config.cfg`.
2. **Локальный** — `config.cfg` в текущей директории.
3. **Системный** — `BOTINOK_CONFIG` env или `/opt/botinok/config.cfg`.

Выбранный путь сохраняется в `config_path`, источник — в `config_source` («personal» / «local» / «system»).

## Секции (см. `sources/config_cfg.md`)
- `[Ollama]` — бэкенд (`Backend`: `ollama`/`openai`), baseurl, model, context, таймауты, сэмплинг, `ApiKey` (Bearer-токен для OpenAI-совместимых API).
- `[Storage]` — `SessionsDir`, `StepsSubDir`.
- `[Tools]` — lynx (useragent, лимиты, таймауты).
- `[UI]` — showvram, showtps.

## Работа
- `--wizard` (`core/config_wizard.py`, класс `ConfigWizard`) — интерактивный мастер: выбор бэкенда (Ollama / OpenAI-совместимый), проверка подключения, список моделей, контекст по умолчанию, `ApiKey`. → `concepts/config_priority.md`, `entities/openai_compat.md`
- `save_config()` — запись выбранного пути; обработка ошибок сохранения.
- Fallback-дефолты, если файл не найден.

## Связи
- Приоритет конфигов и wizard подробнее — `concepts/config_priority.md`.
- Резюме содержимого файла — `sources/config_cfg.md`.
