#!/usr/bin/env python3
"""
Осознанная компакция контекста (запрос модели) + карта контекста + дедуп.

Проверяет: parse_block_ids, нумерацию блоков _context_blocks,
apply_pending_compacts (рельсы: текущий ход, мелкие блоки, неизвестные id,
заглушка, артефакт, статистика), write_context_map, действия session_memory
context_map/compact/context_stats.

Запуск: venv/bin/python -u tests/test_context_compact.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import textual_integration as ti  # noqa: E402
from tools.session_memory import parse_block_ids  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeSM:
    def __init__(self):
        self.artifacts = []

    def save_artifact(self, session_path, name, content):
        p = os.path.join(session_path, "artifacts", name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        self.artifacts.append(p)
        return p


def make_messages():
    """system + 3 блока; блоки 1-2 крупные, 3 — текущий ход."""
    big = "x" * 40000  # ≈10k токенов
    return [
        {"role": "system", "content": "BOTINOK identity"},
        {"role": "user", "content": "первая задача"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "file_system", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "file_system", "content": big},
        {"role": "assistant", "content": "готово по первой"},
        {"role": "user", "content": "вторая задача"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c2", "function": {"name": "journal", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c2", "name": "journal", "content": big},
        {"role": "assistant", "content": "готово по второй"},
        {"role": "user", "content": "текущая задача"},
        {"role": "assistant", "content": "думаю"},
    ]


def test_parse_block_ids():
    check("ranges", parse_block_ids("1,3-5") == [1, 3, 4, 5])
    check("lists", parse_block_ids([1, "4-5"]) == [1, 4, 5])
    check("int", parse_block_ids(7) == [7])
    check("junk", parse_block_ids("a,,3-x") == [])
    check("mixed_junk", parse_block_ids("a,3,b") == [3])
    check("none", parse_block_ids(None) == [])
    check("reverse", parse_block_ids("5-3") == [3, 4, 5])


def test_context_blocks():
    msgs = make_messages()
    blocks = ti._context_blocks(msgs)
    check("three_blocks", len(blocks) == 3, str(len(blocks)))
    check("ids_sequential", [b["id"] for b in blocks] == [1, 2, 3])
    check("tools_collected", blocks[0]["tools"] == ["file_system"]
          and blocks[1]["tools"] == ["journal"])
    check("preview", blocks[0]["user_preview"] == "первая задача")
    check("big_blocks_cost", blocks[0]["tokens"] > 9000, str(blocks[0]["tokens"]))


def test_apply_compacts():
    d = tempfile.mkdtemp(prefix="compact_test_")
    try:
        sm = FakeSM()
        msgs = make_messages()
        num_ctx = 40000
        stats0 = ti.get_compression_stats()

        with open(os.path.join(d, "compact_request.json"), "w", encoding="utf-8") as f:
            json.dump({"blocks": "1,2,3,9", "note": "файл отработан"}, f)

        stub, brief = ti.apply_pending_compacts(sm, d, msgs, num_ctx)
        check("stub_returned", "COMPACTED_BLOCKS" in stub, stub[:120])
        check("stub_structured", "\n• " in stub, repr(stub[:160]))
        check("brief_short", "−" in brief and "ток." in brief and "\n" not in brief, brief)
        check("freed_reported", "освобождено" in stub and "%" in stub, stub)
        check("note_kept", "файл отработан" in stub)
        check("current_protected", "текущий ход не тронут (3)" in stub, stub)
        check("unknown_reported", "нет блоков 9" in stub, stub)

        # блоки 1-2 удалены: user-реплик «первая/вторая» не осталось
        texts = " ".join(str(m.get("content") or "") for m in msgs)
        check("blocks_dropped", "первая задача" not in texts and "вторая задача" not in texts)
        check("current_kept", "текущая задача" in texts)
        check("stub_in_messages", any("COMPACTED_BLOCKS" in str(m.get("content"))
                                      and m.get("role") == "system" for m in msgs))
        check("pairs_intact", all(
            m.get("role") != "tool" or any(
                tc.get("id") == m.get("tool_call_id")
                for a in msgs if a.get("tool_calls") for tc in a["tool_calls"])
            for m in msgs if isinstance(m, dict)))

        check("artifact_saved", len(sm.artifacts) == 1)
        if sm.artifacts:
            with open(sm.artifacts[0], encoding="utf-8") as f:
                dropped = json.load(f)
            check("artifact_has_dropped", any("первая задача" in str(m.get("content"))
                                              for m in dropped))

        stats1 = ti.get_compression_stats()
        check("stats_manual", stats1["manual"] == stats0.get("manual", 0) + 1)
        check("stats_tokens_grew", stats1["tokens"] > stats0["tokens"])
        check("request_consumed", not os.path.exists(os.path.join(d, "compact_request.json")))

        # повторного применения нет: запроса нет → пустой результат
        check("no_request_noop", ti.apply_pending_compacts(sm, d, msgs, num_ctx) == ("", ""))

        # мелкие блоки (<2% num_ctx) не сжимаются
        msgs2 = make_messages()
        with open(os.path.join(d, "compact_request.json"), "w", encoding="utf-8") as f:
            json.dump({"blocks": "3"}, f)  # только текущий
        s2, _ = ti.apply_pending_compacts(sm, d, msgs2, num_ctx)
        check("only_current_skipped", "ничего не сжато" in s2, s2)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_small_block_skip():
    d = tempfile.mkdtemp(prefix="compact_small_")
    try:
        sm = FakeSM()
        msgs = make_messages()
        # num_ctx огромный → блоки 1-2 «мелкие» (<2%)
        with open(os.path.join(d, "compact_request.json"), "w", encoding="utf-8") as f:
            json.dump({"blocks": "1-2"}, f)
        s, _ = ti.apply_pending_compacts(sm, d, msgs, 5_000_000)
        check("small_skipped", "мелкие блоки пропущены" in s and "1,2" in s, s)
        texts = " ".join(str(m.get("content") or "") for m in msgs)
        check("small_kept", "первая задача" in texts)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_write_context_map():
    d = tempfile.mkdtemp(prefix="ctxmap_test_")
    try:
        msgs = make_messages()
        ti.write_context_map(d, msgs, 40000)
        with open(os.path.join(d, "context_map.json"), encoding="utf-8") as f:
            cm = json.load(f)
        check("map_num_ctx", cm["num_ctx"] == 40000)
        check("map_blocks", len(cm["blocks"]) == 3)
        check("map_used_pct", cm["used_pct"] > 0)
        check("map_stats_present", "compression_stats" in cm)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_session_memory_actions():
    from tools.session_memory import session_memory_tool
    d = tempfile.mkdtemp(prefix="smem_test_")
    try:
        with open(os.path.join(d, "context.json"), "w", encoding="utf-8") as f:
            json.dump({"history": []}, f)

        # compact → пишет compact_request.json
        out = session_memory_tool(action="compact", session_path=d,
                                  blocks="1,4-5", note="краш-тест")
        check("compact_queued", '"queued": true' in out or "queued" in out, out[:200])
        rp = os.path.join(d, "compact_request.json")
        check("compact_request_written", os.path.exists(rp))
        if os.path.exists(rp):
            with open(rp, encoding="utf-8") as f:
                req = json.load(f)
            check("compact_blocks_parsed", req["blocks"] == [1, 4, 5])
            check("compact_note", req["note"] == "краш-тест")

        # compact без блоков → подсказка, не ошибка-молчание
        out2 = session_memory_tool(action="compact", session_path=d)
        check("compact_needs_blocks", "не указаны блоки" in out2, out2[:200])

        # context_map без файла → дружелюбная ошибка
        out3 = session_memory_tool(action="context_map", session_path=d)
        check("map_missing_hint", "не построена" in out3, out3[:200])

        # context_map с файлом → блоки и hint про compact
        ti.write_context_map(d, make_messages(), 40000)
        out4 = session_memory_tool(action="context_map", session_path=d)
        check("map_shows_blocks", "user_preview" in out4 and "compact" in out4, out4[:300])

        # context_stats без окон → «считать нечего»
        out5 = session_memory_tool(action="context_stats", session_path=d)
        check("stats_empty_hint", "считать нечего" in out5, out5[:200])

        # алиасы
        out6 = session_memory_tool(action="карта", session_path=d)
        check("alias_cyrillic", "user_preview" in out6 or "не построена" in out6, out6[:120])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main() -> int:
    test_parse_block_ids()
    test_context_blocks()
    test_apply_compacts()
    test_small_block_skip()
    test_write_context_map()
    test_session_memory_actions()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ CONTEXT COMPACT ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
