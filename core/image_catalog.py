"""Каталог изображений чата: хранение файлов и НЕПОВТОРЯЮЩИЕСЯ идентификаторы.

Идея (по требованию): в сессии/чате хранятся только идентификаторы вида
`[[image:<id>]]`, а сам файл лежит в каталоге проекта и подтягивается
рендером по мере прокрутки. Инструмент `image` берёт картинку из файла или по
URL, кладёт её в каталог проекта и возвращает идентификатор для вставки в чат.

Каталог:
  <session>/project/.botinok/images/<id>.<ext>
  <session>/project/.botinok/images/catalog.json

Идентификатор генерируется из `seq` (хранится в каталоге, НЕ сбрасывается при
удалении) + случайный суффикс и проверяется на уникальность, поэтому не может
повториться ни в этой сессии, ни после удаления записи.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlparse

from core.path_utils import resolve_session_path

CATALOG_VERSION = 1
IMAGES_SUBDIR = os.path.join(".botinok", "images")
CATALOG_NAME = "catalog.json"
FALLBACK_DIR = os.path.expanduser("~/.botinok/images")

MAX_BYTES = int(os.environ.get("BOTINOK_IMAGE_MAX_BYTES", str(25 * 1024 * 1024)))

_BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_EXT_BY_FORMAT = {
    "PNG": ".png", "JPEG": ".jpg", "JPG": ".jpg", "GIF": ".gif",
    "WEBP": ".webp", "BMP": ".bmp", "TIFF": ".tiff", "ICO": ".ico",
}
_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".tiff": "image/tiff", ".ico": "image/x-icon",
}


def catalog_dir(session_path: Optional[str] = None) -> str:
    """Папка каталога: в проекте сессии либо глобальный фолбэк."""
    if session_path:
        return os.path.join(os.path.realpath(session_path), "project", IMAGES_SUBDIR)
    return FALLBACK_DIR


def catalog_path(session_path: Optional[str] = None) -> str:
    return os.path.join(catalog_dir(session_path), CATALOG_NAME)


def _empty_state() -> dict:
    return {"version": CATALOG_VERSION, "next_seq": 1, "retired": [], "entries": {}}


def load_catalog(session_path: Optional[str] = None) -> dict:
    path = catalog_path(session_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "entries" not in data:
            raise ValueError("bad catalog")
        base = _empty_state()
        base.update(data)
        return base
    except FileNotFoundError:
        return _empty_state()
    except Exception:
        # Битый каталог не должен терять файлы: стартуем пустой индексацией.
        return _empty_state()


def _save_catalog(state: dict, session_path: Optional[str] = None) -> None:
    directory = catalog_dir(session_path)
    os.makedirs(directory, exist_ok=True)
    path = catalog_path(session_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def new_id(state: dict) -> str:
    """Уникальный (никогда не повторяется) идентификатор."""
    seq = int(state.get("next_seq", 1) or 1)
    entries = state.get("entries", {})
    retired = set(state.get("retired", []) or [])
    while True:
        candidate = f"img_{seq:06d}_{secrets.token_hex(3)}"
        if candidate not in entries and candidate not in retired:
            state["next_seq"] = seq + 1
            return candidate
        seq += 1


def _looks_like_url(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def _download(url: str, timeout: int = 30) -> bytes:
    import httpx
    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": _BROWSER_UA,
                              "Accept": "image/*,*/*;q=0.8"})
    resp.raise_for_status()
    data = resp.content
    if len(data) > MAX_BYTES:
        raise RuntimeError(f"image too large: {len(data)} > {MAX_BYTES} bytes")
    head = (data[:512] or b"").lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise RuntimeError("URL returned HTML, not an image")
    return data


def _probe(data: bytes) -> tuple[int, int, str]:
    """(width, height, format) через Pillow; ошибка если это не картинка."""
    from io import BytesIO
    from PIL import Image
    with Image.open(BytesIO(data)) as im:
        im.verify()
    with Image.open(BytesIO(data)) as im:
        w, h = im.size
        fmt = (im.format or "").upper()
    return w, h, fmt


def add_image(source: str, session_path: Optional[str] = None, alt: str = "",
              reuse: bool = True, timeout_sec: int = 30) -> dict:
    """Положить картинку из файла/URL в каталог проекта и вернуть запись с id."""
    if not source:
        raise ValueError("source is required (file path or URL)")
    source = source.strip()

    if _looks_like_url(source):
        data = _download(source, timeout_sec)
        origin = source
    else:
        path = source if os.path.isabs(source) else resolve_session_path(source, session_path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"image not found: {source}")
        data = open(path, "rb").read()
        if len(data) > MAX_BYTES:
            raise RuntimeError(f"image too large: {len(data)} > {MAX_BYTES} bytes")
        origin = os.path.realpath(path)

    width, height, fmt = _probe(data)
    sha256 = hashlib.sha256(data).hexdigest()

    state = load_catalog(session_path)

    if reuse:
        for entry in state.get("entries", {}).values():
            if entry.get("sha256") == sha256 and os.path.isfile(
                    os.path.join(catalog_dir(session_path), entry.get("file", ""))):
                return dict(entry, reused=True)

    image_id = new_id(state)
    ext = _EXT_BY_FORMAT.get(fmt) or os.path.splitext(urlparse(origin).path)[1] or ".png"
    filename = f"{image_id}{ext}"
    directory = catalog_dir(session_path)
    os.makedirs(directory, exist_ok=True)
    dest = os.path.join(directory, filename)
    with open(dest, "wb") as f:
        f.write(data)

    entry = {
        "id": image_id,
        "file": filename,
        "path": dest,
        "source": origin,
        "alt": alt or "",
        "sha256": sha256,
        "bytes": len(data),
        "width": width,
        "height": height,
        "mime": _MIME_BY_FORMAT(fmt, ext, data),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    state.setdefault("entries", {})[image_id] = entry
    _save_catalog(state, session_path)
    return dict(entry, reused=False)


def _MIME_BY_FORMAT(fmt: str, ext: str, data: bytes) -> str:
    if fmt:
        guess = mimetypes.guess_type("x" + ext)[0]
        if guess:
            return guess
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def get_entry(image_id: str, session_path: Optional[str] = None) -> Optional[dict]:
    if not image_id:
        return None
    return load_catalog(session_path).get("entries", {}).get(image_id)


def resolve_path(image_id: str, session_path: Optional[str] = None) -> Optional[str]:
    entry = get_entry(image_id, session_path)
    if not entry:
        # Попробуем глобальный фолбэк, если искали в сессии.
        if session_path:
            entry = get_entry(image_id, None)
        if not entry:
            return None
    path = entry.get("path") or os.path.join(catalog_dir(session_path), entry.get("file", ""))
    return path if path and os.path.isfile(path) else None


def list_entries(session_path: Optional[str] = None) -> list:
    entries = load_catalog(session_path).get("entries", {})
    return sorted(entries.values(), key=lambda e: e.get("created", ""))


def delete_entry(image_id: str, session_path: Optional[str] = None,
                 remove_file: bool = True) -> bool:
    """Удалить запись. Идентификатор уходит в retired и больше не выдаётся."""
    state = load_catalog(session_path)
    entry = state.get("entries", {}).pop(image_id, None)
    if not entry:
        return False
    state.setdefault("retired", [])
    if image_id not in state["retired"]:
        state["retired"].append(image_id)
    _save_catalog(state, session_path)
    if remove_file:
        try:
            os.remove(os.path.join(catalog_dir(session_path), entry.get("file", "")))
        except OSError:
            pass
    return True


def token_for(image_id: str, alt: str = "") -> str:
    return f"[[image:{image_id}|{alt}]]" if alt else f"[[image:{image_id}]]"
