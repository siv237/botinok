#!/usr/bin/env python3
"""
Тесты _ensure_truecolor_env (botinok.py): эвристика объявления truecolor.

Запуск: venv/bin/python -u tests/test_truecolor_env.py
"""

import os
import sys
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import botinok as B  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


class TTY(io.StringIO):
    def isatty(self):
        return True


class NoTTY(io.StringIO):
    def isatty(self):
        return False


def run(env, tty=True):
    saved = dict(os.environ)
    real_stdout = sys.stdout
    try:
        for k in ("COLORTERM", "TERM", "BOTINOK_TRUECOLOR"):
            os.environ.pop(k, None)
        os.environ.update(env)
        sys.stdout = TTY() if tty else NoTTY()
        B._ensure_truecolor_env()
        return os.environ.get("COLORTERM")
    finally:
        os.environ.clear()
        os.environ.update(saved)
        sys.stdout = real_stdout


def main() -> int:
    print("=" * 60)
    print("truecolor env tests")
    print("=" * 60)
    check("ssh без COLORTERM (xterm-256color) → truecolor",
          run({"TERM": "xterm-256color"}) == "truecolor")
    check("уже truecolor — не трогаем",
          run({"TERM": "xterm-256color", "COLORTERM": "truecolor"}) == "truecolor")
    check("TERM=linux (консоль) — не форсируем",
          run({"TERM": "linux"}) is None)
    check("TERM=dumb — не форсируем", run({"TERM": "dumb"}) is None)
    check("TERM пустой — не форсируем", run({}) is None)
    check("screen — не форсируем",
          run({"TERM": "screen-256color"}) is None)
    check("не TTY — не форсируем",
          run({"TERM": "xterm-256color"}, tty=False) is None)
    check("BOTINOK_TRUECOLOR=0 — выключено",
          run({"TERM": "xterm-256color", "BOTINOK_TRUECOLOR": "0"}) is None)
    check("BOTINOK_TRUECOLOR=1 — force даже на linux tty",
          run({"TERM": "linux", "BOTINOK_TRUECOLOR": "1"}) == "truecolor")
    print("-" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
