---
type: entity
tags: [tool, network]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент web_search

`tools/web_search.py` → функция `ddg_search(query, session_path=None)`. Поиск в интернете через **DuckDuckGo** (использует `lynx`). → `entities/ollama_backend.md`

## Особенности
- Принимает поисковый запрос; в `config.cfg` `[Tools]` настраиваются `lynxuseragent`, `lynxmaxchars`, таймауты.
- Отладочный вывод через `_debug`.
- `session_path` прокидывается (для записи артефактов при необходимости).

## Связи
Зарегистрирован как `web_search`. Типичная связка: серия `web_search` → `open_url`/`web_extract` для чтения найденного. → `entities/tools/open-url.md`, `entities/tools/web-extract.md`, `concepts/function_calling.md`
