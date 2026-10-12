#!/usr/bin/env python3
"""
Контрастность по WCAG AA (4.5:1) для ВСЕХ тем — и TUI, и веб-зеркала:
  • палитры core/themes.py (переменные тем + базовые цвета Textual);
  • адаптация rich-разметки (themes.markup_colors) на фонах каждой темы;
  • CSS-переменные страницы зеркала core/web_mirror._PAGE (night/day/evening).

Запуск: venv/bin/python -u tests/test_theme_contrast.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import themes as T  # noqa: E402
from core.web_mirror import _PAGE  # noqa: E402

MIN_RATIO = 4.5
FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def rgb(color: str):
    # Имена/хэмы резолвим тем же парсером, каким их рендерит Textual.
    from textual.color import Color as TColor
    c = TColor.parse(str(color))
    return (c.r, c.g, c.b)


def contrast(a, b) -> float:
    la = 0.2126 * _lin(a[0]) + 0.7152 * _lin(a[1]) + 0.0722 * _lin(a[2])
    lb = 0.2126 * _lin(b[0]) + 0.7152 * _lin(b[1]) + 0.0722 * _lin(b[2])
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def pair(name, fg, bgs):
    """fg читается хотя бы на худшем из bgs."""
    worst = min(contrast(rgb(fg), rgb(bg)) for bg in bgs)
    check(name, worst >= MIN_RATIO, f"{fg} → {round(worst, 2)}:1 (мин. {MIN_RATIO})")


# ── TUI: темы core/themes.py ────────────────────────────────────────────────

NIGHT_BASE = {"background": "#121212", "surface": "#1e1e1e", "panel": "#2a2a2a",
              "primary": "#0178D4", "accent": "#ffa62b", "foreground": "#e0e0e0"}


def theme_surfaces(name):
    th = T.build_themes()[name]
    base = dict(NIGHT_BASE) if name == "night" else {}
    out = {}
    for attr in ("background", "surface", "panel", "primary", "accent", "foreground"):
        v = getattr(th, attr, None)
        out[attr] = str(v) if v is not None else base.get(attr, "#000000")
    return out


def check_tui():
    for name in T.THEME_ORDER:
        th = T.build_themes()[name]
        v = th.variables
        s = theme_surfaces(name)
        bgs = [s["background"], s["surface"], s["panel"]]
        pair(f"[tui:{name}] hdr-fg/hdr-bg", v["hdr-fg"], [v["hdr-bg"]])
        pair(f"[tui:{name}] web-on/hdr-bg", v["web-on"], [v["hdr-bg"]])
        pair(f"[tui:{name}] pager-fg/hdr-bg", v["pager-fg"], [v["hdr-bg"]])
        pair(f"[tui:{name}] flag-fg/flag-bg", v["flag-fg"], [v["flag-bg"]])
        pair(f"[tui:{name}] cmd-fg/cmd-bg", v["cmd-fg"], [v["cmd-bg"]])
        pair(f"[tui:{name}] foreground/фоны", s["foreground"], bgs)
        for key in ("hl", "ok", "warn", "err"):
            pair(f"[tui:{name}] {key}/фоны", v[key], bgs)
        pair(f"[tui:{name}] accent-fg/primary", v["accent-fg"], [s["primary"]])
        pair(f"[tui:{name}] accent-fg/accent", v["accent-fg"], [s["accent"]])
        for cname, cval in sorted(T.markup_colors(name).items()):
            pair(f"[tui:{name}] rich[{cname}]/фоны", cval, bgs)


# ── Зеркало: CSS страницы core/web_mirror._PAGE ─────────────────────────────

def mirror_palettes():
    base = dict(re.findall(r"--([a-z]+)\s*:\s*(#[0-9a-fA-F]{3,8})",
                           re.search(r"body\{(.*?)\}", _PAGE, re.S).group(1)))
    pals = {"night": base}
    for cls in ("day", "evening"):
        m = re.search(r"body\." + cls + r"\{(.*?)\}", _PAGE, re.S)
        assert m, f"в странице нет темы {cls}"
        pals[cls] = {**base, **dict(re.findall(
            r"--([a-z]+)\s*:\s*(#[0-9a-fA-F]{3,8})", m.group(1)))}
    return pals


def check_mirror():
    for name, p in mirror_palettes().items():
        bgs = [p["bg"], p["panel"], p["code"], p["user"], p["think"]]
        pair(f"[mirror:{name}] text/фоны", p["text"], bgs)
        pair(f"[mirror:{name}] muted/фоны", p["muted"], [p["bg"], p["panel"], p["think"]])
        pair(f"[mirror:{name}] accent/фоны", p["accent"],
             [p["bg"], p["panel"], p["user"], p["code"]])
        pair(f"[mirror:{name}] ok/фоны", p["ok"], [p["bg"], p["panel"]])
        pair(f"[mirror:{name}] warn/фоны", p["warn"], [p["bg"], p["panel"]])
        pair(f"[mirror:{name}] err/фоны", p["err"], [p["bg"], p["panel"]])


def check_shadow():
    """Static в TUI обязан адаптировать разметку (баннер «версия …» жёлтым
    на белом проскакивал именно потому, что миновал адаптацию)."""
    T.set_active_theme("day")
    try:
        from core import textual_app as TA
        from core import shell_screen as SH
        for mod, name in ((TA, "textual_app"), (SH, "shell_screen")):
            r = mod.Static("[bold yellow]версия[/bold yellow]").render()
            style = str(r.spans[0].style) if getattr(r, "spans", None) else ""
            want = T.markup_colors("day")["yellow"]
            ok = want in style
            check(f"[shadow:{name}] Static адаптирует [bold yellow]", ok,
                  f"стиль: {style!r}, ожидался {want}")
    finally:
        T.set_active_theme(T.DEFAULT_THEME)


def test_contrast() -> None:
    bad = list(FAILURES)
    run_all()
    assert not FAILURES, "низкий контраст: " + ", ".join(FAILURES[len(bad):])


def run_all() -> int:
    print("=" * 70)
    print("Контрастность WCAG AA (4.5:1): темы TUI + страница зеркала")
    print("=" * 70)
    check_tui()
    check_mirror()
    check_shadow()
    print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if not FAILURES else 'ПРОВАЛЫ: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(run_all())
