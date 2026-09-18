---
type: entity
tags: [tool, network]
updated: 2026-09-18
sources: 3
status: legacy
---

# Инструмент web_extract (legacy-обёртка)

`tools/web_extract.py` → функция `web_extract(url, extract, ...)`. **Legacy-алиас**
единого веб-кита `entities/tools/web.md`: делегирует в `web action=extract`
(структура: ссылки, изображения, заголовки, мета-теги, таблицы + `css`-селекторы).
Алиас `web_extractor` сохранён.

## Связи
Зарегистрирован как `web_extract` (и `web_extractor`). Предпочтительный
инструмент — `web action=extract`. → `entities/tool_manager.md`
