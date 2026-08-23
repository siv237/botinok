---
type: entity
tags: [tool, system]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент journal

`tools/journal.py` → функция `journal_tool(...)`. Read-only анализ systemd journal через `journalctl` (и аналог на macOS — `log show`).

## Параметры
- `action` (обязательно): `tail` · `unit_tail` · `since` · `query` · `stats`.

## Особенности
- `_run_journalctl` / `_run_log_show` — исполнение с лимитом вывода.
- `_build_base_args` / `_build_macos_args` — аргументы под ОС (Linux/macOS).
- `_filter_lines` — фильтрация по grep/regex; `_stats_levels` — статистика по уровням (`[0-7]`).
- Read-only: анализ логов без модификации системы.

## Связи
Зарегистрирован как `journal`. Полезен для системного администрирования и диагностики ошибок. → `entities/tools/file-system.md`
