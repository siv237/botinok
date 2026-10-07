#!/usr/bin/env python3
"""
Тест мелочей памяти (этап 8 плана wiki/concepts/context_memory_research.md):
  * word_index: кириллица и леммы; .idx с новым полем lemmas_index, старые .idx грузятся;
  * action=windows: те же окна/строки, что у FORGOTTEN_INDEX (общий код);
  * дедуп user-реплик при записи в update_context (raw чище), настоящий повтор остаётся.

Запуск: venv/bin/python -u tests/test_memory_small_fixes.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session_manager import SessionManager  # noqa: E402
from tools import session_memory as smem  # noqa: E402

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

    # 1) _extract_words: кириллица + леммы
    idx = smem.SessionIndex.__new__(smem.SessionIndex)
    words = smem.SessionIndex._extract_words(idx, "Проверка погоды в Хабаровске и file_system action")
    check("ascii_word", "file_system" in words, str(sorted(words)[:10]))
    check("cyrillic_word", "погоды" in words, str(sorted(words)[:10]))
    if smem._lemmatize is not None:
        check("lemma_present", "погода" in words, str(sorted(words)[:10]))
        check("lemma_habarovsk", "хабаровск" in words)

    # 2) индекс на диске: lemmas_index + совместимость со старым форматом
    with tempfile.TemporaryDirectory() as td:
        sess = os.path.join(td, "sess")
        shutil.copytree(FIXTURE, sess)
        idx2 = smem.SessionIndex(sess)
        idx2.build()
        idx_path = idx2.index_path
        check("idx_written", os.path.exists(idx_path))
        data = json.load(open(idx_path, encoding="utf-8"))
        check("lemmas_index_field", "lemmas_index" in data)
        check("lemmas_have_cyrillic", any("погод" in w for w in data.get("lemmas_index", {})),
              str(list(data.get("lemmas_index", {}))[:5]))
        # старый .idx без lemmas_index должен грузиться
        data.pop("lemmas_index")
        json.dump(data, open(idx_path, "w", encoding="utf-8"))
        idx3 = smem.SessionIndex(sess)
        check("old_idx_loads", idx3.get_turns() is not None)

    # 3) action=windows — общий код с дайджестом
    from core import session_digest
    n_metrics = sum(1 for _ in session_digest.build_windows(FIXTURE))
    out = json.loads(smem.session_memory_tool(action="windows", session_path=FIXTURE, limit=5))
    check("windows_count", out.get("count") == n_metrics, f"{out.get('count')} vs {n_metrics}")
    check("windows_returned", len(out.get("windows", [])) == 5)
    check("windows_lines_paired", len(out.get("lines", [])) == 10)
    check("windows_have_cloud", any("☁" in l for l in out.get("lines", [])))
    check("windows_alias_digest", json.loads(smem.session_memory_tool(action="digest", session_path=FIXTURE)).get("count") == n_metrics)
    w0 = out["windows"][0]
    check("window_fields", all(k in w0 for k in ("window_id", "ts_end", "ctx", "turn_ids", "tools")), str(w0))

    # 4) дедуп user-реплик в update_context
    sm = SessionManager()
    with tempfile.TemporaryDirectory() as td:
        sess = os.path.join(td, "s1")
        os.makedirs(sess)
        sm.update_context(sess, "user", "найди погоду")
        sm.update_context(sess, "user", "найди погоду")  # дубль до ответа — гасится
        sm.update_context(sess, "assistant", "", tool_calls=[{"id": "c1", "function": {"name": "t", "arguments": "{}"}}])
        sm.update_context(sess, "user", "найди погоду")  # всё ещё без содержательного ответа — гасится
        h = sm.load_history_entries(sess)
        user_n = sum(1 for m in h if m.get("role") == "user")
        check("dup_suppressed_before_answer", user_n == 1, f"user={user_n}")
        sm.update_context(sess, "assistant", "Погода ясная.")  # содержательный ответ
        sm.update_context(sess, "user", "найди погоду")  # настоящий повтор — остаётся
        h = sm.load_history_entries(sess)
        user_n = sum(1 for m in h if m.get("role") == "user")
        check("real_repeat_kept", user_n == 2, f"user={user_n}")
        # разные реплики не дедеплятся
        sm.update_context(sess, "user", "а завтра?")
        h = sm.load_history_entries(sess)
        check("different_user_kept", sum(1 for m in h if m.get("role") == "user") == 3)
        # tool-записи не затронуты
        sm.update_context(sess, "tool", "r1", tool_call_id="c1")
        sm.update_context(sess, "tool", "r1", tool_call_id="c1")
        h = sm.load_history_entries(sess)
        check("tool_consec_dedup", sum(1 for m in h if m.get("role") == "tool") == 1)

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ MEMORY SMALL FIXES ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
