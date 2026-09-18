---
type: entity
tags: [safety, tool]
updated: 2026-09-18
sources: 1
status: stable
---

# Safe ops — каталог безопасных операций

`tools/safe_ops.py` — единый реестр **read-only** возможностей, доступных без
dangerous mode, плюс подсказки безопасного эквивалента. → `concepts/dangerous_mode.md`

## Двухуровневая модель

- **Уровень A — безопасный каталог (везде):** read-only операции, без привязки к
  пути (та же граница доверия, что у `file_system read`).
- **Уровень B — внутри сессии:** любые **файловые мутации** без dangerous mode
  (см. `concepts/dangerous_mode.md`), с контейнментом.
- **Выполнение кода** (`shell_exec run`) — всегда dangerous; сессия не sandbox
  для процессов.

## Операции

| Группа | Операции |
|---|---|
| 📂 Файлы | `fs.base64`, `fs.file_type`, `fs.stat`, `fs.count`, `fs.hash` (algo), `fs.listing`, `fs.readlink`, `text.base64_decode` |
| 🖥 Система | `sys.uptime`, `sys.loadavg`, `sys.cpu`, `sys.mounts`, `proc.top`, `svc.list` |
| 🌐 Сеть | `net.interfaces`, `net.ports`, `net.dns` |
| 🧩 Разработка | `dev.which`, `git.status/log/diff/show/remote/branch/tag/ls_files/grep` |
| 🖼 Медиа | `image.meta` (Pillow) |

Вызов: `file_system action=inspect command=<операция> [path=…] [content_query=…] [algo=…]`.

## «Умный» харнес

- Справка `file_system action=help` — сгруппированный каталог с примерами.
- Прощающий ввод: алиасы (`base64`→`fs.base64`, `ports`→`net.ports`), регистр не важен.
- «Похоже, вы имели в виду»: `difflib`-подсказка на неизвестную команду.
- Совет/следующий шаг: `advice_for` (например, base64 → как отправить файл в API).
- При запрете `shell_exec run` `ToolManager` предлагает безопасный эквивалент из
  этого же реестра (`suggest_for_shell`).

## Безопасность

- argv без shell (`subprocess`, не `shell=True`), `LC_ALL=C` для стабильного вывода;
- лимит вывода (`max_bytes`) и таймаут; для `fs.base64` — отдельный лимит 20 МБ;
- только обычные файлы (без `/dev`, FIFO, сокетов).

## Связи
`entities/tools/file-system.md`, `entities/tool_manager.md`,
`concepts/dangerous_mode.md`, `tests/test_safe_ops.py`.
