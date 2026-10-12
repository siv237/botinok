#!/usr/bin/env python3
"""
Относительное время в пикере сессий: «0 дн назад» на вчерашних сессиях
(деление на 604800 вместо 86400) и границы порогов.

Запуск: venv/bin/python -u tests/test_session_picker_time.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session_picker import _relative_time  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    now = time.time()
    cases = [
        (30, "30 сек назад"),
        (120, "2 мин назад"),
        (7200, "2 час назад"),
        (86400 + 60, "1 дн назад"),
        (2 * 86400, "2 дн назад"),
        (6 * 86400, "6 дн назад"),
        (7 * 86400, "1 нед назад"),
        (20 * 86400, "2 нед назад"),
    ]
    for age, want in cases:
        got = _relative_time(now - age)
        check(f"{age // 3600}ч → «{want}»", got == want, f"получено «{got}»")
    check("пустой ts", _relative_time(None) == "нет данных")
    print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if not FAILURES else 'ПРОВАЛЫ: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
