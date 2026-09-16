---
type: entity
tags: [tool, session, tui]
updated: 2026-09-16
sources: 1
status: stable
---

# ShellSession — PTY-сессия команды

`core/shell_session.py`. Ядро механики «shell как отдельная сессия»: команда
крутится в собственном псевдотерминале (PTY) и **НЕ держит агента**. UI-экран
(`entities/shell_screen.md`) — лишь один из наблюдателей этой сессии.

## Зачем
Раньше `shell_exec` запускал `subprocess.run` и блокировал агентский цикл до
завершения команды. Теперь команда живёт в фоне: агент читает вывод порциями,
ищет по нему, шлёт ввод (пароли, пункты меню), ждёт завершения — не выгружая
весь буфер в контекст.

## Состав
- **`ShellSession`** — один живой процесс в PTY.
  - `pty.openpty()` + `subprocess.Popen(..., start_new_session=True)`, master
    переведён в неблокирующий режим.
  - Поток-ридер `_reader_loop` на `select()` читает master в буферы и
    оповещает подписчиков (`subscribe`/`_notify`); таймаут — `timeout_sec`
    (по умолчанию 120 с на уровне инструмента).
  - Буферы: `_raw` (с ANSI, для артефакта/UI, лимит `MAX_BUFFER_BYTES=4 МиБ`) и
    `_clean_str` (очищенный текст для агента, `deque(maxlen=20000)`); счётчик
    `lines_total` монотонный, `buffered_lines` — сколько реально удержано.
  - `_partial` — последняя строка без `\n`; досдаётся сразу, чтобы промпты вида
    `Password:` были видны, не дожидаясь Enter.
  - ANSI-очистка: `_strip_ansi` срезает SGR/CSI/OSC, alt-screen, backspace.
  - Ввод: `send_bytes` (сырьё), `send_input` (текст + Enter, LF→CR),
    `send_key` (`KEY_SEQUENCES`: enter, up/down, y/n, ctrl-c, f1…). → `entities/tools/shell-exec.md`
  - Завершение: `kill()` — SIGINT группе процесса и **эскалация до SIGKILL** по
    `subprocess.TimeoutExpired`; `close()` — kill + закрытие master + `_stop_flag`.
  - Чтение: `get_output(tail_lines)`, `get_raw_tail(max_bytes)`,
    `search_output(pattern, regex, context)` (ограничен `MAX_SEARCH_MATCHES=200`,
    `context ≤ MAX_SEARCH_CONTEXT=50`), `wait(timeout)`, `status_dict()`.
  - `start()` при сбое `Popen` закрывает оба конца PTY (без утечки дескрипторов).
- **`ShellSessionRegistry`** — синглтон живых сессий (`add/get/list/remove`),
  `cleanup_dead()` (уборка завершённых старше 10 мин) и `close_all()`; на выходе
  процесса срабатывает `atexit`-хук `_shutdown_sessions` — дети не осиротеют.
- **`TextualAppRegistry`** — глобально хранит живое Textual-приложение. Нужен,
  т.к. инструменты вызываются из рабочего потока, где ContextVar `active_app`
  НЕ наследуется. API: `set_app` / `get_app` / `clear`.

## Связи
- Инструмент-обёртка: `entities/tools/shell-exec.md`.
- Встроенный экран: `entities/shell_screen.md`, `concepts/embedded_terminal.md`.
- Требует dangerous mode/подтверждения: `concepts/dangerous_mode.md`.
