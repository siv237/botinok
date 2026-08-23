---
type: concept
tags: [learn]
updated: 2026-08-23
sources: 2
status: stable
---

# Обучение на опыте (Experience)

Локальная база данных «позитивного» и «негативного» опыта. Агент учится на своих ошибках и успехах. → `entities/tools/experience.md`

## Как работает
- `experience add_positive` / `add_negative` — запись опыта с заголовком и тегами.
- `experience search` / `list` / `check` — поиск по базе.
- База хранится в `~/.botinok/experience`; индексируется для быстрого поиска.

## Связь с вики-методикой
Концептуально схож с LLM Wiki: информация не переоткрывается каждый раз, а **накапливается** в персистентном артефакте. Результаты поиска опыта возвращаются модели для учёта прошлых ошибок.

## Связи
Механизм — `entities/tools/experience.md`. Система навыков — `concepts/skills_system.md`.
