---
type: concept
tags: [llm]
updated: 2026-08-23
sources: 2
status: stable
---

# Режим корректора (Proofreader)

Двухшаговый цикл «Исполнитель → Корректор» для повышения качества ответов.

## Запуск
`botinok --proofread` — включает режим корректора. → `entities/botinok_cli.md`

## Как работает
- Исполнитель генерирует ответ.
- Перед запуском корректора запрашивается подтверждение (из истории: «Добавлен запрос перед запуском корректора»).
- Корректор проверяет/улучшает текст по пошаговому алгоритму (`proofreader.txt`, `run_proofreader_turn`).
- История корректора хранится в `proofreader/context.json` сессии (`load/save_proofreader_history` в `SessionManager`). → `entities/session_directory.md`, `entities/session_manager.md`

## Связи
Промпт-инструкции — `sources/prompts_readme.md`. Подробная реализация — `botinok.py::run_proofreader_turn`.
