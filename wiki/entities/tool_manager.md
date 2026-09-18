---
type: entity
tags: [tool]
updated: 2026-09-18
sources: 3
status: stable
---

# ToolManager

`core/tool_manager.py` — класс `ToolManager`. Реестр, описания и **lazy-загрузка** всех инструментов (function calling).

## Как работает
- **Реестр** `_tool_registry`: имя инструмента → `(module, function)`. Единый веб-добыватель `web` (`tools/web.py`) + legacy-обёртки `web_search`/`open_url`/`web_extract`/`curl` и алиас `web_extractor` (подробно в `entities/tools/`).
- **Lazy-загрузка** `_load_tool(name)`: модуль импортируется `importlib.import_module` только при первом обращении. Сломанные (SyntaxError/прочие исключения) фиксируются в `broken_tools` и логируются (`~/.botinok/logs/tools.log`).
- **Описания** `_descriptions`: JSON Schema в OpenAI-формате (`type: function`) — напрямую отдаются модели как `tools`.
- **Данжер-режим**: `dangerous_mode` берётся из env `BOTINOK_DANGEROUS=1` (или переключается в TUI командой `/dangerous`). → `concepts/dangerous_mode.md`
- **Гейт опасных действий** (`call_tool`, простой режим): `shell_exec` (`run/send/send_key/kill/wait`) запрещён; запись `code_editor`, мутации `file_system` и `curl output_path` разрешены только **внутри** `session_path`, иначе — ошибка с намёком, что пользователь может разрешить переключение.

## Ключевые методы
- `get_tool(name)`, `get_all_tools()`, `call_tool(name, args, session_path, progress_callback)` — выполнение с подстановкой `session_path`, `progress_callback` (curl), `dangerous_mode` (file_system).
- `call_tool` принимает `args` как dict или JSON-строку; даёт понятные ошибки для неизвестного/сломанного инструмента.
- `get_all_descriptions()` / `get_tool_definitions()` — определения для модели, включая пометку сломанных.
- `get_broken_tools_info()` — человекочитаемый свод о сломанных инструментах для агента.

## Безопасность в call_tool
Если не `dangerous_mode` — ошибку «requires dangerous mode» возвращают:
- `shell_exec` (опасные action);
- `code_editor` (`write`/`replace`/`apply`) и `file_system` (мутации) — **если путь вне `session_path`**;
- `curl` и `web` — если `output_path` вне `session_path` (для `web` также `action=download`).

Хелперы `path_within` / `allowed_in_session` (публичные) — единый источник политики «внутри сессии»: их же импортирует TUI-цикл (`textual_integration`), чтобы окно переключения и гейт не разъезжались. Относительные пути трактуются относительно `session_path`.
`dangerous_mode` прокидывается в `file_system` и `code_editor` (последний при
dangerous mode снимает ограничение корня). → `concepts/dangerous_mode.md`,
`entities/tools/file-system.md`, `entities/tools/code-editor.md`, `entities/tools/curl.md`

## Связи
- Регистрирует модули из `tools/*`.
- Вызывается из `botinok.py` и `textual_integration.py` в цикле tool-calls. → `concepts/function_calling.md`
