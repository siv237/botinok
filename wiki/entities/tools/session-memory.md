---
type: entity
tags: [tool, session]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент session_memory

`tools/session_memory.py` → функция `session_memory_tool(...)`. **Объектный доступ к истории сессии.** Используется вместо чтения `context.json` через `file_system`. → `entities/session_directory.md`

## Действия
- `summary` — сводка сессии.
- `turns` — список обменов; `get_turn` — конкретный turn.
- `search` — поиск по содержимому (использует `SessionIndex`).
- `filter` — фильтрация по `since`/`until`/`role`/`has_tool_calls`.
- `timeline` — хронология; `stats` — статистика; `chain` — цепочка turns.

## Внутренняя модель
- `ToolCall` · `MessagePart` · `Turn` · `SessionParser` (разбор `context.json`) · `SessionIndex`.
- Вывод: structured (`_format_structured`) или markdown (`_format_as_markdown`).

## Связи
Зарегистрирован как `session_memory`. Заменяет прямое чтение `context.json` (рекомендация из описания инструмента). → `concepts/session_lifecycle.md`
