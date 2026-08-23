---
type: entity
tags: [tool, network]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент web_extract

`tools/web_extract.py` → функция `web_extract(url, extract, ...)`. Извлечение структурированных ресурсов со страницы: ссылки, изображения, заголовки, мета-теги, таблицы. Использует **httpx + selectolax** (быстрый C-парсер). Алиас — `web_extractor` для совместимости.

## Параметры
- `extract` — что извлекать (enum): `links`, `images`, `headings`, `meta`, `tables`, `all`.
- `max_items`, `timeout_sec`, `headers` (формат `Key: Value`).
- `url` — обязателен.

## Связи
Зарегистрирован как `web_extract` (и алиас `web_extractor`). → `entities/tools/open-url.md`
