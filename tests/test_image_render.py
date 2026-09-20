#!/usr/bin/env python3
"""Тесты рендера изображений в терминал (основа показа картинок в чате).

Проверяем механику: ANSI-рендер, соблюдение ширины, фолбэк без chafa,
кэш (реактивность) и инвалидацию кэша по mtime.

Запуск: venv/bin/python -u tests/test_image_render.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.image_render as ir  # noqa: E402
from PIL import Image  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def make_png(path: str, w: int = 160, h: int = 100) -> None:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 255) // max(1, w - 1), (y * 255) // max(1, h - 1), 128)
    img.save(path, "PNG")


def main() -> int:
    print("=" * 70)
    print("Image render smoke-test")
    print("=" * 70)

    tmp = tempfile.mkdtemp(prefix="botinok_img_")
    png = os.path.join(tmp, "pic.png")
    make_png(png)
    ir.clear_cache()

    # --- базовый рендер и ширина ---
    for width in (20, 40, 80):
        out = ir.render_image_ansi(png, width)
        check(f"render_non_empty_w{width}", bool(out and out.strip()))
        if out:
            check(f"render_fits_w{width}", ir.visible_width(out) <= width,
                  f"width={ir.visible_width(out)} > {width}")
            check(f"render_lines_w{width}", ir.visible_height(out) >= 1)

    # --- нет файла / плохая ширина ---
    check("missing_file_none", ir.render_image_ansi(os.path.join(tmp, "nope.png"), 40) is None)
    check("zero_width_none", ir.render_image_ansi(png, 0) is None)

    # --- кэш: повторный рендер той же ширины не вызывает chafa ---
    ir.clear_cache()
    calls = {"n": 0}
    real_chafa = ir.render_with_chafa

    def counting_chafa(path, width, symbols=None, timeout=15.0, max_height=0):
        calls["n"] += 1
        return real_chafa(path, width, symbols=symbols, timeout=timeout, max_height=max_height)

    ir.render_with_chafa = counting_chafa
    try:
        first = ir.render_image_ansi(png, 50)
        after_first = calls["n"]
        second = ir.render_image_ansi(png, 50)
        after_second = calls["n"]
    finally:
        ir.render_with_chafa = real_chafa

    check("cache_renders_once", after_first >= 1 and after_second == after_first,
          f"calls {after_first} -> {after_second}")
    check("cache_same_result", first == second)

    # --- разная ширина — разный рендер ---
    a = ir.render_image_ansi(png, 30)
    b = ir.render_image_ansi(png, 90)
    check("different_width_differs", a != b)

    # --- фолбэк без chafa (встроенный рендер) ---
    ir.clear_cache()
    real_chafa_path = ir.chafa_path
    ir.chafa_path = lambda: None
    try:
        fallback = ir.render_image_ansi(png, 40)
    finally:
        ir.chafa_path = real_chafa_path
    check("fallback_without_chafa", bool(fallback and fallback.strip()))
    if fallback:
        check("fallback_fits", ir.visible_width(fallback) <= 40,
              f"width={ir.visible_width(fallback)}")

    # --- инвалидация кэша по mtime ---
    ir.clear_cache()
    calls2 = {"n": 0}

    def counting_chafa2(path, width, symbols=None, timeout=15.0, max_height=0):
        calls2["n"] += 1
        return real_chafa(path, width, symbols=symbols, timeout=timeout, max_height=max_height)

    ir.render_with_chafa = counting_chafa2
    try:
        ir.render_image_ansi(png, 60)
        n1 = calls2["n"]
        time.sleep(1.1)
        make_png(png, 161, 100)          # тот же путь, новый mtime
        ir.render_image_ansi(png, 60)
        n2 = calls2["n"]
    finally:
        ir.render_with_chafa = real_chafa
    check("cache_invalidated_on_mtime", n2 > n1, f"calls {n1} -> {n2}")

    # --- утилиты ---
    sample = "\x1b[31mabc\x1b[0m\n\x1b[1mde\x1b[0m"
    check("strip_ansi", ir.strip_ansi(sample) == "abc\nde")
    check("visible_width_util", ir.visible_width(sample) == 3)
    check("visible_height_util", ir.visible_height(sample) == 2)

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ IMAGE RENDER SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    main()
