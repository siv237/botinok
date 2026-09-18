---
type: entity
tags: [tool, network]
updated: 2026-09-18
sources: 3
status: legacy
---

# Инструмент open_url (legacy-обёртка)

`tools/open_url.py` → функция `open_url(url, session_path=None)`. **Legacy-алиас**
единого веб-кита `entities/tools/web.md`: делегирует в `web action=open`
(читаемый основной текст страницы в markdown). Если схема опущена — добавляет
`https://`.

## Связи
Зарегистрирован как `open_url`. Предпочтительный инструмент — `web action=open`.
→ `entities/tools/web.md`
