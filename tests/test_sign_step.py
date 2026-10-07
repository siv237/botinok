#!/usr/bin/env python3
"""
Тест харнеса подписаний sign_step (этап 6 плана
wiki/concepts/context_memory_research.md):
  * валидная подпись принимается и кладётся в signatures.json;
  * левая entity → ошибка-ретрай, вторая левая → отказ (механическая строка);
  * goal/done ≤15 слов, status enum с алиасами, entities ≤6;
  * session_digest подхватывает подпись в окно, window_line печатает goal/done;
  * sign_step зарегистрирован в ToolManager.

Запуск: venv/bin/python -u tests/test_sign_step.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import session_digest  # noqa: E402
from tools import sign_step  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "sessions", "20260409_223242_visual_run")

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    if not os.path.isdir(FIXTURE):
        check("fixture_exists", False, FIXTURE)
        return 1

    with tempfile.TemporaryDirectory() as td:
        sess = os.path.join(td, "sess")
        shutil.copytree(FIXTURE, sess)

        # 1) валидная подпись
        sign_step.reset_turn(sess)
        sign_step.observe(sess, ["file_system", "sessions/x/project/main.py", "https://example.com/api"])
        r = sign_step.sign_step_tool(
            goal="разобрать падение тестов", done="нашёл причину в main.py",
            status="progress", entities=["main.py", "https://example.com/api"],
            session_path=sess)
        check("valid_returns_ok", r == "ok", r)
        check("has_signature", sign_step.has_signature(sess))
        sig = sign_step.pop_signature(sess)
        check("sig_fields", sig and sig.get("status") == "progress" and "main.py" in sig.get("entities", []), str(sig))
        check("sig_persisted", os.path.exists(os.path.join(sess, "signatures.json")))
        recs = json.load(open(os.path.join(sess, "signatures.json"), encoding="utf-8"))
        check("sig_window_bound", isinstance(recs, list) and len(recs) == 1 and "window_id" in recs[0], str(recs)[:120])

        # 2) digest подхватывает подпись
        sign_step.reset_turn(sess)
        sign_step.observe(sess, ["web"])
        sign_step.sign_step_tool(goal="качать данные", done="качал", status="answered",
                                 entities=[], session_path=sess)
        windows = session_digest.build_windows(sess)
        signed = [w for w in windows if w.sign]
        check("digest_picks_sign", len(signed) == 1, str(len(signed)))
        if signed:
            line = session_digest.window_line(signed[0])
            check("line_has_goal", "goal: качать данные" in line and "done: качал" in line, line[:200])

        # 3) левая entity: первая — ошибка с именами, вторая — отказ без подписи
        sign_step.reset_turn(sess)
        sign_step.observe(sess, ["file_system", "notes.txt"])
        r1 = sign_step.sign_step_tool(goal="g", done="d", status="progress",
                                      entities=["выдуманная_сутность_qq"], session_path=sess)
        check("bogus_entity_error", "выдуманная_сутность_qq" in r1 and r1 != "ok", r1[:120])
        check("no_sig_after_first_fail", not sign_step.has_signature(sess))
        r2 = sign_step.sign_step_tool(goal="g", done="d", status="progress",
                                      entities=["тоже_левая_zz"], session_path=sess)
        check("second_fail_gives_up", r2 == "ok" and not sign_step.has_signature(sess))
        # отказ = дальше не мучаем
        r3 = sign_step.sign_step_tool(goal="g", done="d", status="progress", entities=[], session_path=sess)
        check("gave_up_stays_ok", r3 == "ok" and not sign_step.has_signature(sess))

        # 4) ретрай с валидными entity после первой ошибки — принимается
        sign_step.reset_turn(sess)
        sign_step.observe(sess, "shell_exec")
        sign_step.sign_step_tool(goal="g", done="d", status="progress", entities=["нет_такого"], session_path=sess)
        r = sign_step.sign_step_tool(goal="g", done="d", status="progress", entities=["shell_exec"], session_path=sess)
        check("retry_valid_ok", r == "ok" and sign_step.has_signature(sess))

        # 5) схема: ≤15 слов, enum с алиасами, entities ≤6 и строковый ввод
        sign_step.reset_turn(sess)
        sign_step.observe(sess, ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"])
        sign_step.sign_step_tool(
            goal="слово " * 20, done="сделано", status="готово",
            entities="a, b; c\nd, e, f, g, h, i, j", session_path=sess)
        sig = sign_step.pop_signature(sess)
        check("goal_truncated_15", len(sig["goal"].split()) <= 15, str(len(sig["goal"].split())))
        check("status_alias", sig["status"] == "answered", sig["status"])
        check("entities_cap_6", len(sig["entities"]) <= 6, str(sig["entities"]))
        sign_step.reset_turn(sess)
        sign_step.sign_step_tool(goal="g", done="d", status="чепуха", entities=[], session_path=sess)
        check("status_default_progress", sign_step.pop_signature(sess)["status"] == "progress")

        # 6) ToolManager: инструмент в определениях и вызывается
        from core.tool_manager import ToolManager
        tm = ToolManager()
        defs = tm.get_tool_definitions()
        names = defs.keys() if isinstance(defs, dict) else [d["function"]["name"] for d in defs]
        check("registered_in_tm", "sign_step" in names, str(list(names)[:20]))

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ SIGN STEP ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
