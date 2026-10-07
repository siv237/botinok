#!/usr/bin/env python3
"""
Тест pressure-инжекта с гистерезисом (этап 5 плана
wiki/concepts/context_memory_research.md): строка уровня один раз при пересечении
70%/85%, не повторяется до сброса, живёт внутри TOOL_RESULT_SUMMARY.

Запуск: venv/bin/python -u tests/test_pressure_inject.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.textual_integration import (  # noqa: E402
    _compact_tool_message,
    _pressure_note,
    reset_context_pressure,
    set_context_pressure,
)

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    # 1) ниже порога — тишина
    reset_context_pressure()
    set_context_pressure(0.5)
    check("silent_below_70", _pressure_note() == "")

    # 2) пересечение 70% — одно сообщение, повтор подавлен
    set_context_pressure(0.72)
    n1 = _pressure_note()
    check("fires_at_70", "CONTEXT_PRESSURE" in n1 and "70%" in n1, n1)
    check("no_repeat_70", _pressure_note() == "")

    # 3) пересечение 85% — следующее сообщение, повтор подавлен
    set_context_pressure(0.87)
    n2 = _pressure_note()
    check("fires_at_85", "CONTEXT_PRESSURE" in n2 and "85%" in n2, n2)
    check("no_repeat_85", _pressure_note() == "")

    # 4) падение доли не сбрасывает гистерезис сам по себе
    set_context_pressure(0.5)
    check("no_note_after_drop_without_reset", _pressure_note() == "")
    set_context_pressure(0.72)
    check("still_suppressed", _pressure_note() == "")

    # 5) явный сброс (финал хода / overflow-reset) — уровни снова стреляют
    reset_context_pressure()
    set_context_pressure(0.72)
    check("refires_after_reset", "70%" in _pressure_note())

    # 6) прыжок сразу на 85% — только верхний уровень
    reset_context_pressure()
    set_context_pressure(0.9)
    n = _pressure_note()
    check("jump_straight_to_85", "85%" in n and "70%" not in n, n)
    check("jump_no_second_note", _pressure_note() == "")

    # 7) инжект внутрь TOOL_RESULT_SUMMARY
    reset_context_pressure()
    set_context_pressure(0.87)
    msg = _compact_tool_message("file_system", {"action": "read"}, "x" * 100, "/tmp/a.json")
    check("summary_starts_marker", msg.startswith("TOOL_RESULT_SUMMARY"))
    check("note_inside_summary", "CONTEXT_PRESSURE" in msg, msg[-120:])
    reset_context_pressure()
    msg2 = _compact_tool_message("file_system", {"action": "read"}, "x" * 100, "/tmp/a.json")
    check("no_note_when_calm", "CONTEXT_PRESSURE" not in msg2)

    # 8) мусор в ratio не роняет
    reset_context_pressure()
    set_context_pressure(None)
    set_context_pressure("abc")
    check("garbage_ratio_safe", _pressure_note() == "")

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ PRESSURE INJECT ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
