---
type: concept
tags: [llm]
updated: 2026-10-10
sources: 3
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

## Модель исполнения (подробно, актуально на 2026-10-10)

### Где живёт цикл
- Основной агентный цикл — `core/textual_integration.py::_stream_turn` (запускается daemon-тредом из `textual_app`, см. `Thread(target=_stream_turn, …)` в `textual_integration.py:2292`).
- Упрощённый CLI-цикл — `botinok.py:734` (тот же принцип, без TUI).

### Как собираются tool_calls
- Модель стримит; в цикле чтения чанков (`textual_integration.py:1528`) накапливается список `tool_calls` (`msg["tool_calls"].extend(...)`).
- Адаптер OpenAI-совместимого стрима (`core/openai_compat.py::iter_lines`, `tool_calls_acc` по `index`) склеивает дельты в список tool_calls. **Несколько вызовов за один ответ уже поддерживаются протоколом.**

### Как исполняются — СТРОГО ПОСЛЕДОВАТЕЛЬНО
- Блок `for tc in tool_calls:` (`textual_integration.py:1857`) идёт **последовательно**, один за другим. Нет ни пула, ни асинхронщины, ни батча.
- На каждой итерации:
  1. Проверка `app._stop_requested` (Esc) — если стоп, остаток tool_calls гасится aborted-результатами.
  2. Парсинг аргументов (`json.loads`).
  3. `_add_tool(... status="running")` в панель UI.
  4. `sm.log_tool_call(... "STARTED")`.
  5. Для web-тулзов ставится `progress_callback = _tool_progress(tool_name)`.
  6. Dangerous-gate: `is_dangerous_tool` → `show_confirmation_prompt` + `app._confirmation_event.wait()` (**блокирует поток до ответа человека**, timeout 300с).
  7. `_catalog_memo_check` (кэш для skills/experience list).
  8. **`tm.call_tool(...)` — синхронный блокирующий вызов** (`textual_integration.py:1979`). Пока тулз не вернётся, цикл стоит.
  9. Артефакт, `_compact_tool_message`, `messages.append({role:"tool"...})`, `sm.update_context`, `_update_tool(completed)`.
- Цикл повторяется (следующий раунд модели) до финального ответа без tool_calls.

### Что делает web-тулз синхронным
- `tools/web.py::execute` → `_go` → `_fetch` использует **`httpx.Client` (синхронный)** (`web.py:314`); загрузка — `subprocess`/aria2c (`_run`) или `_httpx_download`. Всё блокирует тред цикла до конца запроса/таймаута.
- Внутри одного `execute` уже есть микро-распараллеливание для `action=images` (проверка нескольких картинок), но сам вызов для агента — один блокирующий.

### Прототип «фонового» поведения уже есть — shell_exec
- `shell_exec action=run` запускает PTY-сессию (`ShellSession`) и **сразу возвращает `session_id`** со `status:"running"`, не держая агента (`shell_exec.py:208`). Дальше агент опрашивает `action=status/read/search/wait/kill`.
- Реестр фоновых сессий — `ShellSessionRegistry.instance()` (синглтон, `cleanup_dead()`).
- **Это готовый шаблон** для параллельных/фоновых веб-задач.

### Точки для реализации параллельности/фоновости веб-тулзов
1. **Батч-параллельность в цикле:** группировать соседние web-тулзы (`web/web_search/open_url/web_extract/curl`) в `tool_calls` и исполнять через `ThreadPoolExecutor`, сохраняя порядок `tool`-сообщений (OpenAI требует tool_call_id ↔ tool по порядку). Dangerous-gate и Esc-стоп обрабатывать до запуска батча.
2. **Фоновость по образцу shell_exec:** реестр `WebJobRegistry` + `web action=… background=true` возвращает `job_id` сразу; `action=job_status/job_read/job_kill` для опроса. Годится для долгих download/множественных search.
3. `httpx` имеет `AsyncClient`/`httpx.AsyncClient` c `gather` — альтернатива потокам для чистого I/O-батча.
4. Прогресс: сейчас один `progress_callback` на тулз; для батча нужен `detail` на каждую карточку (`update_tool_detail` ищет **последнюю** по имени — параллельные одноимённые тулзы будут перетирать друг друга в UI).

## Связи
Список инструментов — `overview.md`. Реестр — `entities/tool_manager.md`. Веб-кит — `concepts/web_kit.md`. Фоновые shell-сессии — `entities/shell_session.md`. Прерывание процессов — `entities/process_control.md`.
