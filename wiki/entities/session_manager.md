---
type: entity
tags: [session, llm, config]
updated: 2026-08-23
sources: 2
status: stable
---

# SessionManager

`core/session_manager.py` — класс `SessionManager`. Центр управления сессиями, конфигурацией, логированием и системными промптами.

## Ответственности
- **Конфиги**: определение пути по приоритету (личный → локальный → системный) и чтение `config.cfg`. → `concepts/config_priority.md`, `entities/config_system.md`
- **Сессии**: создание директории сессии (`sessions/<timestamp>_<name>/`), гарантия подпапок (`steps`, `artifacts`, `project`, `proofreader`). → `entities/session_directory.md`, `concepts/session_lifecycle.md`
- **Промпты**: копирование `prompts/*.txt` в сессию при создании; загрузка промпта с подстановкой `{{VAR}}`. → `sources/prompts_readme.md`
- **Логирование**: `log_chunk` (построчный лог с дельтой; инкрементная запись `thinking.md`/`response.md`), `log_tool_call` (`tools.log`), `log_step` (`steps/*.json` + `performance.log`), метаданные-заголовки/футеры.
- **Контекст**: `update_context()` — добавление записи (role, content, thinking, tool_calls) в `context.json`.
- **Ollama**: `get_ollama_status()` (`/api/ps`), `unload_models()` (keep_alive=0).
- **Артефакты**: `save_artifact()` — дампы больших результатов инструментов в `artifacts/`.
- **Возобновление**: `load_last_assistant_answer()`, `load_first_user_prompt()`.
- **Корректор**: `load/save_proofreader_history()`.

## Ключевые методы
- `create_session(name="")` — создаёт структуру + копирует промпты + пишет стартовый `context.json`.
- `get_ollama_status(base_url)` — статус моделей; при бэкенде `openai` возвращает `None` (статус Ollama недоступен).
- `write_file_header/write_file_footer` — YAML-метаданные (`BOTINOK_SESSION_METADATA`) с метриками (tokens, tps, ttft, duration).

## Связи
- Используется в `botinok.py` и `textual_integration.py` как `sm`.
- Фабрика промптов: `load_prompt(session_path, name, **vars)`.

## Примечания
При ошибке создания `sessions`-директории выдаёт подсказку про `chown` (если папку создал root ранее). Разворачивает `~` и `$HOME` в пути.
