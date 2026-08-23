---
type: concept
tags: [llm]
updated: 2026-08-23
sources: 2
status: stable
---

# Function Calling (инструменты)

Механика вызова инструментов моделью — основа агентности Ботинка.

## Поток
1. `ToolManager.get_all_descriptions()` отдаёт определения инструментов (OpenAI JSON Schema `type: function`) в запросе к модели. → `entities/tool_manager.md`
2. Модель возвращает `tool_calls`: имя + аргументы (JSON-строка).
3. `ToolManager.call_tool(name, args, session_path, ...)` парсит аргументы, применяет политику безопасности и выполняет функцию из `tools/*`.
4. Результат возвращается модели как сообщение `tool`; цикл повторяется до финального ответа.

## Бэкенды
- **Ollama** — нативные `/api/chat` tool-calls.
- **OpenAI-совместимые** — адаптер переводит формát `v1/chat/completions` ⇄ Ollama на лету. → `entities/openai_compat.md`

## Модели без tools
Некоторые модели не поддерживают поле `tools`: детектор `_ollama_error_indicates_no_tools` + режим только-чат (`chat_only.txt`) через `_ensure_chat_only_system_message`. → `entities/ollama_backend.md`

## Безопасность вызова
- В `call_tool` блокируются опасные действия `file_system` вне dangerous mode; shell_exec всегда просит подтверждение. → `concepts/dangerous_mode.md`
- Логирование вызовов — `tools.log`; большие результаты — в `artifacts/`. → `concepts/context_management.md`

## Связи
Список инструментов — `overview.md`. Реестр — `entities/tool_manager.md`.
