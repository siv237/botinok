---
type: concept
tags: [safety]
updated: 2026-08-23
sources: 2
status: stable
---

# Dangerous Mode (безопасность)

Потенциально опасные действия требуют явного включения. Цель — предотвратить случайные разрушительные операции LLM-агентом.

## Включение
- Опасные инструменты (`code_editor`, `shell_exec`) по умолчанию отключены.
- Активация на сессию: `botinok --dangerous` (разовый флаг CLI). → `entities/botinok_cli.md`
- Либо env `BOTINOK_DANGEROUS=1` (читается `ToolManager`).

## Что считается опасным
- `code_editor` (write/replace/apply) — правка кода.
- `shell_exec` — выполнение команд (всегда запрашивает подтверждение пользователя перед выполнением).
- `file_system` мутации: `delete` · `move` · `copy` · `mkdir` · `chmod` · `symlink` · `touch` — требуют dangerous mode; вне сессии ещё и подтверждение.
- `curl` запись ответа **вне** папки сессии.

## Реализация
- `ToolManager.call_tool` блокирует опасные действия вне dangerous mode возвратом ошибки.
- Безопасная FS-обёртка: проверки «в пределах» (`_is_within`, `_is_within_session`), `_confirm_action`, `_safe_path`. → `entities/tools/file-system.md`
- Промпт-уведомление `dangerous_mode.txt` говорит модели о режиме. → `sources/prompts_readme.md`

## Связи
Инструменты: `code_editor`, `shell_exec`, `file_system`, `curl`.
