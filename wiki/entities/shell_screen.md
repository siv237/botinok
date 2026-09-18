---
type: entity
tags: [tui, tool]
updated: 2026-09-18
sources: 2
status: stable
---

# ShellScreen / ShellInline — встроенный терминал в TUI

`core/shell_screen.py`. Два представления одной PTY-сессии
(`entities/shell_session.md`): живой вывод и поле ввода, чтобы человек работал
в команде наравне с агентом.

- **`ShellInline(Vertical)`** — панель, встроенная прямо в окно вывода (над
  чатом). **Режим по умолчанию** при запуске shell из агента.
- **`ShellScreen(ModalScreen)`** — модальное окно на весь экран (кнопка
  «Развернуть» / возврат из панели свёрнутых).

## Встроенная панель (ShellInline, по умолчанию)
`#inline_shell` в `core/textual_app.py` — контейнер в колонке `#content`
**над** `#chat` (`height: 50%`, класс `.active`). Верх занимает терминал,
низ — продолжающийся стрим модели. Элементы:
- `#inline_shell_title` — статус с анимацией и счётчиком (`_terminal_title`,
  `_tick_state`, 0.15 с): пока идёт — `⠋ имя · идёт Ns`, после выхода —
  `✔ имя · завершён за Ns (rc=…)`, при остановке — `■ имя · остановлен Ns`.
  Динамические значения экранируются (команда может содержать `[`).
- `#inline_shell_log` — `RichLog` с ANSI-цветами, автоскролл; при открытии
  отдаёт уже накопленный хвост (`get_raw_tail(64 КиБ)`). По завершении процесса
  в лог один раз дописывается явный маркер `─── завершено за Ns (rc=…) ───`
  (или `─── остановлено · Ns ───`) — видно, что команда закончилась.
- `#inline_shell_input` — ввод строки (`send_input`); фокус ставится при
  монтировании, `_keep_focus` не отбирает его у панели.
- `#inline_shell_buttons` — **«Развернуть»** (`#inline_shell_expand`),
  **«Свернуть»** (`#inline_shell_minimize`), **«Закрыть»** (`#inline_shell_close`).

Переиспользование: виджет создаётся один раз и **не удаляется** из DOM —
«свернуть» значит `detach()` + снять класс `active` у контейнера (display:none).
При новой сессии он переключается через `set_session()` (старая уходит в панель
свёрнутых). Удаление через `remove()` асинхронно, и новый виджет, смонтированный
до prune, оставлял «застрявшего» потомка — после этого следующий shell не
открывался. Флаг активности — `inline_shell_active`.

## Модальное окно (ShellScreen)
- Элементы `#shell_dialog`/`#shell_title`/`#shell_log`/`#shell_input`/
  `#shell_hint`/`#shell_buttons`.
- Кнопки: **«В окно»** (`#shell_inline`) — вернуть панель в поток вывода,
  **«Свернуть»** (`#shell_minimize`) — в панель свёрнутых, **«Закрыть»**
  (`#shell_close`) — завершить сессию.
- Ctrl+Q — свернуть, Ctrl+C — SIGINT, стрелки/pgup/pgdown — в PTY при фокусе
  на логе.

## Снятие окна
`_detach_view()` — идемпотентная отписка/остановка таймера; `_pop_screen(cb)`
снимает модалку и при необходимости зовёт `cb` после смены экрана
(`_defer_after_pop` опрашивает `app.screen`, т.к. `AwaitComplete` от
`pop_screen` в test-harness не завершается). `_detach()` = `_detach_view()` +
`pop_screen` + `on_done(session)`. `_to_inline()`, `_minimize()` и
`_terminate()` обновляют DOM основного экрана **только через `cb`** — трогать
панель в том же тике, что и `pop_screen`, нельзя: модалка не домонтируется и
UI подвисает, хотя фон работает. `_resolve_app()` — единая точка получения
живого приложения (реестр или `self.app`).

> Внутренний флаг «виджет отсоединён» называется `_view_closed`, а НЕ `_closed`:
> `MessagePump._closed` — служебный атрибут Textual, и его затенение приводило к
> тому, что виджет вычищался из DOM (перестали работать свернуть/развернуть).

## Доставка вывода
Ридер PTY вызывает `_handle_chunk` из **не-UI-потока**; запись в `RichLog`
планируется через `app.call_from_thread` (в Textual 8.2 он блокирующий —
читатель ждёт UI). Если приложение не найдено — пишем напрямую.

## Панель терминалов
Реализована в `core/textual_app.py` (`BotinokTextualApp`), `#shells` —
`VerticalScroll` в правой колонке (`max-height: 50%`, прокрутка):
- **Верхняя строка `#shells_active`** — всегда видна, пока открыт встроенный
  терминал: `● активный <имя> · <HH:MM:SS> · <N>s`, счётчик секунд от старта
  сессии тикает (обновляется из `_tick_stats`, сигнатура включает `int(elapsed)`).
- **Свёрнутые сессии** — однострочные `Horizontal`-строки: `Button`
  `shell_restore_<session_id>` с именем команды (`width: 1fr`, тянется на всю
  свободную ширину, обрезка с `…`), `Static.stamp` со временем старта и
  длительностью справа (`width: auto`), и кнопка `✕`
  `shell_kill_<session_id>` (завершает сессию, `forget_shell_session`).
- Обновление **инкрементально**: строки переиспользуются по `session_id`
  (`_shell_widgets`), заголовок/активная строка создаются один раз; сигнатура
  `_shells_sig` (включает секунды) защищает от лишних перерисовок.
- `embed_shell_session(session)` / `open_shell_session(session)` — открыть
  панель встроенной; `expand_shell_session(session)` — развернуть в модалку.
- `minimize_shell_session(session)` / `forget_shell_session(sid)` — колбэки;
  `on_button_pressed` обрабатывает `shell_restore_*` и `shell_kill_*`.
- Открыт максимум один терминал: при открытии нового `ShellScreen`-ы и старая
  inline-панель сворачиваются (`_minimize_open_shell_screens`).

## Защита от RecursionError
`ModalScreen` по умолчанию полупрозрачен; десятки наложенных модалок давали
цепочку `BackgroundScreen` и `RecursionError`. Защита: непрозрачный фон
`ShellScreen` и отказ от накопления окон (одно видимое + панель).

## Разворот команды (shfmt)
`format_shell_command(command)` (`core/shell_screen.py`) прогоняет команду через
**shfmt** (`shfmt-py`): полноценно парсит bash и pretty-принтит — разбивает `;`
на строки, сохраняет `for …; do`, выравнивает тело и `done`. Если бинарь
недоступен/команда не парсится — возвращается исходная строка. Результат
кэшируется (`lru_cache`). Где применяется:
- клик по заголовку терминала (`#inline_shell_title`/`#shell_title`) раскрывает
  `#inline_shell_cmd`/`#shell_cmd`;
- подтверждение опасного действия показывает команду развёрнутой сразу
  (`#inline_confirm_cmd` в прокрутке);
- в истории сессии тело раскрытого вызова `shell_exec` (`_format_tool_call`).

## Связи
- Сессия и реестры: `entities/shell_session.md`.
- Главное TUI: `entities/textual_ui.md`.
- Концепция: `concepts/embedded_terminal.md`.
- Безопасность: `concepts/dangerous_mode.md`.
