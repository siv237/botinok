---
type: entity
tags: [tui, tool]
updated: 2026-09-16
sources: 1
status: stable
---

# ShellScreen — встроенный терминал в TUI

`core/shell_screen.py`, класс `ShellScreen(ModalScreen)`. Модальное окно поверх
основного экрана Botinok: живой вывод PTY-сессии (`entities/shell_session.md`) и
поле ввода, чтобы человек работал в команде наравне с агентом.

## Состав окна
- `#shell_title` — имя сессии, cwd, состояние (`выполняется`/`завершён (rc=…)`/`остановлен`), elapsed; обновляется таймером `_tick_state` (0.5 с).
- `#shell_log` — `RichLog` с ANSI-цветами, автоскролл; при открытии заново отдаёт уже накопленный хвост (`get_raw_tail(64 КиБ)`).
- `#shell_input` — ввод строки (`send_input`).
- `#shell_hint` — подсказка по клавишам.
- `#shell_buttons` — кнопки **«Свернуть»** (`#shell_minimize`) и **«Закрыть»** (`#shell_close`).

## Клавиши и кнопки
- **Ctrl+Q / «Свернуть»** → `_minimize()`: окно снимается со стека, сессия
  остаётся живой и попадает в панель свёрнутых терминалов на основном экране.
- **«Закрыть»** → `_terminate()`: окно снимается и сессия завершается (`close()`).
- **Ctrl+C** → SIGINT в сессию (`send_key("ctrl-c")`).
- Стрелки/pgup/pgdown прокидываются в PTY, когда фокус на логе.

Общая механика снятия окна — `_detach()` (идемпотентно: `_closed`, отписка от
сессии, остановка таймера, `pop_screen` с до-выполнением `AwaitComplete`),
`_resolve_app()` — единая точка получения живого приложения (реестр или
`self.app`). `on_done(session)` — колбэк закрытия.

## Доставка вывода
Ридер PTY вызывает `_handle_chunk` из **не-UI-потока**; запись в `RichLog`
планируется через `app.call_from_thread` (в Textual 8.2 он блокирующий —
читатель ждёт UI). Если приложение не найдено — пишем напрямую.

## Панель свёрнутых терминалов
Реализована в `core/textual_app.py` (`BotinokTextualApp`):
- `#shells` в правой колонке — список `Button` `shell_restore_<session_id>` по
  всем свёрнутым сессиям с меткой состояния; обновляется из `_tick_stats`
  (перерисовка только при изменении сигнатуры `_shells_sig`).
- `minimize_shell_session(session)` / `forget_shell_session(sid)` — колбэки экрана.
- `open_shell_session(session)` — разворачивает окно; при этом **открыто не более
  одного окна**: остальные `ShellScreen` автоматически сворачиваются
  (`_minimize_open_shell_screens`), а не наслаиваются.
- `on_button_pressed` ловит `shell_restore_*` и возвращает окно по сессии из реестра.

## Защита от RecursionError
`ModalScreen` по умолчанию имеет полупрозрачный фон; десятки наложенных модальных
экранов порождали цепочку `BackgroundScreen` при рендере и падали с
`RecursionError`. Два уровня защиты: фон `ShellScreen` сделан непрозрачным
(`background: $surface`), и окна больше не накапливаются (одно открытое + панель).

## Связи
- Сессия и реестры: `entities/shell_session.md`.
- Главное TUI: `entities/textual_ui.md`.
- Концепция: `concepts/embedded_terminal.md`.
- Безопасность: `concepts/dangerous_mode.md`.
