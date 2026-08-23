---
type: entity
tags: [tool, learn]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент experience

`tools/experience.py` → функция `experience(...)`. Локальная база «позитивного» и «негативного» опыта: агент **учится на своих ошибках**. → `concepts/experience_learning.md`

## Параметры
- `action` (обязательно): `add_positive` · `add_negative` · `search` · `list` · `check`.

## Особенности
- `_experience_dir()` — база в `~/.botinok/experience`.
- `_ensure_structure()`, `_format_entry()`, `_update_index()`.
- Записи с заголовком и тегами (`title`, `tags`); индексируются для поиска.

## Связи
Регистрируется как `experience`. Концепция обучения и хранения — `concepts/experience_learning.md`. Механизм индексации аналогичен каталогу вики.
