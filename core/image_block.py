"""Ленивый виджет изображения для чата (Textual).

Политика:
- картинка всегда занимает всю ширину контейнера, пропорции сохраняются;
- высота не ограничивается, контент скроллится;
- рисуется ТОЛЬКО ВИДИМЫЙ СРЕЗ строк, а сам источник на лету приводится к
  разрешению терминала и кэшируется, пока размер окна не изменился.

Схема (по требованию):
1. `prepare_scaled(source, width, total_rows)` — уменьшенная копия ровно под
   текущий размер терминала (≈2 px на клетку), кэшируется на диске по
   (файл, mtime, ширина, высота). Огромный файл декодируется один раз.
2. `render_image_band(scaled, width, rows, y0, y1)` — chafa рисует только
   видимую полосу уже уменьшенной копии; стоимость не зависит от размера
   исходной картинки.

В сессии хранятся только идентификаторы; файл берётся из каталога по id
(см. `core/image_catalog.py`, `core/image_refs.py`).
"""

from __future__ import annotations

import os
import threading
from typing import List, Optional

from textual.containers import Container
from textual.geometry import Region
from textual.widgets import Static

_QUANT = 4
_MARGIN_ROWS = 8   # запас строк выше/ниже видимой зоны


def image_aspect(path: str) -> Optional[float]:
    """Отношение высоты к ширине в пикселях (для резерва высоты), либо None."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        if w > 0 and h > 0:
            return h / w
    except Exception:
        pass
    return None


def nominal_rows(width: int, aspect: Optional[float]) -> int:
    """Сколько строк займёт картинка при данной ширине (секстанты: 2px/клетка)."""
    if width <= 0:
        return 1
    if not aspect:
        return max(1, width // 3)
    return max(1, int(round(width * aspect / 2)))


class ImageBlock(Container):
    """Картинка в чате: фиксированная высота + отрисовка видимого среза."""

    DEFAULT_CSS = """
    ImageBlock {
        width: 100%;
        height: auto;
        overflow: hidden hidden;
        margin: 0 0 1 0;
    }
    ImageBlock > .imgview {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, source: str, alt: str = "", max_height: int = 0,
                 name=None, id=None, classes=None) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.source = source
        self.alt = alt
        self.max_height = max_height
        self._aspect = image_aspect(source)
        # уменьшенная копия под текущий размер окна
        self._scaled_path: Optional[str] = None
        self._scaled_px: tuple = (0, 0)
        self._scaled_width: Optional[int] = None
        self._total_rows = 0
        # видимый срез
        self._slice_start: Optional[int] = None
        self._slice_rows = 0
        self._slice_token = 0
        # фоновые задачи
        self._token = 0
        self._busy = False
        self._pending_width: Optional[int] = None
        self._timer = None
        self._view = Static("", markup=False, classes="imgview")

    def compose(self):
        yield self._view

    # -- геометрия -----------------------------------------------------
    def _scroll_container(self):
        node = self.parent
        while node is not None:
            try:
                if getattr(node, "is_scrollable", False):
                    return node
            except Exception:
                pass
            node = node.parent
        return None

    def _viewport_region(self):
        """Видимое окно контейнера в виртуальных координатах (без лага регионов)."""
        c = self._scroll_container()
        try:
            if c is not None:
                viewport = c.scrollable_content_region.size
                return Region(int(c.scroll_x), int(c.scroll_y),
                              viewport.width, viewport.height)
            return Region(0, 0, self.screen.region.width, self.screen.region.height)
        except Exception:
            return None

    def _virtual_region(self) -> Optional[Region]:
        try:
            return self.virtual_region
        except Exception:
            return None

    def _target_width(self) -> int:
        vp = self._viewport_region()
        if vp is None:
            return 0
        return max(16, (vp.width - 1) // _QUANT * _QUANT)

    def is_in_viewport(self) -> bool:
        try:
            vr = self._virtual_region()
            if vr is None or vr.width <= 0 or vr.height <= 0:
                return False
            vp = self._viewport_region()
            return vp is None or vp.overlaps(vr)
        except Exception:
            return True

    def _rows_for_width(self, width: int) -> int:
        rows = nominal_rows(width, self._aspect)
        if self.max_height > 0:
            rows = min(rows, self.max_height)
        return max(1, rows)

    def _set_placeholder(self) -> None:
        width = self._target_width() or 40
        rows = self._total_rows or self._rows_for_width(width)
        try:
            self.styles.height = rows
            label = os.path.basename(self.source)
            if self.alt:
                label = f"{self.alt} ({label})"
            self._view.styles.height = 1
            self._view.styles.offset = (0, 0)
            from rich.text import Text
            self._view.update(Text(f"  {label}  ", style="dim"))
        except Exception:
            pass

    def _visible_range(self):
        """(start, end) видимых строк виджета с запасом, либо None."""
        try:
            vr = self._virtual_region()
            vp = self._viewport_region()
            if vp is None or vr is None or vr.width <= 0:
                return None
            top = max(0, vp.y - vr.y - _MARGIN_ROWS)
            bottom = min(vr.height, vp.y + vp.height - vr.y + _MARGIN_ROWS)
            if bottom <= top:
                return None
            top = (top // _MARGIN_ROWS) * _MARGIN_ROWS
            return top, max(top + 1, bottom)
        except Exception:
            return None

    # -- жизненный цикл -------------------------------------------------
    def on_mount(self) -> None:
        self._set_placeholder()
        self.refresh_visibility()

    def on_resize(self, event) -> None:
        self._schedule()

    def _schedule(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
        self._timer = self.set_timer(0.05, self.refresh_visibility)

    def refresh_visibility(self) -> None:
        """Подготовить копию/полосу, если блок виден (идемпотентно)."""
        self._timer = None
        if not self.is_mounted:
            return
        if not self.is_in_viewport():
            return
        width = self._target_width()
        if width <= 0:
            return
        if width != self._scaled_width or not self._scaled_path:
            self._request_prepare(width)
            return
        self._render_slice()

    # -- шаг 1: уменьшенная копия под размер окна (в фоне) ---------------
    def _request_prepare(self, width: int) -> None:
        if self._busy:
            self._pending_width = width
            return
        self._busy = True
        self._token += 1
        token = self._token
        source = self.source
        rows = self._rows_for_width(width)

        def worker() -> None:
            try:
                from core.image_render import prepare_scaled
                result = prepare_scaled(source, width, rows)
            except Exception:
                result = None
            try:
                self.app.call_from_thread(self._apply_prepare, token, width, rows, result)
            except Exception:
                self._busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _apply_prepare(self, token: int, width: int, rows: int, result) -> None:
        if token != self._token:
            return
        self._busy = False
        try:
            mounted = self.is_mounted
        except Exception:
            mounted = False
        if result and mounted:
            path, tw, th = result
            self._scaled_path = path
            self._scaled_px = (tw, th)
            self._scaled_width = width
            self._total_rows = rows
            self._slice_start = None
            try:
                self.styles.height = rows
            except Exception:
                pass
            self._render_slice(force=True)
        else:
            self._set_placeholder()
        pending = self._pending_width
        self._pending_width = None
        if pending and pending != self._scaled_width:
            self._request_prepare(pending)

    # -- шаг 2: chafa только по видимой полосе (в фоне) ------------------
    def _render_slice(self, force: bool = False) -> None:
        if not self._scaled_path:
            self._set_placeholder()
            return
        rng = self._visible_range()
        if rng is None:
            return
        start, end = rng
        end = min(end, self._total_rows)
        if not force and start == self._slice_start:
            return
        self._slice_start = start
        rows = max(1, end - start)
        tw, th = self._scaled_px
        y0 = int(th * start / self._total_rows) if self._total_rows else 0
        y1 = int(th * end / self._total_rows) if self._total_rows else th
        y1 = max(y0 + 1, min(th, y1))
        self._slice_token += 1
        token = self._slice_token
        scaled = self._scaled_path
        width = self._scaled_width or self._target_width()

        def worker() -> None:
            try:
                from core.image_render import render_image_band
                ansi = render_image_band(scaled, width, rows, y0, y1)
            except Exception:
                ansi = None
            try:
                parsed = None
                if ansi:
                    from rich.text import Text
                    parsed = Text.from_ansi(ansi)
            except Exception:
                parsed = None
            try:
                self.app.call_from_thread(self._apply_slice, token, start, rows, parsed)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply_slice(self, token: int, start: int, rows: int, text) -> None:
        if token != self._slice_token or text is None:
            return
        if start != self._slice_start:
            return
        try:
            if not self.is_mounted:
                return
            self._slice_rows = rows
            self._view.styles.height = rows
            self._view.styles.offset = (0, start)
            self._view.update(text)
        except Exception:
            pass

    # -- диагностика/освобождение ---------------------------------------
    def visible_rows(self) -> int:
        return self._slice_rows

    def total_rows(self) -> int:
        return self._total_rows

    def release(self) -> None:
        """Сбросить нарисованный срез (например, ушёл далеко за экран)."""
        self._slice_start = None
        self._set_placeholder()


def refresh_visible_images(container) -> int:
    """Подтянуть видимые ImageBlock внутри контейнера (вызывать на скролле/ресайзе)."""
    count = 0
    try:
        blocks = container.query(ImageBlock)
    except Exception:
        return 0
    for block in blocks:
        try:
            if block.is_in_viewport():
                count += 1
                block.refresh_visibility()
        except Exception:
            pass
    return count
