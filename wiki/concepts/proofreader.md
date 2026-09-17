---
type: concept
tags: [llm]
updated: 2026-09-17
sources: 3
status: stable
---

# Режим корректора (Proofreader)

Двухшаговый цикл «Исполнитель → Корректор» для повышения качества ответов.

## Запуск
`botinok --proofread` — включает режим корректора. → `entities/botinok_cli.md`

## Как работает
- Исполнитель генерирует ответ.
- Корректор проверяет/улучшает текст по пошаговому алгоритму (`proofreader.txt`, `run_proofreader_turn`).
- История корректора хранится в `proofreader/context.json` сессии (`load/save_proofreader_history` в `SessionManager`). → `entities/session_directory.md`, `entities/session_manager.md`

## Текущий статус
Корректор работает и в интерактивном Textual-режиме, и в headless. В TUI
`--proofread` подключает `run_proofreader_turn` после хода исполнителя (передаётся
в `ask_ollama_textual(proofread=True, proofreader_fn=...)`); замечания выводятся в
чат, при наличии правок исполнитель получает их как следующий запрос (до
`MAX_PROOFREAD_ROUNDS = 3` раундов). В headless/pipe-режиме корректор идёт через
`ask_ollama_stealth`. Rich-визуализация корректора (`vis`, консольные
подтверждения) удалена вместе с Rich-движком в 0.4.

## Связи
Промпт-инструкции — `sources/prompts_readme.md`. Реализация — `botinok.py::run_proofreader_turn`.
