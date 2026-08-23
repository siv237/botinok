---
type: entity
tags: [tool, network]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент open_url

`tools/open_url.py` → функция `open_url(url, session_path=None)`. Извлечение текстового содержимого страницы через `lynx -dump`.

## Особенности
- Быстрый способ прочитать «читабельный» текст страницы без HTML-мусора.
- Настройки lynx в `[Tools]` конфига.
- `session_path` прокидывается опционально.

## Связи
Зарегистрирован как `open_url`. Компаньон `web_search` и `curl`. → `entities/tools/web-search.md`, `entities/tools/curl.md`

## Различие с web_extract
`open_url` даёт сплошной текст; `web_extract` — структурированные данные (ссылки, изображения, таблицы). При глубоком разборе предпочтителен `web_extract`. → `entities/tools/web-extract.md`
