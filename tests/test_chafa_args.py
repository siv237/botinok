#!/usr/bin/env python3
"""
Регрессия: совместимость аргументов chafa и рабочий полосовой рендер.

Причина: chafa 1.8.0 (Ubuntu 22.04) не поддерживает `--animate`, а рендер
передавал его всегда → команда падала (rc=1), `render_image_band` возвращал
None, и картинки в чате не рисовались даже при установленном chafa.

Запуск: venv/bin/python -u tests/test_chafa_args.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import image_render as R  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("chafa args/render smoke-test")
    print("=" * 70)

    saved = R._CHAFA_CAPS
    try:
        # Старый chafa (без --animate): флаг не добавляется.
        R._CHAFA_CAPS = set()
        args = R._chafa_base_args("sextant")
        check("no_animate_when_unsupported", "--animate" not in args, str(args))
        check("base_flags_present",
              all(f in args for f in ("--format", "symbols", "--colors", "full")), str(args))

        # Новый chafa: флаг добавляется.
        R._CHAFA_CAPS = {"animate", "size", "stretch"}
        args2 = R._chafa_base_args("sextant")
        check("animate_when_supported", "--animate" in args2 and "off" in args2, str(args2))
    finally:
        R._CHAFA_CAPS = saved

    check("caps_is_set", isinstance(R.chafa_caps(), set))

    chafa = R.chafa_path()
    if not chafa:
        print("  [SKIP] chafa не установлен — проверка реального рендера пропущена")
    else:
        try:
            from PIL import Image
            tmp = tempfile.mkdtemp(prefix="botinok_chafa_")
            src = os.path.join(tmp, "src.png")
            Image.new("RGB", (800, 500), (30, 120, 200)).save(src)

            full = R.render_with_chafa(src, 40)
            check("full_render_ok", bool(full) and "\x1b[" in full,
                  "None" if full is None else f"{len(full)}b")

            band = R.render_image_band(src, 40, 10, 0, 100)
            check("band_render_ok", bool(band) and "\x1b[" in band,
                  "None" if band is None else f"{len(band)}b")
            if band:
                check("band_height", R.visible_height(band) == 10,
                      f"h={R.visible_height(band)}")
        except Exception as e:
            check("render_exc", False, f"{type(e).__name__}: {e}")

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ CHAFA ARGS SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
