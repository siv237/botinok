---
type: entity
tags: [tool, network]
updated: 2026-09-18
sources: 2
status: stable
---

# Менеджер загрузок (download_manager)

`tools/download_manager.py` — учёт скачанных файлов для инструмента `web`
(`entities/tools/web.md`). Не зависит от сессий: история **глобальная**, чтобы
новая сессия могла просто спросить у `web`, нет ли уже нужного файла.

## Хранилище
`~/.botinok/downloads/history.json` (переопределяется env
`BOTINOK_DOWNLOAD_HISTORY`). По каждой загрузке (ключ `url + dest`): `url`,
`dest`, `status` (`in_progress`/`completed`/`incomplete`/`error`), `total`,
`sha256`, `type`, `engine` (`aria2c`/`httpx`), `session`, `error`, `created`,
`updated`.

## API
- `record(...)` — записать/обновить запись.
- `find(url, dest)` / `list_entries()` — найти/перечислить.
- `verify(entry)` → `(ok, причина)`: наличие, размер, sha256; каталог торрента —
  непустота.
- `pending()` — загрузки, которые нужно проверить/докачать.

## Роль
`web action=download` пишет сюда результат, `web action=downloads` читает и
проверяет (тип через `file`, хеш), предлагает `resume=true` для незавершённых.
→ `concepts/web_kit.md`
