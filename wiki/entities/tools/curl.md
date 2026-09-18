---
type: entity
tags: [tool, network]
updated: 2026-09-18
sources: 3
status: stable
---

# Инструмент curl

`tools/curl.py` → функция `execute(...)`. HTTP GET-запросы и скачивание файлов. Алиас «curl» для совместимости при вызове.

## Параметры
- `url` (обязательно), `headers`, `timeout_sec`, `max_bytes`.
- `follow_redirects`, `jq_filter` (фильтр JSON, напр. `.userId | .items[]`).
- `output_path` — сохранение ответа в файл.

## Политика записи
- **Readonly по умолчанию**.
- `output_path` внутри папки сессии (`session_path`) — разрешено без dangerous mode.
- `output_path` вне сессии требует **dangerous mode**: в простом режиме
  `ToolManager.call_tool` возвращает ошибку, а TUI предлагает переключиться.
  → `concepts/dangerous_mode.md`, `entities/tool_manager.md`
- Поддерживает `progress_callback` (прогресс скачивания) — прокидывается из `ToolManager.call_tool`.

## Связи
Зарегистрирован как `curl`. Альтернатива `open_url`/`web_extract` для сырых бинарных/JSON-ответов и больших файлов.
