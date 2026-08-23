---
type: entity
tags: [llm, session, tui]
updated: 2026-08-23
sources: 2
status: stable
---

# Botinok CLI / main

Точка входа: `botinok.py` (запуск через скрипт `botinok`, который вызывает venv-python). Содержит парсер CLI, главный цикл потока модели, TUI и корректора.

## CLI-флаги (см. `sources/readme.md`)
- `-m MODEL` — модель Ollama; `-c CTX` — размер контекста (напр. 16384/32768).
- `--dangerous` — разовая активация опасных инструментов.
- `--stealth` — выходная мощность: только финальный ответ (для автоматизации).
- `--rich-mode` — выбрать Rich Live TUI-движок (по умолчанию Textual TUI). → `entities/textual_ui.md`, `comparisons/rich_vs_textual.md`
- `--proofread` — режим корректора. → `concepts/proofreader.md`
- `--wizard` — мастер настройки. → `concepts/config_priority.md`
- `--update`, `--update-packages`/`-U` — обновление. → `concepts/self_update.md`
- `--debug` — отладочный вывод.

## Режимы запуска
- **Интерактивный** — полный UI (Textual TUI по умолчанию, Rich Live через `--rich-mode`). → `entities/textual_ui.md`, `comparisons/rich_vs_textual.md`
- **Одиночный запрос** — аргумент строкой; предлагает продолжить интерактивно.
- **Stealth** — только финальный ответ, без ASCII-арта и панелей.
- **Pipe** — автоопределение stdin → stealth. → `concepts/stealth_pipe_mode.md`

## Главные функции потока
- `ask_ollama_stream(...)` — стриминг в TUI (Rich/Textual), цикл tool-calls, TTFT/TPS.
- `ask_ollama_stealth(...)` — поток без интерфейса.
- `_ollama_summarize_and_reset_context(...)` — протокол переполнения контекста. → `concepts/context_management.md`
- `run_proofreader_turn(...)` — корректор. → `concepts/proofreader.md`
- `_choose_or_resume_session(...)` — выбор/возобновление сессии.
- `BotVisualizer` — класс визуализации (статистика VRAM/TPS/контекст).
- `_get_version_info` / `_check_remote_version` / `_perform_update` — версия и обновление. → `concepts/self_update.md`

## Утилиты токенов
`_estimate_tokens`, `_estimate_message_tokens`, `_estimate_messages_tokens`, `_prepare_messages_for_ollama` (резерв токенов, автообрезка), `_compact_tool_message` (дамп больших результатов в артефакты). → `concepts/context_management.md`

## Связи
- Использует `SessionManager` (`sm`), `ToolManager` (`tm`).
- Бэкенд выбран через `is_openai_backend` / `chat_stream_request` / `chat_once` из `openai_compat`. → `entities/openai_compat.md`
