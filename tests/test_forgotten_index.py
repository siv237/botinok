#!/usr/bin/env python3
"""
Тест блока FORGOTTEN_INDEX (этап 3 плана wiki/concepts/context_memory_research.md):
  * блок собирается по вытеснённым окнам, в бюджете токенов, детерминирован;
  * _prepare_messages_for_ollama вставляет блок вместо notice (артефакт — как было);
  * после overflow-reset (история = system + протокол без таймстампов) блок
    сохраняется и содержит все окна;
  * fallback notice, когда Digest недоступен (нет папки сессии).

Запуск: venv/bin/python -u tests/test_forgotten_index.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import session_digest  # noqa: E402
from core.textual_integration import (  # noqa: E402
    FORGOTTEN_BLOCK_BUDGET,
    _build_forgotten_block,
    _estimate_tokens,
    _prepare_messages_for_ollama,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "sessions", "20260409_223242_visual_run")

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
    if not os.path.isdir(FIXTURE):
        check("fixture_exists", False, FIXTURE)
        return 1

    windows = session_digest.build_windows(FIXTURE)
    mid_ts = windows[len(windows) // 2].ts_end

    # 1) блок по середине сессии
    block = _build_forgotten_block(FIXTURE, mid_ts)
    check("block_not_empty", bool(block))
    check("block_header", block.startswith("FORGOTTEN_INDEX"))
    check("block_has_cloud", "☁" in block)
    check("block_has_pointer", "get_turn turn_id=" in block or "context.json#msg=" in block)
    check("block_within_budget", _estimate_tokens(block) <= FORGOTTEN_BLOCK_BUDGET,
          str(_estimate_tokens(block)))
    check("block_deterministic", block == _build_forgotten_block(FIXTURE, mid_ts))
    n_forgotten = sum(1 for w in windows if w.ts_end <= mid_ts)
    n_lines = sum(1 for l in block.splitlines() if l.startswith("## "))
    check("block_covers_forgotten", n_lines >= min(n_forgotten, 3), f"{n_lines} vs {n_forgotten}")

    # 2) все окна (якорь пустой — как после overflow-reset)
    full = _build_forgotten_block(FIXTURE, "")
    check("full_block_all_windows", _estimate_tokens(full) <= FORGOTTEN_BLOCK_BUDGET and "☁" in full,
          str(_estimate_tokens(full)))

    # 3) интеграция с триммом: реальные сообщения с таймстампами fixture
    history = json.load(open(os.path.join(FIXTURE, "context.json")))["history"]
    msgs = [{"role": "system", "content": "SYSPROMPT"}] + history
    sm = StubSM()
    trimmed = _prepare_messages_for_ollama(sm, FIXTURE, msgs, num_ctx=1200)
    block_msgs = [m for m in trimmed if str(m.get("content", "")).startswith("FORGOTTEN_INDEX")]
    check("trim_inserts_block", len(block_msgs) == 1, str(len(block_msgs)))
    check("trim_no_duplicate_block", len([m for m in trimmed if "FORGOTTEN_INDEX" in str(m.get("content", ""))]) == 1)
    check("trim_artifact_saved", len(sm.artifacts) == 1)
    check("trim_notice_replaced", not any("автоматически сокращён" in str(m.get("content", "")) for m in trimmed))
    kept_ts = sorted(str(m.get("timestamp") or "") for m in trimmed if m.get("role") != "system" and m.get("timestamp"))
    if kept_ts and block_msgs:
        import re as _re
        times = _re.findall(r"## \[(\d\d:\d\d:\d\d)\]", str(block_msgs[0].get("content", "")))
        check("block_anchored_before_kept",
              all(t <= kept_ts[0][11:19] for t in times), f"{times[:3]} vs {kept_ts[0][11:19]}")

    # 4) overflow-reset симуляция: история = system + протокол (без ts) — блок на месте
    protocol = {"role": "system", "content": "SESSION_PROTOCOL ..."}
    sm2 = StubSM()
    trimmed2 = _prepare_messages_for_ollama(sm2, FIXTURE, [msgs[0], protocol], num_ctx=1200)
    check("block_survives_reset",
          any(str(m.get("content", "")).startswith("FORGOTTEN_INDEX") for m in trimmed2))
    check("reset_no_artifact", not sm2.artifacts)

    # 5) fallback notice, когда digest недоступен
    sm3 = StubSM()
    big = [{"role": "system", "content": "s"}] + [
        {"role": "user", "content": "u " * 300},
        {"role": "assistant", "content": "a " * 300},
    ] * 10
    trimmed3 = _prepare_messages_for_ollama(sm3, "/nonexistent/session", big, num_ctx=300)
    check("fallback_notice", any("автоматически сокращён" in str(m.get("content", "")) for m in trimmed3))

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ FORGOTTEN INDEX ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
