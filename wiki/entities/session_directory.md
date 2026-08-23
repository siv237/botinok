---
type: entity
tags: [session]
updated: 2026-08-23
sources: 2
status: stable
---

# Директория сессии (session_directory)

Каждая сессия — директория `sessions/<timestamp>_<name>/` (базовый путь из конфига `Storage.SessionsDir`). Спецификация структуры и логирования — в `SessionManager`. → `entities/session_manager.md`

## Структура
```
sessions/<ts>_<name>/
├── context.json        # полная история диалога + thinking + tool_calls (+ состояние памяти)
├── thinking.md         # лог всех размышлений модели (thinking block)
├── response.md         # финальные ответы без служебной информации
├── tools.log           # детальный лог вызовов инструментов (JSON, размер, время)
├── session_raw.log     # построчный лог чанков в реальном времени (с дельтой)
├── performance.log     # компактный лог производительности (tps, vram, ctx) по шагам
├── steps/*.json        # подробности запросов/ответов по шагам
├── artifacts/          # дампы больших результатов инструментов (HTML, JSON, ошибки)
├── project/            # рабочая директория «проекта» сессии
├── prompts/            # копия системных промптов, специфичная для сессии
└── proofreader/        # состояние корректора (context.json)
```

## Назначения
- `context.json` — авторитетный источник истории; `context_trimmed`/протокол переполнения кладут дампы в `artifacts/`.
- Метрики фиксируются в YAML-шапку/футер (`BOTINOK_SESSION_METADATA`): total/thinking/response tokens, tps, ttft, duration.
- `prompts/` копируются при создании сессии и редактируются под задачу (fallback на глобальные). → `sources/prompts_readme.md`

## Связи
- Создаётся и ведётся `SessionManager.create_session` и методами `log_*`/`update_context`. → `session_manager.md`
- Читается объектно через инструмент `session_memory`. → `entities/tools/session-memory.md`, `concepts/session_lifecycle.md`
