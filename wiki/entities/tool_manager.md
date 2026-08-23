---
type: entity
tags: [tool]
updated: 2026-08-23
sources: 2
status: stable
---

# ToolManager

`core/tool_manager.py` — класс `ToolManager`. Реестр, описания и **lazy-загрузка** всех инструментов (function calling).

## Как работает
- **Реестр** `_tool_registry`: имя инструмента → `(module, function)`. Охватывает 13 инструментов + алиас `web_extractor` → `web_extract` (подробно в `entities/tools/`).
- **Lazy-загрузка** `_load_tool(name)`: модуль импортируется `importlib.import_module` только при первом обращении. Сломанные (SyntaxError/прочие исключения) фиксируются в `broken_tools` и логируются (`~/.botinok/logs/tools.log`).
- **Описания** `_descriptions`: JSON Schema в OpenAI-формате (`type: function`) — напрямую отдаются модели как `tools`.
- **Данжер-режим**: `dangerous_mode` берётся из env `BOTINOK_DANGEROUS=1`. → `concepts/dangerous_mode.md`

## Ключевые методы
- `get_tool(name)`, `get_all_tools()`, `call_tool(name, args, session_path, progress_callback)` — выполнение с подстановкой `session_path`, `progress_callback` (curl), `dangerous_mode` (file_system).
- `call_tool` принимает `args` как dict или JSON-строку; даёт понятные ошибки для неизвестного/сломанного инструмента.
- `get_all_descriptions()` / `get_tool_definitions()` — определения для модели, включая пометку сломанных.
- `get_broken_tools_info()` — человекочитаемый свод о сломанных инструментах для агента.

## Безопасность в call_tool
Если не `dangerous_mode`, для `file_system` действия `delete, move, copy, mkdir, chmod, symlink, touch` возвращают ошибку «requires dangerous mode». → `concepts/dangerous_mode.md`, `entities/tools/file-system.md`

## Связи
- Регистрирует модули из `tools/*`.
- Вызывается из `botinok.py` и `textual_integration.py` в цикле tool-calls. → `concepts/function_calling.md`
