"""Чтение первичного выделения (primary selection).

Средняя кнопка мыши в терминале вставляет primary selection. Когда приложение
включает mouse-tracking (Textual делает это всегда, ради прокрутки/кликов),
терминал перестаёт вставлять сам и присылает событие мыши, поэтому вставку
нужно реализовать на нашей стороне (как это делает opencode, не удерживая
mouse-tracking постоянно).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import List


def read_primary_selection(timeout: float = 3.0) -> str:
    """Вернуть текст primary selection или пустую строку.

    Инструменты пробуем по доступности: Wayland (`wl-paste`), X11
    (`xclip`/`xsel`). Нет инструментов/ошибка — пустая строка.
    """
    candidates: List[List[str]] = []
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        candidates.append(["wl-paste", "--primary"])
    if shutil.which("xclip"):
        candidates.append(["xclip", "-selection", "primary", "-o"])
    if shutil.which("xsel"):
        candidates.append(["xsel", "--primary", "--output"])

    for cmd in candidates:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except Exception:
            continue
        if result.returncode == 0:
            text = result.stdout.decode("utf-8", "replace")
            if text:
                return text
    return ""
