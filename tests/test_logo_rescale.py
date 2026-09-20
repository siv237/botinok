#!/usr/bin/env python3
"""Реактивное перемасштабирование картинки в чате (баннер/логотип).

Проверяем, что при изменении размера окна логотип:
- перерисовывается под новую ширину, влезает и не разрастается по высоте;
- не запускает рендер лавиной (single-flight + кэш);
- НЕ блокирует UI-поток: таймер не «проваливается» во время ресайзов
  (раньше Text.from_ansi на широком окне блокировал цикл на ~1.2с).

Запуск: venv/bin/python -u tests/test_logo_rescale.py
"""

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.image_render as ir  # noqa: E402
from core.textual_app import BotinokTextualApp  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def banner_plain(app) -> str:
    st = getattr(app, "_banner_static", None)
    if st is None:
        return ""
    try:
        v = st.visual
        return v.plain if hasattr(v, "plain") else str(getattr(st, "content", ""))
    except Exception:
        return ""


def banner_size(app):
    plain = banner_plain(app)
    lines = plain.split("\n")
    width = max((len(l) for l in lines), default=0)
    height = sum(1 for l in lines if l.strip())
    return width, height


async def settle(pilot, seconds: float = 1.0) -> None:
    await asyncio.sleep(seconds)
    await pilot.pause()


async def main() -> int:
    print("=" * 70)
    print("Logo rescale smoke-test")
    print("=" * 70)

    os.environ["BOTINOK_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="botinok_logo_")

    ir.clear_cache()
    calls = {"n": 0}
    real_render = ir.render_image_ansi

    def counting_render(path, width, prefer_chafa=True, symbols=None, max_height=0):
        calls["n"] += 1
        return real_render(path, width, prefer_chafa=prefer_chafa, symbols=symbols,
                           max_height=max_height)

    ir.render_image_ansi = counting_render
    ticks = []
    try:
        app = BotinokTextualApp(session_path="")
        app.on_submit = lambda t: None
        async with app.run_test(size=(120, 34)) as pilot:
            # Пульс UI: раз в 20мс. Провал между тиками = блокировка цикла.
            app.set_interval(0.02, lambda: ticks.append(time.monotonic()))
            await settle(pilot)
            used0 = app._logo_width_used or 0
            check("initial_rendered", used0 > 0, f"used={used0}")

            for size in ((60, 34), (240, 34)):
                await pilot.resize_terminal(*size)
                await asyncio.sleep(0.05)
            await settle(pilot, 1.5)

            avail = app.chat.scrollable_content_region.width
            used = app._logo_width_used or 0
            width, height = banner_size(app)
            expected = min(max(16, (avail - 1) // 4 * 4), app.LOGO_MAX_WIDTH)
            check("scaled_after_resize", used == expected,
                  f"used={used} expected={expected} avail={avail}")
            check("banner_fits", width <= avail, f"banner={width} avail={avail}")
            check("banner_width_capped", width <= app.LOGO_MAX_WIDTH,
                  f"banner={width} cap={app.LOGO_MAX_WIDTH}")
            check("banner_height_capped", height <= app.LOGO_MAX_HEIGHT + 2,
                  f"height={height} cap={app.LOGO_MAX_HEIGHT}")

            # Немного ресайзов не должны плодить рендеры.
            before = calls["n"]
            for size in ((150, 34), (155, 34), (152, 34), (158, 34)):
                await pilot.resize_terminal(*size)
                await asyncio.sleep(0.02)
            await settle(pilot, 1.0)
            extra = calls["n"] - before
            # Число рендеров должно быть линейным (не лавина): не больше числа
            # ресайзов + небольшой запас на догоняющий рендер.
            check("no_render_storm", extra <= 6, f"extra_renders={extra}")

            # РЕАЛЬНЫЙ maximize 4К (480x135) — последним шагом, чтобы «провал» UI
            # попал в измерение. Раньше это вешало интерфейс на ~1.5с.
            before_max = calls["n"]
            await pilot.resize_terminal(480, 135)
            await settle(pilot, 2.5)
            max_extra = calls["n"] - before_max
            max_width, max_height = banner_size(app)
            check("maximize_render_bounded", max_extra <= 4, f"extra_renders={max_extra}")
            check("maximize_width_capped", max_width <= app.LOGO_MAX_WIDTH,
                  f"banner={max_width} cap={app.LOGO_MAX_WIDTH}")
            check("maximize_height_capped", max_height <= app.LOGO_MAX_HEIGHT + 2,
                  f"height={max_height} cap={app.LOGO_MAX_HEIGHT}")

            # Отзывчивость: таймер не должен «проваливаться» надолго.
            gaps = [b - a for a, b in zip(ticks, ticks[1:])]
            max_gap = max(gaps) if gaps else 0.0
            check("ui_responsive", max_gap < 0.5,
                  f"max_gap={max_gap:.3f}s (блокировка UI-потока)")
    finally:
        ir.render_image_ansi = real_render

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ LOGO RESCALE SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    # Жёсткий таймаут: если UI зависнет — тест упадёт, а не повиснет.
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=60))
    except asyncio.TimeoutError:
        print("  [FAIL] rescale_timeout — перемасштабирование зависло")
        os._exit(1)
