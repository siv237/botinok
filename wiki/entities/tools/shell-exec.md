---
type: entity
tags: [tool, safety]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент shell_exec

`tools/shell_exec.py` → функция `shell_exec(...)`. Выполнение bash-команд.

## Параметры
- `command` — команда (обязательно).
- `cwd` — рабочая директория (по умолчанию корень проекта).
- `timeout_sec` — таймаут.

## Безопасность
Требует **dangerous mode**. При запуске всегда запрашивается подтверждение пользователя перед выполнением. → `concepts/dangerous_mode.md`

## Связи
Зарегистрирован как `shell_exec` в `ToolManager`. → `entities/tool_manager.md`
