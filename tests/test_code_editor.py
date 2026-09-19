#!/usr/bin/env python3
"""
Тест edit-кита `tools/code_editor.py`.

Проверяем:
  * write (create) + JSON-совместимость ("changed": true);
  * read: шапка, нумерация строк, ignored_args;
  * replace: точная замена, fuzzy (дрейф отступов), ближайшее совпадение;
  * неоднозначность (ambiguous) и replace_all;
  * apply: несколько правок атомарно (всё или ничего);
  * сохранение BOM и CRLF;
  * стейл-контроль (файл изменён вне сессии);
  * undo из чекпоинта;
  * отказ на бинарном файле;
  * help;
  * интеграция через ToolManager (dangerous-gate).

Запуск: venv/bin/python -u tests/test_code_editor.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.code_editor import code_editor  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _sess() -> str:
    return tempfile.mkdtemp(prefix="botinok_edit_")


def _write_raw(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def test_write_and_read() -> None:
    print("-- write / read --")
    sess = _sess()
    p = os.path.join(sess, "a.txt")
    r = code_editor(action="write", path=p, content="line1\nline2\n", create=True, session_path=sess)
    j = json.loads(r)
    check("write_changed_true", j.get("changed") is True, r)
    check("write_has_sha", bool(j.get("after_sha256")), r)
    check("write_diff_present", "+line1" in j.get("diff", ""), j.get("diff"))
    check("write_envelope", j.get("_provenance") == "exact" and j.get("_advice"), r)

    r = code_editor(action="read", path=p, session_path=sess, line_numbers=True)
    check("read_header", "--- lines 1-" in r and "sha256=" in r, r[:200])
    check("read_numbered", "1\tline1" in r.replace("      ", ""), r[:300])
    check("read_footer", "action=replace" in r, r[-200:])

    r2 = code_editor(action="read", path=p, session_path=sess, foo=1)
    check("read_ignored_arg", "проигнорированы" in r2 and "foo" in r2, r2[:200])


def test_replace_exact() -> None:
    print("-- replace exact --")
    sess = _sess()
    p = os.path.join(sess, "b.txt")
    code_editor(action="write", path=p, content="alpha\nbeta\ngamma\n", create=True, session_path=sess)
    r = code_editor(action="replace", path=p, old_text="beta", new_text="BETA", session_path=sess)
    j = json.loads(r)
    check("replace_changed", j.get("changed") is True, r)
    check("replace_applied", j.get("applied", [{}])[0].get("matched") == "exact", r)
    check("replace_checkpoint", bool(j.get("checkpoint")), r)
    check("replace_content", "BETA" in open(p, encoding="utf-8").read(), "")


def test_replace_not_found() -> None:
    print("-- replace not found (nearest) --")
    sess = _sess()
    p = os.path.join(sess, "c.txt")
    code_editor(action="write", path=p, content="alpha\nbeta\ngamma\n", create=True, session_path=sess)
    r = code_editor(action="replace", path=p, old_text="alpha\nZZZ\nZZZ", new_text="x", session_path=sess)
    j = json.loads(r)
    err = j.get("error", {})
    check("notfound_code", err.get("code") == "old_text_not_found", r)
    check("notfound_nearest", isinstance(err.get("nearest"), dict) and err["nearest"].get("snippet"), r)
    check("notfound_unchanged", open(p, encoding="utf-8").read() == "alpha\nbeta\ngamma\n", "")


def test_fuzzy() -> None:
    print("-- fuzzy (indent drift) --")
    sess = _sess()
    p = os.path.join(sess, "d.py")
    code_editor(action="write", path=p,
                content="def f():\n    return 1\n\ndef g():\n    return 2\n",
                create=True, session_path=sess)
    r = code_editor(action="replace", path=p,
                    old_text="def f():\n  return 1", new_text="def f():\n    return 100",
                    session_path=sess)
    j = json.loads(r)
    check("fuzzy_changed", j.get("changed") is True, r)
    check("fuzzy_matched", j.get("applied", [{}])[0].get("matched") == "fuzzy", r)
    check("fuzzy_content", "return 100" in open(p, encoding="utf-8").read(), "")


def test_ambiguous_and_replace_all() -> None:
    print("-- ambiguous / replace_all --")
    sess = _sess()
    p = os.path.join(sess, "e.txt")
    code_editor(action="write", path=p, content="x\ny\nx\ny\n", create=True, session_path=sess)
    r = code_editor(action="replace", path=p, old_text="x\ny", new_text="Z", session_path=sess)
    j = json.loads(r)
    check("ambiguous_code", j.get("error", {}).get("code") == "ambiguous", r)
    check("ambiguous_candidates", bool(j.get("error", {}).get("candidates")), r)

    r = code_editor(action="replace", path=p, old_text="x\ny", new_text="Z",
                    replace_all=True, session_path=sess)
    j = json.loads(r)
    check("replace_all_count", j.get("applied", [{}])[0].get("count") == 2, r)
    check("replace_all_content", open(p, encoding="utf-8").read() == "Z\nZ\n", "")


def test_apply_atomic() -> None:
    print("-- apply atomic --")
    sess = _sess()
    p = os.path.join(sess, "f.txt")
    code_editor(action="write", path=p, content="aaa\nbbb\nccc\n", create=True, session_path=sess)
    r = code_editor(action="apply", path=p,
                    edits=[{"old_text": "aaa", "new_text": "AAA"},
                           {"old_text": "ZZZ", "new_text": "Q"}],
                    session_path=sess)
    j = json.loads(r)
    check("apply_error", j.get("ok") is False, r)
    check("apply_atomic_unchanged", open(p, encoding="utf-8").read() == "aaa\nbbb\nccc\n", "")
    check("apply_partial_reported", len(j.get("error", {}).get("applied_before_error", [])) == 1, r)

    r = code_editor(action="apply", path=p,
                    edits=[{"old_text": "aaa", "new_text": "AAA"},
                           {"old_text": "ccc", "new_text": "CCC"}],
                    session_path=sess)
    j = json.loads(r)
    check("apply_ok", j.get("ok") is True and len(j.get("applied", [])) == 2, r)
    check("apply_content", open(p, encoding="utf-8").read() == "AAA\nbbb\nCCC\n", "")


def test_encoding_preservation() -> None:
    print("-- BOM / CRLF preservation --")
    sess = _sess()
    p = os.path.join(sess, "g.txt")
    _write_raw(p, b"\xef\xbb\xbfa\r\nb\r\n")
    r = code_editor(action="replace", path=p, old_text="a\nb", new_text="a\nc", session_path=sess)
    j = json.loads(r)
    check("bom_replace_ok", j.get("ok") is True, r)
    raw = open(p, "rb").read()
    check("bom_preserved", raw.startswith(b"\xef\xbb\xbf"), raw[:10])
    check("crlf_preserved", b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), raw)

    r = code_editor(action="read", path=p, session_path=sess)
    check("read_reports_crlf", "eol=CRLF" in r and "encoding=utf-8-sig" in r, r[:200])


def test_stale_guard() -> None:
    print("-- stale guard --")
    sess = _sess()
    p = os.path.join(sess, "h.txt")
    code_editor(action="write", path=p, content="v1", create=True, session_path=sess)
    code_editor(action="read", path=p, session_path=sess)
    _write_raw(p, b"v2")
    r = code_editor(action="replace", path=p, old_text="v2", new_text="v3", session_path=sess)
    j = json.loads(r)
    check("stale_code", j.get("error", {}).get("code") == "stale", r)
    check("stale_unchanged", open(p, encoding="utf-8").read() == "v2", "")


def test_undo() -> None:
    print("-- undo --")
    sess = _sess()
    p = os.path.join(sess, "i.txt")
    code_editor(action="write", path=p, content="one\ntwo\n", create=True, session_path=sess)
    r = code_editor(action="replace", path=p, old_text="one", new_text="ONE", session_path=sess)
    check("undo_prepare", open(p, encoding="utf-8").read() == "ONE\ntwo\n", "")
    r = code_editor(action="undo", path=p, session_path=sess)
    j = json.loads(r)
    check("undo_ok", j.get("ok") is True, r)
    check("undo_content", open(p, encoding="utf-8").read() == "one\ntwo\n", "")


def test_binary_and_help() -> None:
    print("-- binary / help --")
    sess = _sess()
    p = os.path.join(sess, "j.bin")
    _write_raw(p, b"\x00\x01\x02binary")
    r = code_editor(action="read", path=p, session_path=sess)
    j = json.loads(r)
    check("binary_code", j.get("error", {}).get("code") == "binary", r)

    r = code_editor(action="help", path="", session_path=sess)
    check("help_text", "action=read" in r and "action=apply" in r and "action=undo" in r, r[:200])

    r = code_editor(action="frobnicate", path=os.path.join(sess, "x"), session_path=sess)
    j = json.loads(r)
    check("unknown_action", j.get("error", {}).get("code") == "unknown_action", r)


def test_tool_manager_integration() -> None:
    print("-- ToolManager integration --")
    from core.tool_manager import ToolManager, allowed_in_session
    os.environ["BOTINOK_DANGEROUS"] = "0"
    tm = ToolManager()
    sess = _sess()
    outside = tempfile.mkdtemp(prefix="botinok_out_")
    p = os.path.join(sess, "k.txt")
    r = tm.call_tool("code_editor",
                     {"action": "write", "path": p, "content": "hi\n", "create": True},
                     session_path=sess)
    check("tm_write_inside", '"changed": true' in r, r)
    r = tm.call_tool("code_editor",
                     {"action": "write", "path": os.path.join(outside, "k.txt"),
                      "content": "hi\n", "create": True},
                     session_path=sess)
    check("tm_write_outside_blocked", r.startswith("Error"), r)
    check("gate_allows_read_inside", allowed_in_session("code_editor",
          {"action": "read", "path": p}, sess) is True, "")
    check("gate_blocks_undo_outside", allowed_in_session("code_editor",
          {"action": "undo", "path": os.path.join(outside, "k.txt")}, sess) is False, "")


def test_noop_and_undo_guard() -> None:
    print("-- no-op write / undo guard --")
    sess = _sess()
    p = os.path.join(sess, "m.txt")
    code_editor(action="write", path=p, content="same\n", create=True, session_path=sess)
    r = code_editor(action="write", path=p, content="same\n", session_path=sess)
    j = json.loads(r)
    check("noop_changed_false", j.get("changed") is False, r)
    check("noop_no_checkpoint", j.get("checkpoint") is None, r)

    other = os.path.join(sess, "not-a-checkpoint.txt")
    _write_raw(other, b"evil")
    r = code_editor(action="undo", path=p, checkpoint=other, session_path=sess)
    j = json.loads(r)
    check("undo_bad_checkpoint", j.get("error", {}).get("code") == "bad_checkpoint", r)


def test_read_pagination_beyond_cap() -> None:
    print("-- read pagination beyond 200 KB --")
    sess = _sess()
    p = os.path.join(sess, "big.txt")
    with open(p, "w", encoding="utf-8") as f:
        for i in range(30000):
            f.write(f"{i:05d} " + "x" * 50 + "\n")
    r = code_editor(action="read", path=p, session_path=sess, offset=25000, limit=3)
    head = r.splitlines()[1]
    check("paginate_header", "lines 25001-25003 of 30000" in head, head)
    check("paginate_body", "25000 " in r, r[:400])


def test_trailing_newline_and_eof() -> None:
    print("-- trailing newline / EOF --")
    sess = _sess()
    p = os.path.join(sess, "t.txt")
    _write_raw(p, b"a\nb\nc\n")
    r = code_editor(action="read", path=p, session_path=sess, line_numbers=True)
    check("line_count_correct", "lines 1-3 of 3" in r, r[:160])
    check("no_phantom_line", "4\t" not in r, r[:400])
    r = code_editor(action="read", path=p, session_path=sess, offset=3, limit=1)
    check("eof_no_inverted", "of 3" in r.splitlines()[1] and "конец файла" in r, r[:200])


def test_eol_modes() -> None:
    print("-- EOL modes (CR-only / mixed) --")
    sess = _sess()
    cr = os.path.join(sess, "cr.txt")
    _write_raw(cr, b"a\rb\rc")
    r = code_editor(action="replace", path=cr, old_text="b", new_text="B", session_path=sess)
    check("cr_only_preserved", open(cr, "rb").read() == b"a\rB\rc", open(cr, "rb").read())

    mix = os.path.join(sess, "mix.txt")
    _write_raw(mix, b"a\r\nb\nc\n")
    r = code_editor(action="read", path=mix, session_path=sess)
    check("mixed_reported", "mixed" in r.splitlines()[1], r[:160])
    r = code_editor(action="replace", path=mix, old_text="b", new_text="B", session_path=sess)
    j = json.loads(r)
    check("mixed_flagged_result", j.get("eol_normalized") is True, r)


def test_fuzzy_bounds() -> None:
    print("-- fuzzy bounds --")
    sess = _sess()
    p = os.path.join(sess, "fb.txt")
    with open(p, "w", encoding="utf-8") as f:
        for i in range(500):
            f.write(f"unique line number {i} content\n")
    big_needle = "\n".join(f"absent line {i}" for i in range(90))
    r = code_editor(action="replace", path=p, old_text=big_needle, new_text="x", session_path=sess)
    j = json.loads(r)
    check("fuzzy_skipped_needle", j.get("error", {}).get("fuzzy_skipped") == "needle_too_large", r)


def test_undo_stale_and_force() -> None:
    print("-- undo stale / force --")
    sess = _sess()
    p = os.path.join(sess, "us.txt")
    code_editor(action="write", path=p, content="orig\n", create=True, session_path=sess)
    code_editor(action="replace", path=p, old_text="orig", new_text="v2", session_path=sess)
    _write_raw(p, b"EXTERNAL\n")
    r = code_editor(action="undo", path=p, session_path=sess)
    j = json.loads(r)
    check("undo_stale", j.get("error", {}).get("code") == "stale", r)
    r = code_editor(action="undo", path=p, force=True, session_path=sess)
    j = json.loads(r)
    check("undo_force_ok", j.get("ok") is True, r)
    check("undo_force_content", open(p, encoding="utf-8").read() == "orig\n", "")


def test_alias_gate() -> None:
    print("-- alias danger gate --")
    from core.tool_manager import allowed_in_session
    sess = _sess()
    outside = tempfile.mkdtemp(prefix="botinok_out_")
    check("alias_gate_inside", allowed_in_session(
        "code_editor", {"action": "save", "path": os.path.join(sess, "x")}, sess) is True, "")
    check("alias_gate_outside", allowed_in_session(
        "code_editor", {"action": "save", "path": os.path.join(outside, "x")}, sess) is False, "")
    check("alias_edit_gate_outside", allowed_in_session(
        "code_editor", {"action": "edit", "path": os.path.join(outside, "x")}, sess) is False, "")


def main() -> int:
    print("=" * 70)
    print("code_editor (edit-кит) test")
    print("=" * 70)
    test_write_and_read()
    test_replace_exact()
    test_replace_not_found()
    test_fuzzy()
    test_ambiguous_and_replace_all()
    test_apply_atomic()
    test_encoding_preservation()
    test_stale_guard()
    test_undo()
    test_noop_and_undo_guard()
    test_read_pagination_beyond_cap()
    test_trailing_newline_and_eof()
    test_eol_modes()
    test_fuzzy_bounds()
    test_undo_stale_and_force()
    test_alias_gate()
    test_binary_and_help()
    test_tool_manager_integration()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ code_editor: все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
