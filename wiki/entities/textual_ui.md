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
- **Живое markdown-форматирование** стрима ассистента.
- **Независимый ввод** сообщений, очередь сообщений, остановка по ESC.
- Корректное отображение **VRAM на всех этапах**. → `concepts/streaming_tui.md`
- Визуальный паритет со старым Rich Live интерфейсом (заголовок окна, оформление).

## Взаимодействие
Из `botinok.py` поток идёт через `ask_ollama_textual` (TUI-режим) либо `ask_ollama_stream` (Rich). Переключение — флаг `--rich-mode`. → `botinok_cli.md`, `comparisons/rich_vs_textual.md`

## Связи
- HistoryViewer читает структуру сессии. → `entities/session_directory.md`
- Логика токенов/контекста перенесена и сюда (`textual_integration` дублирует утилиты из `botinok.py`): `_prepare_messages_for_ollama`, `_compact_tool_message`, `_ollama_summarize_and_reset_context`, `_detect_repetition`. → `concepts/context_management.md`
