---
type: entity
tags: [tui]
updated: 2026-09-16
sources: 4
status: stable
---

# Textual UI

Текстовый интерфейс пользователя на базе библиотеки [Textual](https://textual.textualize.io/). Состоит из модулей в `core/`:

- `textual_app.py` — класс `BotinokTextualApp` (главное приложение TUI).
- `textual_integration.py` — функция `ask_ollama_textual(...)`: поток вызова модели через TUI (стрим, tool-calls, markdown-рендеринг, спойлеры).
- `textual_history_viewer.py` — класс `HistoryViewerApp` + `view_history(session_path)` — просмотр истории сессии.
- `shell_screen.py` — класс `ShellScreen` (встроенный терминал). → `entities/shell_screen.md`
- `textual_prompts.py` — простые Textual-диалоги (`textual_select`/`textual_prompt`/`textual_confirm`) вместо inquirer/rich.prompt.
- `session_picker.py` — Textual-экран выбора/возобновления сессии (замена readchar-таблицы): двухшагово — меню из 3 пунктов, затем список с фильтром.
- `cli_io.py` — plain-вывод (`out`, `term_width`) вместо Rich Console для CLI/wizard.

## Возможности
- **Плавный стриминг**: UI ускорен до 10/30 FPS; `stream_static` конвертируется «на месте», спойлеры закрываются по очереди (не мигает).
- **Collapsible-спойлеры** в общем потоке вместо RichLog (для thinking/артефактов).
- **Хронологический порядок вывода (инвариант)**: поздний контент никогда не становится более ранним. Рассуждение стримится первым (сверху); при финализации хода оно схлопывается в одну строку `Thinking: <превью> <время>` и монтируется `before=stream_static` — на своё место над ответом (`finalize_assistant_turn`). Превью рассчитывается по ширине чата (`_spoiler_title`), чтобы строка не переносилась. В истории (`_render_history_entry`) спойлер thinking стоит перед ответом.
- **No хвоста рассуждения**: `stream_static` финализируется ВСЕГДА (`finalize_assistant_turn`): есть финальное содержимое → Markdown, нет → `update("")`. Иначе для ходов «только мышление + вызов инструмента» (`content=""`, `thinking>0`, `tool_calls=1`) сырой многострочный текст мышления оставался бы мусором в общем потоке под свёрнутыми спойлерами. В чате после ответа остаются только: запрос → спойлер `Thinking` → спойлер `Tool calls` → отформатированный ответ.
- **Прокрутка без прилипания**: auto-scroll к низу работает только пока пользователь реально внизу. `_tick_stats` каждые 0.1 с сравнивает `scroll_y` с прошлым значением: уменьшение позиции = намеренный скролл вверх (колесо/клавиши) → `_user_scrolled_away = True`, и `scroll_end` больше не вызывается, пока флаг установлен. Сброс — только когда пользователь явно докрутил до самого низа (`SCROLL_BOTTOM_EPS = 1` px — буквальный низ, без широкой «зоны внизу»). Дополнительно `on_mouse_scroll` (`_event_inside_chat`) ставит флаг сразу, не дожидаясь тика, а `_auto_scroll_chat` (вызывается при каждом монтировании спойлера) уважает флаг и не возвращает к выводу, пока пользователь листает.
- **Счётчик No chunks**: `_last_chunk_time` сбрасывается в `start_assistant_turn` (начало хода) и `flush_tool_buffer` (конец хода), иначе таймер зазора рос бесконечно между ходами.
- **Живое markdown-форматирование** стрима ассистента.
- **Независимый ввод** сообщений, очередь сообщений, остановка по ESC.
- Корректное отображение **VRAM на всех этапах**. → `concepts/streaming_tui.md`
- Визуальный паритет со старым Rich Live интерфейсом (заголовок окна, оформление).

- **Экранирование markup при рендере истории/ввода**: `_render_history_entry`, `append_user_message`, `on_input_submitted` и спойлеры thinking теперь прогоняют вставляемый контент через `_rich_escape` (`[`→`\[`, вырез управления). Раньше сырой текст из `context.json` (напр. вывод `shell_exec` с `xterm-256color`) попадал внутрь `[dim]...[/dim]` без экранирования и ронял рендер `MarkupError: Expected markup value` при старте.

## Панели (нативные виджеты)
Правая колонка и левый верх собраны на нативных виджетах Textual (без Rich-renderables):
- `#header` — `Static` с `content-align: center middle` и CSS-классами `dangerous`/`proofreader`.
- `#stats` («Performance») — контейнер с `border: round yellow` и `border-title`; внутри `Static` со строками статистики и `ProgressBar` (`#ctx_bar`, цвет по заполнению через классы `low/mid/high`).
- `#tools` («Tools Activity») — список карточек-`Collapsible`: в заголовке время + имя инструмента + статус; все карточки по умолчанию свёрнуты, по клику раскрываются и показывают дерево деталей (запрос, результат, размер). Карточки обновляются инкрементально (без пересоздания), состояние раскрытия сохраняется (`_tools_expanded`, `_tool_widgets`); тело обновляется через `Collapsible.Contents` (заголовок `CollapsibleTitle` тоже `Static`).
- `#diag` — кликабельный `Collapsible` в левой колонке наверху (вместо строки `Response (Lines: …)`): свёрнут в одну строку `Prompt: <последний вопрос>` с обрезкой по ширине (`cell_truncate`, `…`; пересчёт при `on_resize`). В раскрытом виде — список вопросов сессии карточками: `#diag_list` (`Vertical`) внутри `VerticalScroll` (`max-height: 14`), каждая карточка — `Collapsible` с заголовком `дата · сколько назад` + обрезка вопроса, по клику показывает полный текст. Вопросы подгружаются из истории (`context.json`) и добавляются при отправке; относительное время обновляется раз в 30 с. Блок `Performance` не перекрывает.
- Финальный ответ и история — виджет `Markdown` (Textual), стрим — `Static`.
`rich.text.Text` остаётся только как renderable для ANSI-вывода (логотип-баннер, лог терминала); сам пакет `rich` — транзитивная зависимость Textual. → `concepts/terminal_unicode_width.md`

## Баннер новой сессии
При старте новой сессии (пустая история) в начале `#chat` показывается логотип
`assets/logo.png`, сгенерированный в ASCII (`core/image_ascii.image_to_fullcolor`)
и автомасштабированный под ширину поля вывода, плюс строка версии
(`BOTINOK AGENT — Version …`). Для возобновлённой сессии (есть история) баннер не
показывается. Реализация: `_mount_banner` (через `call_after_refresh`, чтобы
знать ширину после раскладки). → `concepts/vision_multimodal.md`

## Встроенный терминал
`BotinokTextualApp` умеет показывать PTY-сессии `shell_exec` прямо в TUI:
- `open_shell_session(session)` открывает `ShellScreen`; одновременно открыто не более одного окна — остальные автоматически сворачиваются.
- Панель `#shells` в правой колонке перечисляет свёрнутые терминалы (кнопки `shell_restore_<session_id>`, метка «выполняется/завершён»), обновляется из `_tick_stats`.
- `minimize_shell_session` / `forget_shell_session` — колбэки экрана.

Подробно: `entities/shell_screen.md`, `entities/shell_session.md`, `concepts/embedded_terminal.md`.

## Взаимодействие
Из `botinok.py` интерактивный поток идёт через `ask_ollama_textual` (единственный UI; старый Rich Live удалён в 0.4), а headless — через `ask_ollama_stealth`. → `botinok_cli.md`, `comparisons/rich_vs_textual.md`

## Связи
- HistoryViewer читает структуру сессии. → `entities/session_directory.md`
- Логика токенов/контекста перенесена и сюда (`textual_integration` дублирует утилиты из `botinok.py`): `_prepare_messages_for_ollama`, `_compact_tool_message`, `_ollama_summarize_and_reset_context`, `_detect_repetition`. → `concepts/context_management.md`
