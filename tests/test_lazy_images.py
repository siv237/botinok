#!/usr/bin/env python3
"""Ленивая отрисовка множества картинок в чате на 4К-разрешении.

Сценарий: в истории десятки высоких изображений, окно 4К (400x110 клеток).
Требования: при изменении размера НЕ перерисовывать все; рисовать только
видимые блоки; у высоких картинок разбирать только ВИДИМЫЙ СРЕЗ (иначе
гигантский Static вешает UI). Всё должно «летать».

Запуск: venv/bin/python -u tests/test_lazy_images.py
"""

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.app import App  # noqa: E402
from textual.containers import VerticalScroll  # noqa: E402

import core.image_render as ir  # noqa: E402
from core.image_block import ImageBlock, refresh_visible_images  # noqa: E402
from PIL import Image  # noqa: E402

N_IMAGES = 60
IMG_W, IMG_H = 200, 800          # высокие: aspect 4 → ~800 строк при ширине 400
VIEW = (400, 110)                # 4К-подобное окно
FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def make_images(tmp: str, n: int):
    paths = []
    for i in range(n):
        p = os.path.join(tmp, f"img_{i:03d}.png")
        Image.new("RGB", (IMG_W, IMG_H), (i % 255, (i * 7) % 255, (i * 13) % 255)).save(p, "PNG")
        paths.append(p)
    return paths


def view_rows(block) -> int:
    return block.visible_rows()


class GalleryApp(App):
    CSS = "VerticalScroll { height: 1fr; }"

    def __init__(self, paths):
        super().__init__()
        self._paths = paths

    def compose(self):
        with VerticalScroll(id="chat"):
            for p in self._paths:
                yield ImageBlock(p, alt="img")

    def on_scroll(self, event) -> None:
        refresh_visible_images(self.query_one("#chat", VerticalScroll))


async def settle(pilot, seconds: float = 1.2) -> None:
    await asyncio.sleep(seconds)
    await pilot.pause()


async def main() -> int:
    print("=" * 70)
    print(f"Lazy images 4K smoke-test ({VIEW[0]}x{VIEW[1]}, images {IMG_W}x{IMG_H}, n={N_IMAGES})")
    print("=" * 70)

    tmp = tempfile.mkdtemp(prefix="botinok_lazy_")
    paths = make_images(tmp, N_IMAGES)

    ir.clear_cache()
    calls = {"n": 0}
    real = ir.prepare_scaled

    def counting_render(path, width, rows, max_pixels=0):
        calls["n"] += 1
        return real(path, width, rows, max_pixels=max_pixels)

    ir.prepare_scaled = counting_render
    ticks = []
    try:
        app = GalleryApp(paths)
        async with app.run_test(size=VIEW) as pilot:
            app.set_interval(0.02, lambda: ticks.append(time.monotonic()))
            container = app.query_one("#chat", VerticalScroll)
            await settle(pilot, 1.5)

            initial = calls["n"]
            visible = refresh_visible_images(container)
            print(f"  · старт: подготовлено копий {initial} из {N_IMAGES} (видимых блоков {visible})")
            check("initial_only_visible", 0 < initial <= visible + 4,
                  f"rendered={initial} visible={visible} of {N_IMAGES}")

            # Высокая картинка: разобранный срез много меньше всей высоты.
            blocks = list(container.query(ImageBlock))
            first = blocks[0]
            total_rows = first.total_rows()
            slice_rows = view_rows(first)
            print(f"  · срез первой картинки: {slice_rows} строк из {total_rows}")
            check("tall_image_rendered", total_rows > 200, f"total_rows={total_rows}")
            check("slice_is_window", 0 < slice_rows <= VIEW[1] + 40,
                  f"slice_rows={slice_rows} (не должно быть {total_rows})")
            check("block_height_reserved", first.region.height >= total_rows - 2,
                  f"region_h={first.region.height} total={total_rows}")

            # Прокрутка вглубь: подтягивается срез у видимых, но не все сразу.
            before_scroll = calls["n"]
            container.scroll_to(y=container.scroll_offset.y + 6000, animate=False)
            await settle(pilot, 1.0)
            refresh_visible_images(container)
            await settle(pilot, 0.6)
            print(f"  · после прокрутки: подготовлено копий {calls['n']} из {N_IMAGES}")
            check("scroll_not_all", calls["n"] < N_IMAGES,
                  f"rendered={calls['n']} of {N_IMAGES}")

            # Ресайз: перерисовываются только видимые.
            before_resize = calls["n"]
            await pilot.resize_terminal(420, 110)
            await settle(pilot, 1.2)
            refresh_visible_images(container)
            await settle(pilot, 0.8)
            added = calls["n"] - before_resize
            vis_now = refresh_visible_images(container)
            print(f"  · после ресайза: догон {added} (видимых {vis_now}), всего {calls['n']}")
            check("resize_not_all", added <= vis_now + 6, f"added={added} visible={vis_now}")
            check("resize_bounded", added < N_IMAGES // 3, f"added={added} of {N_IMAGES}")

            gaps = [b - a for a, b in zip(ticks, ticks[1:])]
            max_gap = max(gaps) if gaps else 0.0
            print(f"  · максимальный провал UI: {max_gap*1000:.0f} мс")
            check("ui_responsive_4k", max_gap < 0.5,
                  f"max_gap={max_gap:.3f}s (блокировка UI-потока)")
    finally:
        ir.prepare_scaled = real

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ LAZY IMAGES 4K SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=120))
    except asyncio.TimeoutError:
        print("  [FAIL] lazy_timeout — UI завис")
        os._exit(1)
