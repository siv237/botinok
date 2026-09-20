#!/usr/bin/env python3
"""Новая строка в Composer: Alt+Enter (универсально), Ctrl+J, Shift+Enter.

Проверяем:
- `install()` ставит парсер в Linux-драйвер Textual;
- Alt+Enter в обычном терминале (ESC + CR/LF, так шлёт VTE/xterm) -> `alt+enter`
  и Composer вставляет перевод строки, а не отправляет;
- формы Kitty (`\\x1b[13;3u`) и modifyOtherKeys (`\\x1b[27;3;13~`) тоже дают перенос;
- Enter и Ctrl+Enter отправляют.

Запуск: venv/bin/python -u tests/test_newline_keys.py
"""

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import textual.drivers.linux_driver as linux_driver  # noqa: E402

from core.textual_app import BotinokTextualApp  # noqa: E402
from core.terminal_keys import BotinokXTermParser, install  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def parse(data: bytes):
    """Разобрать байты терминала, включая ESC-последовательности (с таймаутом)."""
    parser = BotinokXTermParser(debug=False)
    events = list(parser.feed(data.decode()))
    if b"\x1b" in data:
        time.sleep(0.16)
        events += list(parser.tick())
    return events


def feed(app, data: bytes) -> None:
    for event in parse(data):
        app.post_message(event)


def reset(app) -> None:
    c = app.input_widget
    c.text = ""
    c._paste_until = 0.0
    c._prev_len = 0
    c._last_change = 0.0


def key_name(seq: str) -> str:
    events = parse(seq.encode())
    return events[0].key if events else ""


async def main() -> int:
    print("=" * 70)
    print("Newline keys smoke-test")
    print("=" * 70)

    os.environ["BOTINOK_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="botinok_nl_")

    install()
    check("driver_parser_installed", linux_driver.XTermParser is BotinokXTermParser)

    check("vte_alt_enter", key_name("\x1b\r") == "alt+enter",
          f"key={key_name(chr(27) + chr(13))!r}")
    check("vte_alt_enter_lf", key_name("\x1b\n") == "alt+enter")
    check("modifyOtherKeys_alt_enter", key_name("\x1b[27;3;13~") == "alt+enter")
    check("kitty_alt_enter", key_name("\x1b[13;3u") == "alt+enter")
    check("kitty_shift_enter", key_name("\x1b[13;2u") == "shift+enter")
    check("modifyOtherKeys_ctrl_enter", key_name("\x1b[27;5;13~") == "ctrl+enter")

    app = BotinokTextualApp(session_path="")
    submitted = []
    app.on_submit = lambda text: submitted.append(text)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        c = app.input_widget

        reset(app)
        submitted.clear()
        feed(app, b"x")
        feed(app, b"\x1b\r")
        feed(app, b"y")
        await pilot.pause()
        check("vte_alt_enter_newline", c.text == "x\ny" and submitted == [],
              f"text={c.text!r} submitted={submitted!r}")

        reset(app)
        submitted.clear()
        feed(app, b"x\x1b[13;3uy")
        await pilot.pause()
        check("kitty_alt_enter_newline", c.text == "x\ny" and submitted == [],
              f"text={c.text!r} submitted={submitted!r}")

        reset(app)
        submitted.clear()
        feed(app, b"x\x1b[27;3;13~y")
        await pilot.pause()
        check("modifyOtherKeys_alt_enter_newline", c.text == "x\ny" and submitted == [],
              f"text={c.text!r} submitted={submitted!r}")

        reset(app)
        submitted.clear()
        feed(app, b"x\x1b[13;2uy")
        await pilot.pause()
        check("shift_enter_newline", c.text == "x\ny" and submitted == [],
              f"text={c.text!r} submitted={submitted!r}")

        reset(app)
        submitted.clear()
        feed(app, b"x\x0ay")
        await pilot.pause()
        check("ctrl_j_newline", c.text == "x\ny" and submitted == [],
              f"text={c.text!r} submitted={submitted!r}")

        # Печатаем текст не «всплеском» (пауза), затем отправляем.
        reset(app)
        submitted.clear()
        feed(app, b"hi")
        await asyncio.sleep(0.35)
        feed(app, b"\x1b[27;5;13~")
        await pilot.pause()
        check("ctrl_enter_submits", submitted == ["hi"] and c.text == "",
              f"text={c.text!r} submitted={submitted!r}")

        reset(app)
        submitted.clear()
        feed(app, b"ok")
        await asyncio.sleep(0.35)
        feed(app, b"\r")
        await pilot.pause()
        check("enter_submits", submitted == ["ok"] and c.text == "",
              f"text={c.text!r} submitted={submitted!r}")

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ NEWLINE KEYS SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
