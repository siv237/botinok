---
type: entity
tags: [tool, session]
updated: 2026-10-11
sources: 2
status: stable
---

# sign_step — подпись хода самой моделью

Инструмент `tools/sign_step/`: модель отмечает сделанное **чекпоинтами в процессе хода** (`sign_step(done=…)` после каждого значимого шага) и финальной подписью перед ответом (со `status`). → `concepts/context_memory_research.md`

## Схема подписи (жёсткая)

- `goal`/`done` — ≤15 слов; `status` — enum `progress | blocked | decision | answered` (с алиасами: «готово»→answered и т.п.).
- `entities` — только закрытый список того, что харнес **реально видел** в ходе (пути/URL/аргументы инструментов); валидация подстрокой по `observed`. Левая сущность → одна ретрай-попытка с текстом ошибки, дальше подписи принимаются молча.

## Куда попадает

- Подписи пишутся в `signatures.json` (несколько на окно) и подхватываются `core/session_digest` (`Window.signs/sign` → goal/done в строке `FORGOTTEN_INDEX`) — прогресс **не теряется при сбросе контекста** и виден в списке сессий (последняя подпись).
- В чат и в `messages` не попадает (не шумит).
- При заполнении контекста ≥40% без единой отметки агент получает напоминание.

## Связи
- `entities/tools/session-memory.md` — подъём забытого по индексу
- `concepts/context_management.md` — скользящее окно и сбросы
- `entities/session_directory.md` — `signatures.json` в архиве сессии
