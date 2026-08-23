---
type: concept
tags: [config, integration]
updated: 2026-08-23
sources: 2
status: stable
---

# Автообновление (Self-update)

Ботинок умеет обновлять сам себя из git-репозитория. → `entities/botinok_cli.md`

## Механика
- `botinok --update` → `_check_remote_version()` сравнивает локальную и удалённую версии; при наличии новой показывает сравнение и запрашивает подтверждение перед установкой → `_perform_update()`.
- `--version` / `_get_version_info()` — текущая версия (напр. `0.2 | дата | хеш`).
- Пакеты: `botinok --update-packages` / `-U` (более свежая версия в launcher `botinok`) — `pip install --upgrade pip setuptools wheel -r requirements.txt`.
- Улучшенное автообновление с поддержкой Python-зависимостей.

## Связи
Связан с git GitHub-интеграцией (инструмент `github`). → `entities/tools/github.md`, `sources/git_history.md`
