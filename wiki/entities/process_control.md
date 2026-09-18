---
type: entity
tags: [tui, safety]
updated: 2026-09-18
sources: 1
status: stable
---

# Process control — единый реестр процессов и мгновенная остановка

`core/process_control.py` — общий реестр дочерних процессов и прерываемый
запуск. Нужен, потому что `subprocess.run` блокирует поток и не реагирует на
Esc: инструмент (aria2c, jq, lynx, safe_ops, shell) продолжал работать, а
«Stop requested» только копился. → `entities/textual_ui.md`

## API
- `run(argv, timeout, cwd, env, input, capture_output, text)` — как
  `subprocess.run`, но: `start_new_session=True` (своя группа процессов),
  регистрация в реестре, `communicate` в отдельном потоке и опрос `stop_event`
  каждые 0.1 с.
- `request_stop()` — ставит флаг и **убивает все зарегистрированные процессы**
  сигналом группе (`killpg(SIGTERM)` → grace 2 с → `SIGKILL`). Так гибнет и
  сам процесс, и все порождённые им («внуки»).
- `stop_requested()` / `clear_stop()`, `register()`/`unregister()`,
  `terminate(proc)`.

## Интеграция
- `BotinokTextualApp.request_stop()` → `process_control.request_stop()` +
  `ShellSessionRegistry.close_all()` (гасятся и PTY-сессии `shell_exec`).
- Esc (Composer и App) логирует «Остановлено» **один раз** (`_stop_log_once`).
- `start_assistant_turn` сбрасывает флаг (`clear_stop`) на новом ходе.
- Прерванный инструмент помечается в сессии как `aborted` с результатом
  «ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ…», ход не продолжается.
- `web._fetch`/httpx-циклы и `safe_ops`/`file_system`/`web`/`aria2c` используют
  прерываемый запуск.

## Остановка модели
Процессы — это не всё: сама генерация LLM тоже должна прекращаться. Это делается
не здесь, а обрывом стрима — `_abort_stream()` в `core/textual_integration.py`
(`shutdown` сокета). → `concepts/streaming_tui.md`

## Связи
`entities/textual_ui.md`, `concepts/streaming_tui.md`, `concepts/dangerous_mode.md`,
`tests/test_process_control.py`, `tests/test_abort_stream.py`.
