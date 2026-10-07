#!/usr/bin/env python3
"""
Тест мемо каталогов (купирование повторных skills/experience list после
overflow-reset): первый вызов кэшируется в артефакт, повтор — короткая памятка,
другие инструменты/действия не затронуты.

Запуск: venv/bin/python -u tests/test_catalog_memo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import textual_integration as ti  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class StubSM:
    def __init__(self):
        self.artifacts = {}

    def save_artifact(self, session_path, name, data):
        self.artifacts[name] = data
        return f"{session_path}/artifacts/{name}"


def main() -> int:
    ti._catalog_memo.clear()
    sm = StubSM()
    sess = "/tmp/sess_x"

    # 1) первый вызов — мемo нет, результат сохраняется
    check("first_call_no_memo", ti._catalog_memo_check(sess, "skills", {"action": "list"}) is None)
    ti._catalog_memo_store(sess, "skills", {"action": "list"}, "SKILLS " * 500, sm)
    check("artifact_saved", len(sm.artifacts) == 1)

    # 2) повтор — памятка с указателем, короткая
    memo = ti._catalog_memo_check(sess, "skills", {"action": "list"})
    check("repeat_gets_memo", memo is not None and "CATALOG_CACHED" in memo, str(memo)[:80])
    check("memo_short", memo is not None and len(memo) < 400, str(len(memo or "")))
    check("memo_points_artifact", memo is not None and "artifacts/catalog_skills_" in memo)

    # 3) другие инструменты и действия не мемоизируются
    check("other_tool_pass", ti._catalog_memo_check(sess, "web", {"action": "list"}) is None)
    check("other_action_pass", ti._catalog_memo_check(sess, "skills", {"action": "get", "name": "x"}) is None)
    check("experience_memoized", (ti._catalog_memo_store(sess, "experience", {"action": "list"}, "EXP", sm),
                                  ti._catalog_memo_check(sess, "experience", {"action": "list"}) is not None)[1])

    # 4) разные аргументы — разные ключи
    check("different_args_different_key",
          ti._catalog_memo_check(sess, "skills", {"action": "list", "scope": "project"}) is None)

    # 5) пустой результат не кэшируется
    ti._catalog_memo_store(sess, "skills", {"action": "list", "fresh": True}, "", sm)
    check("empty_result_not_cached",
          ti._catalog_memo_check(sess, "skills", {"action": "list", "fresh": True}) is None)

    # 6) изоляция по сессиям
    check("session_isolated", ti._catalog_memo_check("/tmp/other_sess", "skills", {"action": "list"}) is None)

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ CATALOG MEMO ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
