---
type: entity
tags: [tool, system, safety]
updated: 2026-08-23
sources: 2
status: stable
---

# Инструмент file_system

`tools/file_system.py` → функция `file_system_tool(...)`. Самый богатый инструмент для работы с файловой системой.

## Действия
**Безопасные** (работают всегда):
`list` · `search` · `grep` · `read` · `info` · `inspect` · `find`
- Расширенный `find` с фильтрами (размер, время, тип), `_walk_files`, `_top_largest_files`.
- Чтение с лимитами (`_read_file`, `_read_text_with_limits`, offset/limit), `_tail_file`, `grep`/regex (`_grep_files`, `_grep_regex`).
- Системная инспекция: `_proc_list`, `_proc_info`, `_sys_meminfo`, `_sys_disk_free`, `_read_os_release`, `_fs_tree`.

**Опасные** (требуют dangerous mode + подтверждение вне сессии):
`delete` · `move` · `copy` · `mkdir` · `chmod` · `symlink` · `touch`
- Обёртки `_dangerous_action`, `_confirm_action`, `_parse_mode`, `_is_within_session`.

## Безопасность
Проверка пути на выход за пределы рабочей области; запрос подтверждения для мутирующих действий вне сессии; dangerous_mode прокидывается из `ToolManager`. → `concepts/dangerous_mode.md`, `entities/tool_manager.md`

## Связи
Зарегистрирован в `ToolManager._tool_registry` как `file_system`. Журнал вызовов — `tools.log` сессии. → `entities/session_directory.md`
