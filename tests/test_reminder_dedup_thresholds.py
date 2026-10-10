#!/usr/bin/env python3
"""
Тест фикса шторма ресетов (регресс 2026-10-10, сессия 20261010_202930):
1. _append_system_once — дедуп служебных system-реплик (TOOL_USAGE_REMINDER);
2. бюджет тримма лежит НИЖЕ хард-триггера HARD_CTX_PCT·num_ctx — сегментный
   тримм успевает раньше big-bang-ресета;
3. _ollama_summarize_and_reset_context не копит старые протоколы ресета;
4. load_messages_snapshot самолечит снапшоты с сотнями дублей памяток.

Запуск: venv/bin/python -u tests/test_reminder_dedup_thresholds.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.textual_integration as ti  # noqa: E402
from core.textual_integration import (  # noqa: E402
    HARD_CTX_PCT,
    _append_system_once,
    _estimate_messages_tokens,
    _ollama_summarize_and_reset_context,
    _prepare_messages_for_ollama,
)
from core.session_manager import SessionManager  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class StubConfig:
    def get(self, section, option, fallback=None):
        return fallback

    def getboolean(self, section, option, fallback=None):
        return fallback


class StubSM:
    def __init__(self):
        self.config = StubConfig()
        self.artifacts = {}

    def save_artifact(self, session_path, name, data):
        self.artifacts[name] = data
        return f"{session_path}/artifacts/{name}"

    def load_prompt(self, session_path, name, **kw):
        if name == "context_overflow_protocol":
            return ("Контекст был очищен из-за риска переполнения/зацикливания.\n"
                    f"Полная история: {kw.get('ARTIFACT_PATH', '')}\n"
                    f"{kw.get('SESSION_PROTOCOL', '')}")
        return f"[{name}]"


def test_append_system_once():
    msgs = []
    check("appends_first", _append_system_once(msgs, "ПАМЯТКА") and len(msgs) == 1)
    check("skips_duplicate", not _append_system_once(msgs, "ПАМЯТКА") and len(msgs) == 1)
    for _ in range(300):
        _append_system_once(msgs, "ПАМЯТКА")
    check("no_growth_300_calls", len(msgs) == 1)
    check("distinct_kept", _append_system_once(msgs, "ДРУГАЯ") and len(msgs) == 2)
    check("empty_ignored", not _append_system_once(msgs, "   ") and len(msgs) == 2)


def test_budget_below_hard_trigger():
    num_ctx = 262144
    hard = int(num_ctx * HARD_CTX_PCT)
    # история, которая влезала бы в старый бюджет (num_ctx−1200), но превышает
    # новый (0.9·num_ctx−1200): тримм обязан сработать, не дожидаясь ресета
    per = 4000
    n = (hard // (per // 4)) + 20
    msgs = [{"role": "system", "content": "SYSP"}]
    for i in range(n):
        msgs.append({"role": "user", "content": f"q{i} " + "д" * per})
    est = _estimate_messages_tokens(msgs)
    check("history_above_new_budget", est > hard - 1200, f"est={est}")
    check("history_below_old_budget", est < num_ctx - 1200, f"est={est}")
    trimmed = _prepare_messages_for_ollama(StubSM(), "sess", msgs, num_ctx=num_ctx)
    check("trim_fires_before_hard_reset", len(trimmed) < len(msgs),
          f"{len(trimmed)}/{len(msgs)}")
    est_after = _estimate_messages_tokens(trimmed)
    check("trimmed_within_hard_threshold", est_after <= hard, f"est_after={est_after}")
    check("keeps_latest", msgs[-1] in trimmed)


def test_reset_drops_old_protocols():
    sm = StubSM()
    msgs = [
        {"role": "system", "content": "IDENTITY"},
        {"role": "system", "content": "Контекст был очищен из-за риска переполнения/зацикливания.\nПолная история: a1\nпротокол-1"},
        {"role": "system", "content": "Контекст был очищен из-за риска переполнения/зацикливания.\nПолная история: a2\nпротокол-2"},
        {"role": "system", "content": "Context cleared. Continue task: old"},
        {"role": "user", "content": "задача"},
        {"role": "assistant", "content": "работа"},
    ]
    orig_is_openai = ti.is_openai_backend
    orig_chat_once = ti.chat_once
    ti.is_openai_backend = lambda sm: True
    ti.chat_once = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("offline"))
    try:
        summary, artifact = _ollama_summarize_and_reset_context(
            sm, "test-model", "sess", msgs, 262144, reason="test")
    finally:
        ti.is_openai_backend = orig_is_openai
        ti.chat_once = orig_chat_once
    protocols = [m for m in msgs if m.get("role") == "system"
                 and str(m.get("content", "")).lstrip().startswith(ti.OVERFLOW_PROTOCOL_MARKERS)]
    check("exactly_one_protocol_after_reset", len(protocols) == 1, str(len(protocols)))
    check("identity_survives", any(m.get("content") == "IDENTITY" for m in msgs))
    check("history_cleared", all(m.get("role") not in ("user", "assistant") for m in msgs))
    check("artifact_saved", bool(artifact))


def test_snapshot_selfheal():
    with tempfile.TemporaryDirectory() as d:
        dup = {"role": "system", "content": "TOOL_USAGE_REMINDER:\nпамятка"}
        payload = {"version": 1, "messages": [
            {"role": "system", "content": "IDENTITY"},
            dup,
            *[dict(dup) for _ in range(324)],
            {"role": "user", "content": "q"},
        ]}
        with open(os.path.join(d, "messages.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        sm = SessionManager.__new__(SessionManager)
        restored = sm.load_messages_snapshot(d)
        reminders = [m for m in restored if str(m.get("content", "")).startswith("TOOL_USAGE_REMINDER")]
        check("snapshot_deduped_to_one", len(reminders) == 1, str(len(reminders)))
        check("snapshot_order_kept", restored[0]["content"] == "IDENTITY" and restored[-1]["role"] == "user")


def main() -> int:
    print("== _append_system_once ==")
    test_append_system_once()
    print("== бюджет тримма ниже хард-триггера ==")
    test_budget_below_hard_trigger()
    print("== ресет не копит протоколы ==")
    test_reset_drops_old_protocols()
    print("== самопочинка снапшота ==")
    test_snapshot_selfheal()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ DEDUP/THRESHOLDS ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
