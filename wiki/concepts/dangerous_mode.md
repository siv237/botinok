---
type: concept
tags: [safety, tui]
updated: 2026-09-18
sources: 3
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

## Подтверждение в TUI
Подтверждение (`show_confirmation_prompt`) показывается **встроенно** в окно
вывода — `#inline_confirm` (`ConfirmInline`), а не модалкой поверх правых
панелей (модальный `ConfirmationScreen` остаётся запасным путём). Варианты:
✅ Да · ❌ Нет · ✏️ Отменить с причиной (`y/д`, `n/esc`, ↑↓+Enter). Воркер ждёт
ответ через `threading.Event` (`_confirmation_event`), таймаут 300 с. После
выбора `ConfirmInline` вызывает `_apply_confirmation` и убирается
(`hide_inline_confirmation`). Команда `shell_exec` показывается **развёрнутой**
через `shfmt` (`format_shell_command`) в прокручиваемом блоке; прочие аргументы —
pretty-JSON. → `entities/shell_screen.md`

## Связи
Инструменты: `code_editor`, `shell_exec`, `file_system`, `curl`.
