---
type: entity
tags: [tool, safety, dev]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент code_editor

`tools/code_editor.py` → функция `code_editor(...)`. Редактирование файлов.

## Действия
- `read` — чтение с лимитами (SHA256 для проверки).
- `write` — полная запись содержимого.
- `replace` / `apply` — замена текстового фрагмента (`old_text` → `new_text`).
- Опции: `create`, `expected_sha256` (контроль перед записью).

## Безопасность
Требует **dangerous mode**. Пути резолвятся безопасно (`_safe_path`) относительно проекта/сессии; проверки выхода за пределы (`_resolve_code_editor_target_path` в `botinok.py`). → `concepts/dangerous_mode.md`

## Связи
Зарегистрирован как `code_editor`. Отображаемые аргументы экранируются (`_code_editor_args_for_display`). → `entities/tool_manager.md`, `entities/botinok_cli.md`
