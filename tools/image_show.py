#!/usr/bin/env python3
"""
image — показать изображение в чате.

Инструмент сообщает агенту, что тот умеет показывать картинки: можно дать
изображение файлом или ссылкой, инструмент кладёт его в каталог проекта и
возвращает КОРОТКИЙ идентификатор. Чтобы картинка появилась в ответе, вставь
этот идентификатор в текст ответа — рендер чата сам превратит его в картинку
по мере прокрутки.

В сессии сохраняется только идентификатор, а не само изображение.

Действия:
  show (по умолчанию) — добавить картинку (source: путь к файлу или URL)
  list                — что уже добавлено в этой сессии
  get                 — запись по идентификатору
  help                — справка

Пример:
  image(source="/path/photo.png", alt="Схема")
  image(source="https://site.com/plot.png")
  → {"id": "img_000003_a1b2c3", "token": "[[image:img_000003_a1b2c3]]", ...}
"""

from typing import Optional

from core import image_catalog
from core import image_refs


HELP = """🖼 image — показать изображение в чате

Действия:
  image(source="/path/file.png")            добавить файл
  image(source="https://site/img.png")      скачать по ссылке
  image(source=..., alt="подпись")          добавить с подписью
  image(action="list")                      список картинок сессии
  image(action="get", id="img_...")         запись по id
  image(action="help")                      эта справка

Как показать в чате: вставь полученный `token` (вида [[image:img_...]])
в текст ответа — рендер превратит его в картинку. В сессии хранится только
идентификатор; файл лежит в каталоге проекта и подтягивается лениво."""


def image(
    action: str = "show",
    source: Optional[str] = None,
    path: Optional[str] = None,
    url: Optional[str] = None,
    alt: str = "",
    id: Optional[str] = None,
    limit: int = 50,
    session_path: Optional[str] = None,
) -> dict:
    """Показать/каталогизировать изображение. См. HELP."""
    act = (action or "show").strip().lower()

    if act in ("help", "?", "справка"):
        return {"ok": True, "help": HELP, "actions": ["show", "list", "get", "help"]}

    if act in ("list", "ls"):
        entries = image_catalog.list_entries(session_path)
        items = []
        for e in entries[-max(1, int(limit or 50)):]:
            items.append({
                "id": e.get("id"),
                "token": image_refs.token(e.get("id", ""), e.get("alt", "")),
                "source": e.get("source"),
                "size": f"{e.get('width')}x{e.get('height')}",
                "bytes": e.get("bytes"),
                "created": e.get("created"),
            })
        return {"ok": True, "count": len(entries), "images": items,
                "catalog": image_catalog.catalog_path(session_path),
                "next_steps": "Вставь token нужной картинки в ответ, чтобы показать её."}

    if act in ("get", "info"):
        entry = image_catalog.get_entry(id or "", session_path)
        if not entry:
            return {"ok": False, "error": f"image not found: {id}",
                    "next_steps": "image(action=\"list\") — посмотреть доступные."}
        return {"ok": True, "image": entry,
                "token": image_refs.token(entry.get("id", ""), entry.get("alt", ""))}

    if act not in ("show", "add"):
        return {"ok": False, "error": f"unknown action: {action}",
                "available": ["show", "list", "get", "help"]}

    src = source or path or url
    if not src:
        return {"ok": False, "error": "source is required (file path or URL)",
                "next_steps": "image(source=\"/path/img.png\") или image(source=\"https://…/img.png\")"}

    try:
        entry = image_catalog.add_image(src, session_path=session_path, alt=alt)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e),
                "next_steps": "Проверь путь (относительный ищется в project/ сессии)."}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    token = image_refs.token(entry.get("id", ""), entry.get("alt", ""))
    return {
        "ok": True,
        "id": entry.get("id"),
        "token": token,
        "reused": entry.get("reused", False),
        "width": entry.get("width"),
        "height": entry.get("height"),
        "bytes": entry.get("bytes"),
        "mime": entry.get("mime"),
        "source": entry.get("source"),
        "catalog": image_catalog.catalog_dir(session_path),
        "message": (f"Изображение добавлено. Вставь {token} в текст ответа — "
                    f"оно появится в чате по мере прокрутки."),
        "next_steps": "Вставляй token как есть; повторный show того же файла вернёт тот же id.",
    }


if __name__ == "__main__":
    import json
    import sys
    kwargs = {}
    for arg in sys.argv[1:]:
        k, _, v = arg.partition("=")
        kwargs[k] = v
    print(json.dumps(image(**kwargs), ensure_ascii=False, indent=2))
