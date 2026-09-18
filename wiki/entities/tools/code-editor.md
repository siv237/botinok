---
type: entity
tags: [tool, safety, dev]
updated: 2026-09-18
sources: 3
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
- `read` — всегда; запись (`write`/`replace`/`apply`) внутри `session_path` —
  без dangerous mode; **вне сессии** — требуется dangerous mode (TUI запрашивает
  переключение). → `concepts/dangerous_mode.md`
- Путь резолвится `_safe_path` (ограничение корнем); при `dangerous_mode=True`
  ограничение снимается, путь берётся как `realpath` (аргумент `dangerous_mode`
  прокидывается из `ToolManager`).

## Связи
Зарегистрирован как `code_editor`. Отображаемые аргументы экранируются (`_code_editor_args_for_display`). → `entities/tool_manager.md`, `entities/botinok_cli.md`
