#!/usr/bin/env python3
"""
Регрессия: большие ICC-профили (CMYK-фото) не должны ломать рендер.

PIL отказывается открывать PNG с iCCP-чанком больше MAX_TEXT_CHUNK:
    ValueError: Decompressed data too large for PngImagePlugin.MAX_TEXT_CHUNK
Это ломало полосовой рендер (render_image_band → None) на профессиональных
фото. Исправление: поднят лимит + ICC/EXIF не пишутся в PNG-кэш копий.

Запуск: venv/bin/python -u tests/test_image_icc.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import image_render as R  # noqa: E402
from PIL import Image, PngImagePlugin  # noqa: E402

FAILURES = []
BIG_ICC = b"\x00" * (2 * 1024 * 1024)  # распаковывается заметно больше лимита PIL


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("image ICC smoke-test")
    print("=" * 70)

    check("max_text_chunk_raised",
          PngImagePlugin.MAX_TEXT_CHUNK is None
          or PngImagePlugin.MAX_TEXT_CHUNK >= 64 * 1024 * 1024,
          str(PngImagePlugin.MAX_TEXT_CHUNK))

    tmp = tempfile.mkdtemp(prefix="botinok_icc_")

    # 1) «Старый» проблемный кэш: PNG с огромным iCCP — должен открываться.
    legacy = os.path.join(tmp, "legacy.png")
    Image.new("RGB", (400, 300), (40, 90, 160)).save(
        legacy, "PNG", icc_profile=BIG_ICC)
    try:
        with Image.open(legacy) as im:
            im.load()
        check("legacy_big_icc_opens", True)
    except Exception as e:
        check("legacy_big_icc_opens", False, f"{type(e).__name__}: {e}")

    # 2) prepare_scaled не должен тащить ICC в кэш уменьшенной копии.
    src = os.path.join(tmp, "src.png")
    im = Image.new("RGB", (800, 600), (30, 120, 200))
    im.info["icc_profile"] = BIG_ICC
    im.save(src, "PNG", icc_profile=BIG_ICC)
    pre = R.prepare_scaled(src, 40, 30)
    check("scaled_created", bool(pre))
    if pre:
        cached, tw, th = pre
        try:
            with Image.open(cached) as c:
                c.load()
                has_icc = bool(c.info.get("icc_profile"))
            check("scaled_cache_opens", True)
            check("scaled_cache_without_icc", not has_icc)
        except Exception as e:
            check("scaled_cache_opens", False, f"{type(e).__name__}: {e}")

        if R.chafa_path():
            band = R.render_image_band(cached, 40, 30, 0, th)
            check("band_from_scaled", bool(band), "None" if band is None else str(len(band)))
        else:
            print("  [SKIP] chafa не установлен — полосовой рендер не проверяется")

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ IMAGE ICC SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
