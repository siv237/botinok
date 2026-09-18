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
- **Логирование**: `log_chunk` (построчный лог с дельтой; инкрементная запись `thinking.md`/`response.md`), `log_tool_call` (`tools.log`, с `call_id`), `log_step` (`steps/*.json` + `performance.log`, уникальные имена без затирания), метаданные-заголовки/футеры.
- **Контекст**: `update_context(role, content, thinking, tool_calls, tool_call_id, name, extra)` — запись в `context.json`; дедупликация подряд идущих одинаковых записей. Запись **атомарная** (`_atomic_write_json`: tmp+fsync+`os.replace`, бэкап прошлой версии в `.bak`), поэтому обрыв/убийство процесса не портит файл.
- **Защита от повреждения**: `_read_json_with_backup` (context → `.bak`), `load_history_entries` (context → `.bak` → `messages.json`); при повреждении обоих `update_context` **засевает историю из снапшота** и откладывает битый файл в `context.json.corrupt-<ts>`.
- **Канонический снапшот**: `save_messages_snapshot()` → `messages.json` (точный массив сообщений, медиа выносится в `artifacts` по хэшу), `load_messages_snapshot()`, `restore_session()` (EXACT/DERIVED), `load_context_messages()`, `reconstruct_messages()` (обратная совместимость старых сессий), `audit_context()`.
- **Ollama**: `get_ollama_status()` (`/api/ps`), `unload_models()` (keep_alive=0).
- **Артефакты**: `save_artifact()`, `save_media()` — дампы/медиа в `artifacts/`.
- **Возобновление**: `load_last_assistant_answer()` (последний **финальный** ответ, очищенный от YAML), `load_first_user_prompt()`, `build_resume_brief()`, `strip_skills_mandate()`.
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
