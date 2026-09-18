---
type: entity
tags: [tool, safety, session, tui]
updated: 2026-09-18
sources: 3
status: stable
---

# Инструмент shell_exec

`tools/shell_exec.py` → функция `shell_exec(...)`. «Shell как отдельная
сессия»: команда запускается в PTY-сессии (`entities/shell_session.md`), которая
**не держит агента**. Возвращает JSON-строку.

## Действия (`action`)
| action | Назначение |
|--------|-----------|
| `run` | запустить команду в PTY, вернуть `session_id` + хвост вывода (по умолчанию) |
| `status` | состояние сессии + хвост |
| `read` | прочитать хвост (`tail_lines`) |
| `search` | поиск по выводу (`pattern`, `regex`, `context`) |
| `send` | отправить текст (как пользователь: с Enter) |
| `send_key` | спец-клавиша: `enter`, `down`, `up`, `y`, `n`, `ctrl-c`, … |
| `wait` | дождаться завершения (`wait_timeout`) |
| `kill` | прервать сессию (SIGINT → SIGKILL) |
| `list` | список живых сессий |

## Параметры
- `command` — команда (для `run`).
- `cwd` — рабочая директория (по умолчанию корень проекта).
- `timeout_sec` — таймаут сессии (по умолчанию 120 с; `0` — без таймаута).
- `session_id` — ID из ответа `run`.
- `input` / `key` — для `send` / `send_key`.
- `pattern` / `regex` / `context` — для `search`.
- `tail_lines` — сколько строк хвоста вернуть.
- `wait_timeout` — таймаут для `wait`.
- `interactive` — `true` открывает встроенный экран терминала в TUI.
- `name` — человекочитаемое имя сессии.

## UI
При `interactive=true` и живом Textual-приложении открывается окно
`entities/shell_screen.md`. Агент приложение находит через `TextualAppRegistry`
(работа из рабочего потока) и открывает экран через
`BotinokTextualApp.open_shell_session`. Окно можно свернуть — сессия попадёт в
панель свёрнутых терминалов на основном экране. Без TUI инструмент работает
headless (сессия в реестре).

## Безопасность
Опасные action (`run`/`send`/`send_key`/`kill`/`wait`) требуют **dangerous mode**.
В простом режиме вызов блокируется гейтом `ToolManager`; в TUI пользователю
предлагается окно переключения (да/нет), после согласия режим включается и
команда выполняется. В dangerous mode перед стартом команды всегда показывается
встроенное подтверждение (`ConfirmInline`, с галочкой автосогласия) — не модалка.
→ `concepts/dangerous_mode.md`

## Связи
- Ядро сессии и реестры: `entities/shell_session.md`.
- Экран и панель: `entities/shell_screen.md`, `concepts/embedded_terminal.md`.
- Регистрация в реестре инструментов: `entities/tool_manager.md`.
