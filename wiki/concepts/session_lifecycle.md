---
type: concept
tags: [session]
updated: 2026-08-23
sources: 2
status: stable
---

# Жизненный цикл сессии

Сессия — единица работы агента. Базовая логика — в `core/session_manager.py`; пользовательские выборы — `_choose_or_resume_session()` в `botinok.py`. → `entities/session_manager.md`, `entities/session_directory.md`

## Этапы
1. **Создание**: `create_session(name)` → директория `sessions/<ts>_<name>/` с подпапками и копией промптов; стартовый `context.json`.
2. **Выбор/возобновление**: при запуске можно выбрать существующую сессию (интерактивная таблица с курсорной навигацией, фильтрацией по вводу, относительным временем) или создать новую. Сессия создаётся только после успешного выбора.
3. **Работа**: поток диалога — пользовательский запрос → модель (thinking → tool-calls → результат) → ответ. Всё логируется (thinking.md, response.md, tools.log, context.json).
4. **Продолжение**: `load_last_assistant_answer()`/`load_first_user_prompt()` показывают контекст; `resume_context.txt` описывает продолжение.
5. **Переполнение**: при лимитах — протокол `SESSION_PROTOCOL`. → `concepts/context_management.md`

## Подробности
- Сессия хранит полный трейс, что позволяет возвращаться и продолжать работу (промпты сессии можно редактировать под задачу). → `sources/prompts_readme.md`
- Объектный доступ к истории — через инструмент `session_memory`. → `entities/tools/session-memory.md`

## Связи
Подробнее про структуру файлов — `entities/session_directory.md`. Управление — `entities/session_manager.md`.
