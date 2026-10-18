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
- `verify(entry, deep=False)` — проверка целостности. По умолчанию **быстрая**:
  наличие, непустой каталог, размер против записанного `total`; sha256 не
  пересчитывается. `deep=True` — сверка sha256 **потоком** (`sha256_file`,
  чанки по 1 МиБ — раньше файл читался целиком в память, что на моделях в
  гигабайты было опасно), результат кэшируется в записи
  (`verified_size`/`verified_mtime_ns`) и повторно файл не хешируется.
  `record(status="completed")` помечает свежую загрузку проверенной сразу.
- `pending(session_path, deep=False)` — загрузки, которые нужно проверить/докачать.

## Роль
`web action=download` пишет сюда результат, `web action=downloads` читает и
проверяет (тип через `file`; хеш — только по запросу `verify=true`),
предлагает `resume=true` для незавершённых.

### Почему быстрая проверка по умолчанию (регрессия 2026-10-18)
`downloads` пересчитывал sha256 **каждого** файла истории: на живой истории это
29–31 ГБ (модели по 5–9 ГБ), и вызов висел минутами, а файлы читались целиком в
память. Теперь по умолчанию — проверка наличия и размера, глубокая сверка
включается `verify=true` (потоково, с кэшем).
→ `concepts/web_kit.md`
