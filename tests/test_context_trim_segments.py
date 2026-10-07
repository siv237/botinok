#!/usr/bin/env python3
"""
Тест сегментно-границевого тримма (этап 2 плана
wiki/concepts/context_memory_research.md): _prepare_messages_for_ollama
выбрасывает целыми сегментами, пары assistant.tool_calls ↔ tool не разрывает.

Запуск: venv/bin/python -u tests/test_context_trim_segments.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.textual_integration import _prepare_messages_for_ollama  # noqa: E402

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


def asst_with_tools(tc_ids, content=""):
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": tid, "type": "function",
             "function": {"name": "file_system", "arguments": json.dumps({"action": "read", "path": "x" * 50})}}
            for tid in tc_ids
        ],
    }


def tool_msg(tc_id):
    return {"role": "tool", "tool_call_id": tc_id, "content": "R" * 200}


def assert_no_orphans(trimmed, label):
    declared = set()
    orphans = []
    for m in trimmed:
        if m.get("role") == "assistant":
            for tc in (m.get("tool_calls") or []):
                declared.add(tc.get("id"))
        elif m.get("role") == "tool":
            if m.get("tool_call_id") not in declared:
                orphans.append(m.get("tool_call_id"))
    check(f"no_orphan_tools:{label}", not orphans, str(orphans[:5]))


def build_history():
    msgs = [{"role": "system", "content": "SYSPROMPT " * 30}]
    for s in range(3):
        msgs.append({"role": "user", "content": f"вопрос номер {s} " + "детали " * 40})
        msgs.append(asst_with_tools([f"call_{s}_a"], ""))
        msgs.append(tool_msg(f"call_{s}_a"))
        msgs.append(asst_with_tools([f"call_{s}_b"], ""))
        msgs.append(tool_msg(f"call_{s}_b"))
        msgs.append({"role": "assistant", "content": f"итог сегмента {s} " + "текст " * 40})
    return msgs


def main() -> int:
    # 1) бюджет режет середину: висять tool-сообщений нет, system целы
    msgs = build_history()
    sm = StubSM()
    trimmed = _prepare_messages_for_ollama(sm, "sess", msgs, num_ctx=1700)
    orig_systems = [m for m in trimmed if m.get("role") == "system" and str(m.get("content", "")).startswith("SYSPROMPT")]
    check("systems_intact", len(orig_systems) == 1)
    assert_no_orphans(trimmed, "mid_cut")
    dropped_roles = [m.get("role") for m in msgs if m not in trimmed]
    check("something_dropped", any(r == "tool" for r in dropped_roles), str(dropped_roles[:10]))
    check("artifact_saved", len(sm.artifacts) == 1, str(list(sm.artifacts)))
    art = next(iter(sm.artifacts.values()))
    check("artifact_is_json_list", isinstance(json.loads(art), list))
    check("notice_present", any("сокращён" in str(m.get("content", "")) for m in trimmed if m.get("role") == "system"))
    # вытеснение по границам сегментов: первое kept-сообщение (после notice) — user
    non_sys = [m for m in trimmed if m.get("role") != "system"]
    check("boundary_at_segment_start", non_sys and non_sys[0].get("role") == "user",
          str(non_sys[0].get("role")) if non_sys else "empty")

    # 2) самый свежий сегмент сам больше бюджета — держим последние единицы, пары целы
    sm2 = StubSM()
    trimmed2 = _prepare_messages_for_ollama(sm2, "sess", msgs, num_ctx=256)
    assert_no_orphans(trimmed2, "tiny_budget")
    non_sys2 = [m for m in trimmed2 if m.get("role") != "system"]
    check("kept_something_tiny", len(non_sys2) >= 1, str(len(non_sys2)))
    check("keeps_last_message", msgs[-1] in trimmed2)

    # 3) num_ctx <= 0 — без изменений
    check("no_ctx_passthrough", _prepare_messages_for_ollama(StubSM(), "s", msgs, 0) is msgs)

    # 4) бюджет велик — ничего не выброшено, notice нет
    sm3 = StubSM()
    trimmed3 = _prepare_messages_for_ollama(sm3, "sess", msgs, num_ctx=100000)
    check("no_trim_when_fits", len(trimmed3) == len(msgs) and not sm3.artifacts)

    # 4b) регрессия 2026-10-07: огромный tool-дамп выживал ЕДИНСТВЕННЫЙ user →
    # LiteLLM 400 "No user query found in messages". user обязан остаться.
    litellm_hist = [
        {"role": "system", "content": "SYSPROMPT"},
        {"role": "user", "content": "найди погоду"},
        asst_with_tools(["c1"], ""),
        {"role": "tool", "tool_call_id": "c1", "content": "X" * 60000},
        asst_with_tools(["c2"], ""),
        {"role": "tool", "tool_call_id": "c2", "content": "Y" * 60000},
    ]
    trimmed4 = _prepare_messages_for_ollama(StubSM(), "sess", litellm_hist, num_ctx=2000)
    users = [m for m in trimmed4 if m.get("role") == "user" and str(m.get("content", "")).strip()]
    check("user_anchor_survives_huge_dump", len(users) >= 1, str([m.get("role") for m in trimmed4]))
    assert_no_orphans(trimmed4, "litellm_case")

    # 5) tool без предшествующего assistant (битая история) не роняет тримм
    broken = [{"role": "system", "content": "s"}, {"role": "tool", "tool_call_id": "z", "content": "x" * 500},
              {"role": "user", "content": "u"}]
    tr = _prepare_messages_for_ollama(StubSM(), "s", broken, num_ctx=256)
    check("broken_history_survives", isinstance(tr, list))

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ SEGMENT TRIM ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
