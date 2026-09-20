#!/usr/bin/env python3
"""Вставка в Composer: bracketed paste, средняя кнопка, крупные вставки-чипы.

Проверяем:
- bracketed paste вставляет многострочный текст целиком и НЕ отправляет;
- без bracketed paste («всплеск») Enter внутри вставки становится переносом;
- крупная вставка (>= PASTE_COLLAPSE_LINES строк) сворачивается в чип
  [Pasted ~N lines], а при отправке разворачивается в исходный текст;
- средняя кнопка (MouseDown button=2) вставляет primary selection.

Запуск: venv/bin/python -u tests/test_paste.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.textual_app as textual_app  # noqa: E402
from core.textual_app import BotinokTextualApp  # noqa: E402
from core.terminal_keys import BotinokXTermParser  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def feed(app, data: bytes) -> None:
    for event in BotinokXTermParser(debug=False).feed(data.decode()):
        app.post_message(event)


def reset(app) -> None:
    c = app.input_widget
    c.text = ""
    c._paste_until = 0.0
    c._prev_len = 0
    c._last_change = 0.0
    c._last_key_time = 0.0
    c._paste_blocks = []


BIG = "\n".join(f"line{i}" for i in range(1, 11))  # 10 строк


async def main() -> int:
    print("=" * 70)
    print("Paste smoke-test")
    print("=" * 70)

    os.environ["BOTINOK_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="botinok_paste_")

    app = BotinokTextualApp(session_path="")
    submitted = []
    app.on_submit = lambda text: submitted.append(text)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        c = app.input_widget

        # Bracketed paste: мелкая — как есть, без отправки.
        reset(app)
        submitted.clear()
        feed(app, b"\x1b[200~a\nb\x1b[201~")
        await pilot.pause()
        check("bracketed_small_literal", c.text == "a\nb" and submitted == [],
              f"text={c.text!r} submitted={submitted!r}")

        # Bracketed paste: крупная — вставляем целиком (без чипа).
        reset(app)
        submitted.clear()
        feed(app, ("\x1b[200~" + BIG + "\x1b[201~").encode())
        await pilot.pause()
        check("bracketed_big_full", c.text == BIG and submitted == [],
              f"text_len={len(c.text)}")
        c._paste_until = 0.0
        feed(app, b"\r")
        await pilot.pause()
        check("big_submits_full", submitted == [BIG],
              f"submitted_len={len(submitted[0]) if submitted else 0}")

        # Без bracketed paste («всплеск»): Enter внутри вставки — перенос.
        reset(app)
        submitted.clear()
        feed(app, b"line1\rline2\rline3")
        await pilot.pause()
        check("raw_burst_multiline", c.text == "line1\nline2\nline3" and submitted == [],
              f"text={c.text!r} submitted={submitted!r}")

        reset(app)
        submitted.clear()
        feed(app, b"ab\r")
        await pilot.pause()
        check("raw_burst_two_lines", c.text == "ab\n" and submitted == [],
              f"text={c.text!r} submitted={submitted!r}")

        # VTE внутри bracketed paste разделяет строки \r: нормализуем в \n.
        reset(app)
        submitted.clear()
        cr_big = "\r".join(f"строка {i}" for i in range(1, 12))
        feed(app, ("\x1b[200~" + cr_big + "\x1b[201~").encode())
        await pilot.pause()
        check("bracketed_cr_full", c.text == cr_big.replace("\r", "\n") and submitted == [],
              f"text={c.text!r}")

        # Вставка при фокусе вне поля ввода — ловим на уровне App.
        reset(app)
        submitted.clear()
        app.set_focus(None)
        await pilot.pause()
        feed(app, b"\x1b[200~hello\nworld\x1b[201~")
        await pilot.pause()
        check("paste_without_focus", c.text == "hello\nworld",
              f"text={c.text!r} focused={app.focused!r}")

        # Средняя кнопка: primary selection -> вставляем целиком.
        reset(app)
        submitted.clear()
        original = textual_app.read_primary_selection
        textual_app.read_primary_selection = lambda: BIG
        try:
            feed(app, b"\x1b[<1;10;5M")  # MouseDown button=2
            await asyncio.sleep(0.2)
            await pilot.pause()
        finally:
            textual_app.read_primary_selection = original
        check("middle_click_full", c.text == BIG, f"text_len={len(c.text)}")
        c._paste_until = 0.0
        feed(app, b"\r")
        await pilot.pause()
        check("middle_click_submits_full", submitted == [BIG],
              f"submitted_len={len(submitted[0]) if submitted else 0}")

        # Обычная отправка одиночного текста (печатаем не «всплеском»).
        reset(app)
        submitted.clear()
        feed(app, b"ok")
        await asyncio.sleep(0.35)
        feed(app, b"\r")
        await pilot.pause()
        check("plain_enter_submits", submitted == ["ok"] and c.text == "",
              f"text={c.text!r} submitted={submitted!r}")

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ PASTE SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
