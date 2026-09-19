#!/usr/bin/env python3
"""
Защита от «молчаливого» обрыва ответа.

Модель может вернуть полностью пустое завершение (нет content, thinking и
tool_calls), хотя бэкенд насчитал токены. Раньше это молча сохранялось как
финальный ответ и гасило ход. Проверяем классификатор и наличие ограниченного
авто-повтора.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.textual_integration import (  # noqa: E402
    _is_empty_completion,
    MAX_EMPTY_RETRIES_PER_TURN,
)

FAILURES = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("Empty-completion guard smoke-test")
    print("=" * 70)

    # 1. Полностью пустое завершение — это сбой, а не ответ.
    check("empty_all", _is_empty_completion("", "", []))
    check("whitespace", _is_empty_completion("   \n\t ", None, None))
    check("none_values", _is_empty_completion(None, None, None))

    # 2. Всё остальное — не пустое (нормальный ответ / reasoning / tool-call).
    check("text_present", not _is_empty_completion("ответ", "", []))
    check("thinking_only", not _is_empty_completion("", "размышление", []))
    check("tool_calls_only", not _is_empty_completion("", "", [{"id": "c1"}]))

    # 3. Повтор ограничен, чтобы не зациклиться на «тупящей» модели.
    check("retries_bounded", isinstance(MAX_EMPTY_RETRIES_PER_TURN, int)
          and 1 <= MAX_EMPTY_RETRIES_PER_TURN <= 10, str(MAX_EMPTY_RETRIES_PER_TURN))

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ EMPTY-COMPLETION GUARD SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
