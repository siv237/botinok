---
type: concept
tags: [config, integration]
updated: 2026-09-21
sources: 3
status: stable
---

# Автообновление (Self-update)

Ботинок умеет обновлять сам себя из git-репозитория. → `entities/botinok_cli.md`

## Механика
- `botinok --update` → `_check_remote_version()` сравнивает локальную и удалённую версии; при наличии новой показывает сравнение и запрашивает подтверждение перед установкой → `_perform_update()`.
- **Системные компоненты ставятся всегда** (`_ensure_system_deps`) — независимо от того, есть ли новый коммит. Раньше установка зависимостей (`_ensure_chafa`) вызывалась только внутри `_perform_update`, поэтому на актуальной версии обновление не доустанавливало `chafa` (картинки в чате не рисовались) и не сообщало об этом: `chafa` не был в `_SYSTEM_TOOLS`. Теперь в списке (`_SYSTEM_TOOLS`) — `curl/lynx/jq/aria2c/file/git/chafa/ffmpeg`, а `_ensure_system_deps` доустанавливает весь набор через пакетный менеджер (root — напрямую, иначе `sudo -n`), с `apt-get update` и отчётом.
- `botinok --ensure-deps` — только проверка/установка системных компонентов (без обновления кода).
- `botinok --update-packages` / `-U` (launcher `botinok`) — pip-зависимости **и затем** `--ensure-deps`.
- `update.sh` в корне репозитория — единая команда обновления под root: `git pull` (с `safe.directory`) → pip → `--ensure-deps`.
- `--version` / `_get_version_info()` — текущая версия (напр. `0.4 | дата | хеш`).
- `install.sh` ставит системные пакеты, включая `chafa` и `ffmpeg`.

## Диагностика (почему chafa не ставился)
Сессия `20260824_164041_visual_run`: фото качались, но не отображались. Причина — нет `chafa` (`render_image_band` → `chafa_path()` → `None`), а `--update` на актуальном коммите делал ранний `return` до `_perform_update`; вдобавок `chafa` не входил в предупреждение о зависимостях. См. выше исправления и тест `tests/test_system_deps.py`.

## Связи
Связан с git GitHub-интеграцией (инструмент `github`). → `entities/tools/github.md`, `sources/git_history.md`
