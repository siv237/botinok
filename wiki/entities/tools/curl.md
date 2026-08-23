---
type: entity
tags: [tool, network]
updated: 2026-08-23
sources: 2
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
- Запись файлов разрешена **только внутри папки сессии** (`session_path`).
- Запись вне сессии требует **dangerous mode**. → `concepts/dangerous_mode.md`
- Поддерживает `progress_callback` (прогресс скачивания) — прокидывается из `ToolManager.call_tool`. → `entities/tool_manager.md`

## Связи
Зарегистрирован как `curl`. Альтернатива `open_url`/`web_extract` для сырых бинарных/JSON-ответов и больших файлов.
