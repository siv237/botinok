---
type: entity
tags: [tool]
updated: 2026-10-18
sources: 4
status: stable
---

# ToolManager

`core/tool_manager.py` — класс `ToolManager`. Реестр, описания и **lazy-загрузка** всех инструментов (function calling). Набор инструментов — плагинный: реестр и схемы собираются сканированием папок `tools/` (`core/tool_discovery.py`), рукописных таблиц в ядре нет. → `concepts/tool_plugins.md`

## Как работает
- **Реестр** `_tool_registry`: имя инструмента → `(module, function)`. Собирается `_sync_discovery()` из папок `tools/<folder>/tool.json` (+ алиасы). Единый веб-добыватель `web` + legacy-обёртки `web_search`/`open_url`/`web_extract`/`curl` и алиас `web_extractor` (подробно в `entities/tools/`).
- **Lazy-загрузка** `_load_tool(name)`: реализация плагина импортируется только при первом обращении (`ToolSpec.entry_func()`). Сломанные (SyntaxError/прочие исключения) фиксируются в `broken_tools` и логируются (`~/.botinok/logs/tools.log`).
- **Описания** `_descriptions`: JSON Schema в OpenAI-формате (`type: function`) из манифестов — напрямую отдаются модели как `tools`.
- **Подключение/отключение на лету**: `_refresh_if_stale()` сверяет штамп содержимого папки перед сборкой payload и вызовом, `rediscover()` пересобирает реестр и сбрасывает закэшированные вызовы. Удалили папку — инструмента нет в payload/каталоге/вызовах; положили — появился, без перезапуска.
- **Данжер-режим**: `dangerous_mode` берётся из env `BOTINOK_DANGEROUS=1` (или переключается в TUI командой `/dangerous`). → `concepts/dangerous_mode.md`
- **Гейт опасных действий** (`call_tool`, простой режим): работает по классам опасности из манифеста плагина (`danger`: `shell` / `session_write` / `session_output`) — `shell_exec` (опасные action) запрещён; мутации `code_editor`/`file_system` и запись `curl`/`web` разрешены только **внутри** `session_path`, иначе — ошибка с намёком, что пользователь может разрешить переключение. Сторонний плагин с объявленным `danger` гейтится так же; таблица встроенных имён осталась лишь страховкой при недоступном сканировании.

## Ключевые методы
- `get_tool(name)`, `get_all_tools()`, `call_tool(name, args, session_path, progress_callback)` — выполнение; контекст подставляется строго по контракту плагина (`provides` ∩ сигнатура): `session_path`, `progress_callback`, `dangerous_mode`.
- `call_tool` принимает `args` как dict или JSON-строку; даёт понятные ошибки для неизвестного/сломанного инструмента; неизвестное имя → `rediscover()` (папку могли положить в этом же ходе).
- `get_all_descriptions()` / `get_tool_definitions()` — определения для модели, включая пометку сломанных.
- `rediscover()` — пересканировать папку инструментов (подключить/отключить плагины).
- `get_broken_tools_info()` — человекочитаемый свод о сломанных инструментах для агента (в т.ч. папки, нарушившие контракт: `PluginContractError`).

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
- Регистрирует плагины из `tools/<folder>/` (манифест `tool.json`). → `concepts/tool_plugins.md`
- Вызывается из `botinok.py` и `textual_integration.py` в цикле tool-calls. → `concepts/function_calling.md`
