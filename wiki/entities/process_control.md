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
- `signal_stop()` — **мягкая** остановка: только выставляет флаг. Запущенный
  через `run()` процесс сам замечает флаг и аккуратно завершает свою группу
  (`terminate`), а ход успевает штатно финализироваться. Никого «чужого» не
  убивает — это безопасный путь для Esc.
- `request_stop()` — **жёсткая** остановка: флаг + **убийство всех
  зарегистрированных процессов** (`killpg(SIGTERM)` → grace 2 с → `SIGKILL`).
  Для явного «стоп всё», не для обработчика клавиши.
- `stop_requested()` / `clear_stop()`, `register()`/`unregister()`,
  `terminate(proc)`.

## Интеграция
- `BotinokTextualApp.request_stop()` → `process_control.signal_stop()` (только
  флаг). Из обработчика Esc **нельзя** вызывать `kill_all`/закрытие PTY-сессий:
  это гоняется с записью `context.json` и рвёт сессию.
- Esc (Composer и App) логирует «Остановлено» **один раз** (`_stop_log_once`).
- Флаг сбрасывается **один раз на запрос** пользователя — в `reset_turn_state`
  (не в `start_assistant_turn`, который зовётся каждую итерацию цикла).
- Прерванный инструмент помечается в сессии как `aborted` с результатом
  «ОСТАНОВЛЕНО ПОЛЬЗОВАТЕЛЕМ…», ход не продолжается.
- `web._fetch`/httpx-циклы и `safe_ops`/`file_system`/`web`/`aria2c` используют
  прерываемый запуск.

## Остановка модели
Процессы — это не всё: сама генерация LLM тоже должна прекращаться. Это делается
не здесь, а обрывом стрима — `_abort_stream()` в `core/textual_integration.py`
(`shutdown` сокета). → `concepts/streaming_tui.md`

## Контракт Esc (не нарушать)
Esc прерывает **текущее действие и ход**, после чего агент **останавливается и
ждёт следующее сообщение** пользователя. Он НЕ должен: продолжать диалог,
запускать авто-продолжение, автоподставлять «Сформулируй финальный ответ» или
автоматически отправлять накопленную очередь. Накопленный ввод возвращается в
поле ввода (`flush_tool_buffer` при `_stop_requested`), а не отправляется сам.
Сессия обязана оставаться живой и корректной.

## Связи
`entities/textual_ui.md`, `concepts/streaming_tui.md`, `concepts/dangerous_mode.md`,
`tests/test_process_control.py`, `tests/test_abort_stream.py`.
