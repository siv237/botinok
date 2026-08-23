---
type: entity
tags: [tool, dev, integration]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент github

`tools/github.py` → функция `github(...)`. Работа с GitHub API.

## Параметры
- `action` (обязательно): `search_repos` · `get_repo` · `get_readme` · `get_file` · `get_tags` · `get_branches`.
- `query`, `repo`.

## Особенности
- `_github_request(url)` — HTTP-обёртка над GitHub API.
- Полезен для поиска репозиториев, чтения README/файлов, проверки тегов/веток (интеграция с автообновлением).

## Связи
Зарегистрирован как `github`. Связан с `--update` (проверка версий) → `concepts/self_update.md`, и системой skills (ClawHub) → `concepts/skills_system.md`.
