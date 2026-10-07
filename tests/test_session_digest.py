#!/usr/bin/env python3
"""
Тест механического дайджеста сессий (core/session_digest.py), этап 1 плана
wiki/concepts/context_memory_research.md:
  * число окон == числу metrics-событий session_raw.log;
  * облако непустое на содержательных окнах (пустое — только на пустых ходах);
  * все completed-события tools.log привязаны к окнам;
  * детерминизм (два прогона — равный вывод);
  * формат строк индекса и иерархическое сжатие merge_old_lines;
  * fallback-стеммер без pymorphy3.

Запуск: venv/bin/python -u tests/test_session_digest.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import session_digest as sd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = [
    os.path.join(ROOT, "sessions", "20260409_223242_visual_run"),
    os.path.join(ROOT, "sessions", "20260409_230600_visual_run"),
]

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def count_metrics(session_path: str) -> int:
    n = 0
    for ev in sd._iter_jsonl(os.path.join(session_path, "session_raw.log")):
        if ev.get("type") == "metrics":
            n += 1
    return n


def count_completed_tools(session_path: str) -> int:
    return sum(
        1 for ev in sd._iter_jsonl(os.path.join(session_path, "tools.log"))
        if ev.get("status") == "completed"
    )


def main() -> int:
    for fx in FIXTURES:
        name = os.path.basename(fx)
        if not os.path.isdir(fx):
            check(f"fixture_exists:{name}", False, fx)
            continue
        windows = sd.build_windows(fx)

        check(f"windows_eq_metrics:{name}",
              len(windows) == count_metrics(fx),
              f"{len(windows)} vs {count_metrics(fx)}")

        bound = sum(len(w.tools) for w in windows)
        total = count_completed_tools(fx)
        check(f"all_tools_bound:{name}", bound == total, f"{bound} vs {total}")

        substantive = [w for w in windows if w.final_text.strip() or w.tools or w.call_args]
        empty_sub = [w.window_id for w in substantive if not sd.window_cloud(w)]
        check(f"cloud_nonempty_on_substantive:{name}", not empty_sub, str(empty_sub[:5]))

        lines1 = sd.build_digest_lines(sd.build_windows(fx))
        lines2 = sd.build_digest_lines(sd.build_windows(fx))
        check(f"deterministic:{name}", lines1 == lines2)

        header_lines = [l for l in lines1 if l.startswith("## ")]
        fmt_ok = all(("☁" in l and l[3:4] == "[") for l in header_lines)
        tail_ok = all("ctx=" in l for l in lines1 if l.startswith("   "))
        check(f"line_format:{name}", fmt_ok and tail_ok and len(header_lines) == len(windows))

        # указатели: хотя бы у части окон есть turn/msg-указатель
        with_ptr = sum(1 for w in windows if w.turn_ids or w.msg_indices)
        check(f"pointers_present:{name}", with_ptr >= len(windows) // 2, f"{with_ptr}/{len(windows)}")

    # merge_old_lines: счётчик окон и частотные термины
    ws = sd.build_windows(FIXTURES[0]) if os.path.isdir(FIXTURES[0]) else []
    if ws:
        lines = sd.build_digest_lines(ws)
        merged = sd.merge_old_lines(lines)
        check("merge_counts_windows", f"×{len(ws)}" in merged, merged)
        check("merge_has_terms", "☁" in merged and len(merged.split("☁")[1].split()) > 0, merged)

    # fallback-стеммер без pymorphy3
    saved = sd._MORPH
    try:
        sd._MORPH = None
        stem = sd.lemmatize("погоды")
        check("fallback_stemmer", bool(stem) and stem.startswith("погод"), str(stem))
        check("fallback_drops_short", sd.lemmatize("дом") is None)
    finally:
        sd._MORPH = saved

    # pymorphy3 (если установлен) даёт нормальную форму
    if saved is not None:
        check("pymorphy_lemma", sd.lemmatize("погоды") == "погода", str(sd.lemmatize("погоды")))
        check("pymorphy_drops_stopword_pos", sd.lemmatize("очень") is None)

    # пустая/битая сессия не роняет модуль
    check("missing_session_empty", sd.build_windows("/nonexistent/session") == [])

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ SESSION DIGEST ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
