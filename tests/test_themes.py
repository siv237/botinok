#!/usr/bin/env python3
"""Темы: ночь (текущая, дефолт), день (белая), вечер (голубая); иконка-цикл в шапке.

Проверяем:
- палитры: night — клон textual-dark (вид не меняется), day — белая, evening — голубая;
- [UI] theme: чтение с фолбэком и построчная запись с сохранением комментариев;
- цикл тем по клику на иконку в левом верхнем углу + персист в конфиг.

Запуск: venv/bin/python -u tests/test_themes.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.theme import BUILTIN_THEMES  # noqa: E402

from core import themes as T  # noqa: E402
from core.textual_app import BotinokTextualApp  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def test_palettes() -> None:
    th = T.build_themes()
    check("three_themes", set(th) == {"night", "day", "evening"})
    td = BUILTIN_THEMES["textual-dark"]
    n = th["night"]
    check("night_is_clone", n.primary == td.primary and n.foreground == td.foreground
          and n.dark == td.dark)
    check("night_vars_match_old_css", n.variables.get("hdr-bg") == "#0055aa"
          and n.variables.get("hl") == "#00ffff" and n.variables.get("cmd-bg") == "#0f0f0f")
    check("day_white", th["day"].dark is False and th["day"].background == "#ffffff")
    check("evening_blue", th["evening"].dark is True and th["evening"].background == "#0d2b45")


def test_resolve_save() -> None:
    class Cfg:
        def __init__(self, v):
            self.v = v

        def get(self, sec, key, fallback=""):
            return self.v

    check("default_night", T.resolve_theme_name(Cfg("")) == "night")
    check("unknown_night", T.resolve_theme_name(Cfg("bogus")) == "night")
    check("day_ok", T.resolve_theme_name(Cfg("Day")) == "day")
    check("cycle", T.next_theme("night") == "day" and T.next_theme("evening") == "night")

    d = tempfile.mkdtemp(prefix="botinok_themes_")
    p = os.path.join(d, "config.cfg")
    with open(p, "w", encoding="utf-8") as f:
        f.write("[Ollama]\nbaseurl = http://x\n; коммент\n[UI]\nshowvram = true\ntheme = night\n")
    check("save_replace", T.save_theme_name("evening", p) is True)
    txt = open(p, encoding="utf-8").read()
    check("persisted", "theme = evening" in txt and "theme = night" not in txt)
    check("comments_kept", "; коммент" in txt and "showvram = true" in txt)

    p2 = os.path.join(d, "c2.cfg")
    with open(p2, "w", encoding="utf-8") as f:
        f.write("[Ollama]\nbaseurl = http://x\n")
    T.save_theme_name("day", p2)
    txt2 = open(p2, encoding="utf-8").read()
    check("section_added", "[UI]" in txt2 and "theme = day" in txt2)

    # Глобальный путь: load видит global, save(None) пишет туда же.
    g = os.path.join(d, "nested", "global.cfg")
    old_global = T.GLOBAL_CONFIG_PATH
    try:
        T.GLOBAL_CONFIG_PATH = g
        check("load_missing_global_night", T.load_theme_name() == "night")
        T.save_theme_name("evening")
        check("save_global_creates_dirs", os.path.exists(g))
        check("load_global", T.load_theme_name() == "evening")
        check("global_beats_fallback",
              T.load_theme_name(Cfg("day")) == "evening")
    finally:
        T.GLOBAL_CONFIG_PATH = old_global


async def test_app() -> None:
    os.environ["BOTINOK_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="botinok_themes_s_")
    d = tempfile.mkdtemp(prefix="botinok_themes_c_")
    cfg = os.path.join(d, "config.cfg")
    open(cfg, "w", encoding="utf-8").close()
    old_global = T.GLOBAL_CONFIG_PATH
    T.GLOBAL_CONFIG_PATH = os.path.join(d, "global.cfg")
    try:
        app = BotinokTextualApp(session_path="", config_path=cfg)
        app.on_submit = lambda t: None
        check("default_theme_night", app.theme == "night")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            btn = app.query_one("#theme_btn")
            check("icon_in_header", btn in app.header_row.children)
            check("glyph_shows_next", "☀" in (app.theme_btn.render().plain if hasattr(app.theme_btn.render(), "plain") else str(app.theme_btn.render())))
            await pilot.click("#theme_btn")
            await pilot.pause()
            check("click_cycles_day", app.theme == "day", f"theme={app.theme}")
            await pilot.click("#theme_btn")
            await pilot.pause()
            check("click_cycles_evening", app.theme == "evening", f"theme={app.theme}")
            await pilot.click("#theme_btn")
            await pilot.pause()
            check("click_wraps_night", app.theme == "night", f"theme={app.theme}")
        txt = open(cfg, encoding="utf-8").read()
        check("click_persists", "theme = night" in txt, txt.strip())

        # Диалог-меню (wizard): mixin применяет глобальную тему и даёт иконку.
        T.save_theme_name("day")
        from core.textual_prompts import _SelectApp
        dlg = _SelectApp("тест", [("а", 1)])
        check("dialog_uses_global_theme", dlg.theme == "day", f"theme={dlg.theme}")

        # Без config_path — клик пишет в глобальный конфиг.
        app2 = BotinokTextualApp(session_path="")
        app2.on_submit = lambda t: None
        async with app2.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#theme_btn")
            await pilot.pause()
        gtxt = open(T.GLOBAL_CONFIG_PATH, encoding="utf-8").read()
        check("click_writes_global", "theme = evening" in gtxt, gtxt.strip())
    finally:
        T.GLOBAL_CONFIG_PATH = old_global


def main() -> int:
    print("=" * 70)
    print("Themes test")
    print("=" * 70)
    test_palettes()
    test_resolve_save()
    asyncio.run(test_app())
    print("=" * 70)
    print("FAILED:", FAILURES if FAILURES else "нет")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
