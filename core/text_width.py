"""
Нормализация ширины символов для стабильного рендера в терминале.

Причина «сдвига панелей» на строках с необычными символами: Textual/Rich считают
ширину ячейки по своей wcwidth (с отдельной обработкой вариационных селекторов
VS15/VS16, ZWJ и табов), а реальный терминал может рендерить те же символы иначе.
На такой строке курсор уезжает на 1..N ячеек, и соседние панели/границы визуально
сдвигаются, оставляя чёрные «дыры».

Здесь текст приводится к предсказуемой ширине:
  * табы раскрываются в пробелы;
  * убираются вариационные селекторы (U+FE0E/U+FE0F), ZWJ (U+200D) и прочие
    zero-width/формат-символы, из-за которых ширина зависит от спец-обработки;
  * отбрасываются непечатаемые контролы.

Плюс хелперы обрезки по ширине ячейки (а не по числу символов).
"""

from __future__ import annotations

import re
from typing import Iterable

from rich.cells import cell_len

_ZERO_WIDTH = dict.fromkeys([
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F,  # zero-width space/joiners/marks
    0x2060, 0x2061, 0x2062, 0x2063, 0x2064,  # word joiner / invisible operators
    0xFE0E, 0xFE0F,  # variation selectors 15/16
    0xFEFF,          # BOM / zero-width no-break space
])

_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]')


def normalize_cells(text, tab: int = 4) -> str:
    """Привести текст к предсказуемой терминальной ширине."""
    if text is None:
        return ""
    s = str(text)
    if "\t" in s:
        s = s.expandtabs(tab)
    s = s.translate(_ZERO_WIDTH)
    return _CONTROL_RE.sub("", s)


def cell_width(text) -> int:
    """Ширина строки в терминальных ячейках."""
    return cell_len(normalize_cells(text))


def cell_truncate(text, max_cells: int, ellipsis: str = "…") -> str:
    """Обрезать строку до max_cells по ширине ячейки, добавив ellipsis."""
    s = normalize_cells(text)
    if max_cells <= 0:
        return ""
    if cell_len(s) <= max_cells:
        return s
    budget = max_cells - cell_len(ellipsis)
    if budget <= 0:
        return ellipsis[:max_cells]
    out: list[str] = []
    used = 0
    for ch in s:
        w = cell_len(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out) + ellipsis


def cell_pad(text, cells: int, fill: str = " ") -> str:
    """Дополнить строку справа до cells по ширине ячейки."""
    s = normalize_cells(text)
    diff = cells - cell_len(s)
    if diff <= 0:
        return s
    return s + fill * diff
