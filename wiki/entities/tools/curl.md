---
type: entity
tags: [tool, network]
updated: 2026-09-18
sources: 3
status: legacy
---

# Инструмент curl (legacy-обёртка)

`tools/curl.py` → функция `execute(...)`. **Legacy-алиас** единого веб-кита
`entities/tools/web.md`; нового кода с ним писать не нужно.

## Делегирование
| Аргументы curl | Действие web |
|---|---|
| `jq_filter=…` | `action=json` (проекция JSON через jq) |
| `output_path=…` | `action=download` (сохранить в файл) |
| иначе | `action=auto` (стратегия по content-type) |

## Историческая справка
- `jq_filter` был добавлен в `c79ad2f` (29.03.2026) и **вырезан** из реализации
  в `307dcf8` (29.03.2026, «рефактор curl для скачивания файлов»), но остался в
  JSON-схеме `ToolManager`. Из-за этого модель получала `TypeError`.
- При консолидации `jq_filter` восстановлен — теперь через `web action=json`.

## Политика записи
`output_path` внутри папки сессии — можно; вне — dangerous mode.
→ `concepts/dangerous_mode.md`, `entities/tool_manager.md`

## Связи
Зарегистрирован как `curl`. Альтернатива — `open_url`/`web_extract` (тоже
legacy). Предпочтительный инструмент — `web`.
