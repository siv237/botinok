---
type: entity
tags: [tool, system, safety]
updated: 2026-09-18
sources: 3
status: stable
---

# Инструмент file_system

`tools/file_system.py` → функция `file_system_tool(...)`. Самый богатый инструмент для работы с файловой системой.

## Действия
**Безопасные** (работают всегда):
`list` · `search` · `grep` · `read` · `info` · `inspect` · `find`
- **`grep`** — поиск по содержимому, `content_query` трактуется как **regex**
  (регистронезависимо; при некорректном regex — fallback на текст). `path` может
  быть **файлом или каталогом**; `pattern` — маска имён (по умолчанию `*`);
  `recursive` — по подкаталогам. Прощающий ввод: если `content_query` пуст,
  запросом становится `pattern`. Вывод с числом совпадений и подсказкой.
- **`search`** — поиск по маске имени (`pattern`); если задан `content_query`,
  ищет по содержимому (тот же grep).
- Расширенный `find` с фильтрами (размер, время, тип), `_walk_files`, `_top_largest_files`.
- Чтение с лимитами (`_read_file`, `_read_text_with_limits`, offset/limit), `_tail_file`.
- Системная инспекция: `_proc_list`, `_proc_info`, `_sys_meminfo`, `_sys_disk_free`, `_read_os_release`, `_fs_tree`.
- `inspect command=grep.contains` — литеральный поиск; `grep.regex` — по regex.

**Опасные** (в простом режиме — только внутри папки сессии; вне — dangerous mode):
`delete` · `move` · `copy` · `mkdir` · `chmod` · `symlink` · `touch`
- Обёртки `_dangerous_action`, `_confirm_action`, `_parse_mode`, `_is_within_session`.
- `_dangerous_action` разрешает мутацию без dangerous mode, если `path` (и `dest`
  для `move`/`copy`/`symlink`) внутри `session_path`; иначе — ошибка.

## Безопасный каталог (read-only)
`action=help` — сгруппированный каталог безопасных операций с примерами.
`action=inspect` поддерживает расширенный набор (`fs.base64`, `fs.file_type`,
`fs.stat`, `fs.count`, `fs.hash`, `fs.listing`, `fs.readlink`, `sys.*`, `proc.top`,
`svc.list`, `net.*`, `git.*`, `image.meta`, `text.base64_decode`) — единый источник
`tools/safe_ops.py`. Прощающий ввод (алиасы), «похоже, вы имели в виду», совет.
→ `entities/safe_ops.md`

## Безопасность
Проверка пути на выход за пределы сессии (`_is_within_session`); мутации внутри
сессии разрешены без dangerous mode; вне — гейт в `ToolManager.call_tool` и
запрос переключения/подтверждения в TUI. Относительные `path`/`dest`
резолвятся в `<session>/project/` через `core.path_utils.resolve_session_path`
(ведущий `project/` не дублируется); гейт `allowed_in_session` использует тот же
резолвер. → `concepts/dangerous_mode.md`, `entities/tool_manager.md`

## Связи
Зарегистрирован в `ToolManager._tool_registry` как `file_system`. Журнал вызовов — `tools.log` сессии. → `entities/session_directory.md`
