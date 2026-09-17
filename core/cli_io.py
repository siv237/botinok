"""
Вывод в консоль без Rich API (для CLI-веток, мастера и headless-режимов).

Старый Rich-UI удалён; здесь остаётся простой print со снятием rich-разметки,
чтобы не тянуть Rich в код вне Textual. Textual использует Rich внутри себя —
это его внутренняя деталь.
"""

from __future__ import annotations

import re
import shutil

_MARKUP = re.compile(r"\[/?[a-zA-Z][^\]]*\]")


def strip_markup(text: str) -> str:
    """Убрать rich-разметку вида [bold cyan]...[/bold cyan]."""
    return _MARKUP.sub("", str(text))


def out(text: object = "") -> None:
    """Печать строки без rich-разметки."""
    print(strip_markup(str(text)))


def term_width(default: int = 80) -> int:
    """Ширина терминала (для разделителей)."""
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default
