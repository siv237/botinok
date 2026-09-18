---
type: entity
tags: [tool, network]
updated: 2026-09-18
sources: 3
status: legacy
---

# Инструмент web_search (legacy-обёртка)

`tools/web_search.py` → функция `ddg_search(query, session_path=None)`.
**Legacy-алиас** единого веб-кита `entities/tools/web.md`: делегирует в
`web action=search` (DuckDuckGo HTML через httpx, fallback — lynx).

## Связи
Зарегистрирован как `web_search`. Предпочтительный инструмент — `web action=search`.
→ `entities/tools/web.md`
