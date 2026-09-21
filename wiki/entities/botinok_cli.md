---
type: entity
tags: [llm, session, tui]
updated: 2026-09-18
sources: 4
status: stable
---

# Botinok CLI / main

Точка входа: `botinok.py` (запуск через скрипт `botinok`, который вызывает venv-python). Содержит парсер CLI, выбор/возобновление сессии и запуск интерфейса. Старый Rich Live движок удалён (0.4) — остался только Textual TUI и headless stealth-цикл.

## CLI-флаги (см. `sources/readme.md`)
- `-m MODEL` — модель Ollama; `-c CTX` — размер контекста (напр. 16384/32768).
- `--dangerous` — разовая активация опасных инструментов (ставит `BOTINOK_DANGEROUS=1`). Без него мутации разрешены только внутри папки сессии; выход за её пределы в TUI запрашивает переключение. → `concepts/dangerous_mode.md`
- `--stealth` — headless-режим: только финальный ответ (для автоматизации).
- `-p/--prompt` / позиционный аргумент — стартовый запрос; в Textual отправляется автоматически.
- `--proofread` — режим корректора, работает и в Textual, и в headless. → `concepts/proofreader.md`
- `--wizard` — мастер настройки. → `concepts/config_priority.md`
- `--update`, `--update-packages`/`-U` — обновление. → `concepts/self_update.md`
- `--ensure-deps` — только проверка/установка системных компонентов (`chafa`, `ffmpeg`, `aria2`, …), без обновления кода. → `concepts/self_update.md`
- `--debug` — отладочный вывод (в т.ч. в Textual).

## Режимы запуска
- **Интерактивный** — Textual TUI (`ask_ollama_textual`), при TTY и без `--stealth`. → `entities/textual_ui.md`
- **Stealth** — только финальный ответ, без ASCII-арта и панелей (`ask_ollama_stealth`).
- **Pipe** — автоопределение stdin → stealth. → `concepts/stealth_pipe_mode.md`

## Главные функции потока
- `ask_ollama_textual(...)` — интерактивный цикл Textual (в `core/textual_integration.py`). → `entities/textual_ui.md`
- `ask_ollama_stealth(...)` — headless-цикл (stealth/pipe и корректор).
- `run_proofreader_turn(...)` — корректор (headless, через `ask_ollama_stealth`). → `concepts/proofreader.md`
- `_choose_or_resume_session(...)` — выбор/возобновление сессии через Textual-экран `core/session_picker.py` (до старта основного TUI).
- `_get_version_info` / `_check_remote_version` / `_perform_update` — версия и обновление. → `concepts/self_update.md`

## Утилиты токенов
`_estimate_tokens`, `_estimate_message_tokens`, `_prepare_messages_for_ollama` (резерв токенов, автообрезка), `_compact_tool_message` (дамп больших результатов в артефакты). → `concepts/context_management.md`

## Связи
- Использует `SessionManager` (`sm`), `ToolManager` (`tm`).
- Бэкенд выбран через `is_openai_backend` / `chat_stream_request` из `openai_compat`. → `entities/openai_compat.md`
