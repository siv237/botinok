---
type: entity
tags: [tool, tui, image]
updated: 2026-09-20
sources: 3
status: stable
---

# image — показать изображение в чате

Инструмент `tools/image_show.py` (реестр: `image`). Не анализ, а **отображение**:
принимает картинку файлом или по URL, кладёт её в каталог проекта и возвращает
короткий идентификатор, который агент вставляет в текст ответа.

## Действия

| action | Что делает |
|--------|-----------|
| `show` (по умолчанию) | добавить картинку из `source` (путь или URL), вернуть `id` и `token` |
| `list` | что уже добавлено в сессии |
| `get` | запись по `id` |
| `help` | справка |

Пример ответа:

```json
{"ok": true, "id": "img_000003_a1b2c3", "token": "[[image:img_000003_a1b2c3|подпись]]",
 "width": 1100, "height": 822, "mime": "image/png"}
```

## Контракт с агентом

- Описание инструмента прямо сообщает: «вставь `token` в ответ — появится картинка».
- В сессии хранится **только идентификатор**, не файл (см.
  [concepts/image_rendering.md](../../concepts/image_rendering.md)).
- Повторная вставка того же файла возвращает тот же `id` (переиспользование по
  sha256), поэтому один файл = один id.
- Ошибки (нет файла, HTML вместо картинки, битая ссылка) возвращаются полем
  `ok: false` + `error`, без исключений наружу.

## Хранение

- Файлы: `<session>/project/.botinok/images/<id>.<ext>`
- Индекс: `<session>/project/.botinok/images/catalog.json`
- Без сессии — фолбэк `~/.botinok/images`.

## Связи

- [core/image_catalog.py](../../../core/image_catalog.py) — каталог и генерация
  неповторяющихся id.
- [core/image_refs.py](../../../core/image_refs.py) — разбор маркеров `[[image:id]]`.
- [vision](vision.md) — «что на картинке», а `image` — «показать картинку».
- [entities/textual_ui.md](../textual_ui.md) — рендер в чате и пейджере.
