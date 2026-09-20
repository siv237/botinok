"""Ленивый виджет изображения для чата (Textual).

Политика:
- картинка всегда занимает всю ширину контейнера, пропорции сохраняются;
- высота не ограничивается, контент скроллится;
- разбирается и рисуется ТОЛЬКО ВИДИМЫЙ СРЕЗ строк (по скроллу), а не вся
  картинка целиком.

Почему так: Textual рисует `Static` целиком, и один гигантский Static на 4К
(ширина ~400 клеток, высота сотни строк) блокирует UI на сотни миллисекунд.
Здесь контейнер держит ФИКСИРОВАННУЮ высоту (=высота картинки) и геометрию
скролла, а единственный дочерний вью смещён (`offset`) на начало видимого
среза и содержит только его. Стоимость раскладки и парсинга пропорциональна
экрану, а не размеру картинки — поэтому на 4К всё летает.

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
        self._ansi_lines: List[str] = []
        self._rendered_width: Optional[int] = None
        self._slice_start: Optional[int] = None
        self._slice_rows = 0
        self._slice_token = 0
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
        """Видимое окно контейнера — в ВИРТУАЛЬНЫХ координатах (без лага
        экранных регионов): (scroll_x, scroll_y, ширина, высота)."""
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

    def _reserve_height(self, width: int) -> int:
        rows = nominal_rows(width, self._aspect)
        if self.max_height > 0:
            rows = min(rows, self.max_height)
        return max(1, rows)

    def _set_placeholder(self) -> None:
        width = self._target_width() or 40
        rows = len(self._ansi_lines) or self._reserve_height(width)
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
            # Квантуем начало, чтобы мелкий скролл не пересобирал срез.
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
        """Подтянуть картинку/срез, если блок виден (идемпотентно)."""
        self._timer = None
        if not self.is_mounted:
            return
        if not self.is_in_viewport():
            return
        width = self._target_width()
        if width <= 0:
            return
        if width != self._rendered_width:
            self._request_full(width)
            return
        self._render_slice()

    # -- полный рендер (в фоне) ----------------------------------------
    def _request_full(self, width: int) -> None:
        if self._busy:
            self._pending_width = width
            return
        self._busy = True
        self._token += 1
        token = self._token
        source = self.source
        max_height = self.max_height

        def worker() -> None:
            try:
                from core.image_render import render_image_ansi
                ansi = render_image_ansi(source, width, max_height=max_height)
            except Exception:
                ansi = None
            try:
                self.app.call_from_thread(self._apply_full, token, width, ansi)
            except Exception:
                self._busy = False

        threading.Thread(target=worker, daemon=True).start()

    def _apply_full(self, token: int, width: int, ansi) -> None:
        if token != self._token:
            return
        self._busy = False
        try:
            mounted = self.is_mounted
        except Exception:
            mounted = False
        if ansi and mounted:
            self._ansi_lines = ansi.split("\n")
            self._rendered_width = width
            self._slice_start = None
            try:
                self.styles.height = max(1, len(self._ansi_lines))
            except Exception:
                pass
            self._render_slice(force=True)
        else:
            self._set_placeholder()
        pending = self._pending_width
        self._pending_width = None
        if pending and pending != self._rendered_width:
            self._request_full(pending)

    # -- отрисовка видимого среза (в фоне) ------------------------------
    def _render_slice(self, force: bool = False) -> None:
        if not self._ansi_lines:
            self._set_placeholder()
            return
        rng = self._visible_range()
        if rng is None:
            return
        start, end = rng
        end = min(end, len(self._ansi_lines))
        if not force and start == self._slice_start:
            return
        self._slice_start = start
        lines = self._ansi_lines[start:end]
        self._slice_token += 1
        token = self._slice_token

        def worker() -> None:
            try:
                from rich.text import Text
                parsed = Text.from_ansi("\n".join(lines))
            except Exception:
                parsed = None
            try:
                self.app.call_from_thread(self._apply_slice, token, start, end, parsed)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply_slice(self, token: int, start: int, end: int, text) -> None:
        if token != self._slice_token or text is None:
            return
        if start != self._slice_start:
            return
        try:
            if not self.is_mounted:
                return
            self._slice_rows = max(1, end - start)
            self._view.styles.height = self._slice_rows
            self._view.styles.offset = (0, start)
            self._view.update(text)
        except Exception:
            pass

    def visible_rows(self) -> int:
        """Сколько строк реально разобрано/нарисовано сейчас (для тестов/диагностики)."""
        return self._slice_rows

    def total_rows(self) -> int:
        """Полная высота картинки в строках (0, пока не отрендерена)."""
        return len(self._ansi_lines)

    def release(self) -> None:
        """Сбросить разобранное (например, ушёл далеко за экран)."""
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
