---
type: source
tags: [llm, config]
updated: 2026-08-23
sources: 2
status: stable
---

# Системные промпты (prompts/README.md)

Системные сообщения вынесены в `prompts/*.txt`; при создании сессии копируются в `session/prompts/` (можно редактировать под задачу; fallback на глобальные). Поддержка переменных `{{VAR_NAME}}`. → `entities/session_manager.md`, `entities/session_directory.md`

## Ключевые промпты
- **identity.txt** — основной системный промпт (личность/правила).
- **Контекст/переполнение**: `context_overflow_summary.txt`, `context_overflow_user.txt`, `context_overflow_protocol.txt`. → `concepts/context_management.md`
- **Авто-продолжение**: `auto_continue.txt`, `auto_continue_final.txt`.
- **Режимы**: `chat_only.txt` (модели без tools), `proofreader.txt`, `dangerous_mode.txt`, `broken_tools.txt`, `context_trimmed.txt`.
- **Сессия**: `resume_context.txt`, `session_files.txt`, `session_location.txt`, `system_time.txt`.
- **Политика**: `tool_policy.txt`, `tool_reminder.txt`.

## Как добавить промпт
1. Файл `.txt` в `prompts/`; 2. переменные `{{VAR}}`; 3. загрузка через `sm.load_prompt(session_path, name, **vars)`; 4. описание в `prompts/README.md`.

## Производные страницы
`concepts/context_management.md` · `concepts/proofreader.md` · `entities/ollama_backend.md`
