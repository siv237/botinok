#!/usr/bin/env python3
"""
Регресс: get_turn(include_content=true) не должен сжигать контекст.

Боевой кейс (сессия 20261007_222243): ход из 48 tool-вызовов, get_turn вернул
101 КБ полных результатов → переполнение → модель бросила session_memory и
полезла в file_system. Теперь результаты инструментов — превью + артефакт,
полные тексты только по include_results=true.

Запуск: venv/bin/python -u tests/test_get_turn_compact.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.session_memory import session_memory_tool  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _make_session() -> str:
    sess = tempfile.mkdtemp(prefix="botinok_gt_")
    tool_calls = []
    n_tools = 12
    for i in range(n_tools):
        tool_calls.append({"id": f"call_{i}", "type": "function",
                           "function": {"name": "web", "arguments": json.dumps({"action": "get", "url": f"http://x/{i}"})}})
    history = [
        {"role": "user", "content": "собери данные", "timestamp": "2026-10-07T22:23:19.000000"},
        {"role": "assistant", "content": "готово", "timestamp": "2026-10-07T22:28:04.000000",
         "tool_calls": tool_calls},
    ]
    with open(os.path.join(sess, "context.json"), "w", encoding="utf-8") as f:
        json.dump({"history": history}, f, ensure_ascii=False)
    with open(os.path.join(sess, "tools.log"), "w", encoding="utf-8") as f:
        for i in range(n_tools):
            big = f"BIGRESULT_{i}_" + ("д" * 40000)
            f.write(json.dumps({
                "timestamp": "2026-10-07T22:25:00.000000", "tool": "web",
                "arguments": {"action": "get", "url": f"http://x/{i}"},
                "status": "completed", "call_id": f"call_{i}",
                "full_result": f"TOOL_RESULT_SUMMARY\ntool: web\nartifact_path: ./artifacts/tool_web_call_{i}.txt\ncontent_preview:\n{big}",
            }, ensure_ascii=False) + "\n")
    return sess


def main() -> int:
    sess = _make_session()

    out = session_memory_tool(action="get_turn", turn_id=1, include_content=True,
                              session_path=sess)
    out = str(out)
    check("compact_default", len(out) < 20000, f"len={len(out)}")
    check("preview_present", "preview:" in out or "result_preview" in out)
    check("artifact_pointers", "artifact:" in out)
    check("huge_results_hidden", "д" * 1000 not in out)
    check("hint_include_results", "include_results=true" in out)

    out_full = session_memory_tool(action="get_turn", turn_id=1, include_content=True,
                                   include_results=True, session_path=sess)
    out_full = str(out_full)
    check("include_results_works", "BIGRESULT_0_" in out_full, f"len={len(out_full)}")

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ GET_TURN COMPACT ТЕСТ ПРОЙДЕН")
    return 0


def test_all() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
