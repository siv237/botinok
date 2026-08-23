---
type: concept
tags: [session, llm]
updated: 2026-08-23
sources: 2
status: stable
---

# Управление контекстом

Работа с ограниченным контекстом LLM — ключевая тема проекта (малый VRAM). Реализовано в `botinok.py` и `textual_integration.py` (+ промпты в `prompts/`).

## Механизмы
- **Оценка токенов**: `_estimate_tokens`, `_estimate_message_tokens`, `_estimate_messages_tokens`.
- **Подготовка**: `_prepare_messages_for_ollama(...)` — резерв токенов (reserve_tokens), автообрезка старых сообщений; дамп обрезанного в артефакт + уведомление `context_trimmed.txt`.
- **Компактизация tool-сообщений**: `_compact_tool_message` — большие результаты инструментов сохраняются в `artifacts/`, в контекст идёт ссылка, чтобы не раздувать окно. → `entities/session_directory.md`

## Переполнение контекста (SESSION_PROTOCOL)
Функция `_ollama_summarize_and_reset_context`:
1. `context_overflow_summary.txt` — модель суммаризирует важные факты.
2. `context_overflow_user.txt` — запрос на создание протокола с `original_task`; полная история сохраняется в артефакт.
3. `context_overflow_protocol.txt` — продолжение работы с очищенным контекстом.

Триггеры: `hard_ctx_threshold`, `repetition_detected`, `max_tool_rounds`. → `sources/prompts_readme.md`

## Детекция зацикливания
`_detect_repetition(full_response)` — выявление повторов, чтобы прервать бесконечные циклы. Затем — протокол/auto_continue.

## Авто-продолжение
- `auto_continue.txt` — продолжить задачу после очистки.
- `auto_continue_final.txt` — сформулировать финал при `missing_final_response` (мысли без ответа).

## Связи
Структура хранения — `entities/session_directory.md`. Возможности UI — `concepts/streaming_tui.md`.
