"""Идентификаторы изображений в тексте чата: разбор и разрешение в файл.

В сессии хранятся только маркеры вида `[[image:<id>]]` / `[[image:<id>|alt]]`.
Рендер чата режет текст по маркерам и превращает каждый в изображение, беря
файл из каталога по id (см. `core/image_catalog.py`).
"""

from __future__ import annotations

import re
from typing import List, Optional

# id: буквы/цифры/подчёркивания/дефис; alt — необязательный, до закрывающих ]]
TOKEN_RE = re.compile(r"\[\[image:([A-Za-z0-9_\-]+)(?:\|([^\]\n]*))?\]\]")


def has_images(text: str) -> bool:
    return bool(text and TOKEN_RE.search(text))


def token(image_id: str, alt: str = "") -> str:
    return f"[[image:{image_id}|{alt}]]" if alt else f"[[image:{image_id}]]"


def find_tokens(text: str) -> List[dict]:
    """Все маркеры: [{id, alt, start, end, raw}]."""
    result = []
    for m in TOKEN_RE.finditer(text or ""):
        result.append({
            "id": m.group(1),
            "alt": (m.group(2) or "").strip(),
            "start": m.start(),
            "end": m.end(),
            "raw": m.group(0),
        })
    return result


def split_segments(text: str) -> List[dict]:
    """Разбить текст на сегменты: {"type": "text"|"image", ...}."""
    text = text or ""
    segments: List[dict] = []
    pos = 0
    for m in TOKEN_RE.finditer(text):
        if m.start() > pos:
            segments.append({"type": "text", "text": text[pos:m.start()]})
        segments.append({"type": "image", "id": m.group(1),
                         "alt": (m.group(2) or "").strip()})
        pos = m.end()
    if pos < len(text):
        segments.append({"type": "text", "text": text[pos:]})
    if not segments:
        segments.append({"type": "text", "text": text})
    return segments


def strip_tokens(text: str) -> str:
    """Текст без маркеров (например, для поиска/превью)."""
    return TOKEN_RE.sub("", text or "")


def resolve(image_id: str, session_path: Optional[str] = None) -> Optional[str]:
    """Путь к файлу картинки по идентификатору, либо None."""
    try:
        from core.image_catalog import resolve_path
        return resolve_path(image_id, session_path)
    except Exception:
        return None
