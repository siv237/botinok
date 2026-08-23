---
type: entity
tags: [tool, learn, integration]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент skills

`tools/skills.py` → функция `skills(...)`. Мощная система расширения функционала — менеджер AI-навыков. → `concepts/skills_system.md`

## Действия
- `list` · `get` · `add` · `remove` · `run` — управление навыками.
- `search` · `clawhub` · `install-clawhub` — поиск и установка из базы **ClawHub**.

## Источники навыков
- **Personal**: `~/.botinok/skills/` — приватные навыки пользователя.
- **Project**: `./skills/` — общие навыки проекта (напр. `skills/excel/SKILL.md`).

## Особенности
- Каждый навык — папка с `SKILL.md` (описание) и реализацией на Python, подключаемой через `tools/skills.py`.
- `_ensure_dirs`, `find_skill`, `get_skill_description`, `get_raw_url`/`fetch_file` (работа с raw GitHub), ClawHub API (`clawhub_search`, `clawhub_explore`, `clawhub_install`).
- Командные функции `cmd_*` под каждое действие, включая `cmd_run`.

## Связи
Зарегистрирован как `skills`. Концепция — `concepts/skills_system.md`. Пример навыка: `skills/excel/SKILL.md`.
