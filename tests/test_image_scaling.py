#!/usr/bin/env python3
"""Нормализация изображения под размер терминала + полосовой рендер.

Требование: не рендерить всю картинку. Инструмент на лету берёт исходник,
вычисляет текущий размер терминала, делает уменьшенную копию нужного
разрешения и кэширует её, пока размер окна не изменился.

Запуск: venv/bin/python -u tests/test_image_scaling.py
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


def main() -> int:
    print("=" * 70)
    print("Image scaling/band smoke-test")
    print("=" * 70)

    tmp = tempfile.mkdtemp(prefix="botinok_scale_")
    huge = os.path.join(tmp, "huge.jpg")
    Image.new("RGB", (4000, 3000), (30, 110, 190)).save(huge, "JPEG", quality=92)
    ir.clear_cache()

    width = 200
    # Сколько строк займёт картинка: aspect 0.75 → rows = width*0.75/2
    rows = max(1, int(round(width * (3000 / 4000) / 2)))

    # --- уменьшенная копия под размер терминала ---
    t0 = time.time()
    res = ir.prepare_scaled(huge, width, rows)
    dt_first = (time.time() - t0) * 1000
    check("scaled_created", bool(res), str(res))
    scaled, tw, th = res
    check("scaled_size_matches_terminal", tw <= width * 2 and th <= rows * 2 and tw >= width,
          f"{tw}x{th} для width={width} rows={rows}")
    check("scaled_smaller_than_source", tw < 4000, f"{tw} < 4000")
    check("scaled_written", os.path.isfile(scaled))

    # --- кэш: пока размер окна не изменился, не пересчитываем ---
    t0 = time.time()
    res2 = ir.prepare_scaled(huge, width, rows)
    dt_cached = (time.time() - t0) * 1000
    check("scaled_cached", res2 and res2[0] == scaled, str(res2 and res2[0]))
    check("scaled_cached_fast", dt_cached < 5.0, f"{dt_cached:.2f}ms (first {dt_first:.1f}ms)")
    print(f"  · подготовка: первый раз {dt_first:.1f}ms, из кэша {dt_cached:.2f}ms")

    # --- смена размера окна → новая копия ---
    res3 = ir.prepare_scaled(huge, width - 40, max(1, rows // 2))
    check("rescaled_on_resize", res3 and res3[0] != scaled, str(res3 and res3[0]))

    # --- полосовой рендер: только видимый кусок ---
    t0 = time.time()
    band = ir.render_image_band(scaled, width, 20, 0, 40)
    dt_band = (time.time() - t0) * 1000
    check("band_rendered", bool(band and band.strip()))
    check("band_height_exact", ir.visible_height(band) == 20,
          f"h={ir.visible_height(band)} (запрошено 20)")
    check("band_width", ir.visible_width(band) == width,
          f"w={ir.visible_width(band)}")
    t0 = time.time()
    ir.render_image_band(scaled, width, 20, 0, 40)
    dt_band_cached = (time.time() - t0) * 1000
    check("band_cached_fast", dt_band_cached < 2.0, f"{dt_band_cached:.2f}ms")
    print(f"  · полоса 20 строк: первый раз {dt_band:.1f}ms, из кэша {dt_band_cached:.2f}ms")

    # --- стоимость не зависит от размера исходника ---
    small = os.path.join(tmp, "small.jpg")
    Image.new("RGB", (400, 300), (30, 110, 190)).save(small, "JPEG", quality=92)
    res_small = ir.prepare_scaled(small, width, rows)
    ir.clear_cache()
    t0 = time.time()
    ir.render_image_band(res_small[0], width, 20, 0, 40)
    dt_small = (time.time() - t0) * 1000
    print(f"  · полоса из большого исходника {dt_band:.1f}ms vs из маленького {dt_small:.1f}ms")
    check("size_independent", dt_band < max(60.0, dt_small * 4),
          f"huge={dt_band:.1f}ms small={dt_small:.1f}ms")

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ IMAGE SCALING SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    main()
