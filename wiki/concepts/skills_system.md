---
type: concept
tags: [learn]
updated: 2026-08-23
sources: 2
status: stable
---

# Система навыков (Skills)

Расширение функционала агента модульными «навыками». Реализация — `tools/skills.py`. → `entities/tools/skills.md`

## Модель навыка
- Папка-навык с файлом **`SKILL.md`** (описание способностей) и реализацией на **Python**, подключаемой через `tools/skills.py`.
- Пример: `skills/excel/SKILL.md` (проектный навык).

## Источники
- **Personal**: `~/.botinok/skills/` — приватные навыки пользователя.
- **Project**: `./skills/` — общие навыки проекта.

## Действия (actions)
`list` · `get` · `add` · `remove` · `run` · `search` · `clawhub` · `install-clawhub`.
`run` — исполнить навык с задачей (`task`).

## ClawHub (экосистема)
- `clawhub_search(query)`, `clawhub_explore()` — поиск/обзор базы навыков.
- `clawhub_install(slug)` — установка.
- Работа через raw GitHub-URL (`get_raw_url`, `fetch_file`).

## Связи
Инструмент-менеджер — `entities/tools/skills.md`. Обучение через опыт — `concepts/experience_learning.md`.
