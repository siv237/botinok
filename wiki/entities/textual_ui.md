---
type: entity
tags: [tui]
updated: 2026-08-23
sources: 2
status: stable
---

# Textual UI

Текстовый интерфейс пользователя на базе библиотеки [Textual](https://textual.textualize.io/). Состоит из трёх модулей в `core/`:

- `textual_app.py` — класс `BotinokTextualApp` (главное приложение TUI).
- `textual_integration.py` — функция `ask_ollama_textual(...)`: поток вызова модели через TUI (стрим, tool-calls, markdown-рендеринг, спойлеры).
- `textual_history_viewer.py` — класс `HistoryViewerApp` + `view_history(session_path)` — просмотр истории сессии.

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

## Взаимодействие
Из `botinok.py` поток идёт через `ask_ollama_textual` (TUI-режим) либо `ask_ollama_stream` (Rich). Переключение — флаг `--rich-mode`. → `botinok_cli.md`, `comparisons/rich_vs_textual.md`

## Связи
- HistoryViewer читает структуру сессии. → `entities/session_directory.md`
- Логика токенов/контекста перенесена и сюда (`textual_integration` дублирует утилиты из `botinok.py`): `_prepare_messages_for_ollama`, `_compact_tool_message`, `_ollama_summarize_and_reset_context`, `_detect_repetition`. → `concepts/context_management.md`
