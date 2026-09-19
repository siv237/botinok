#!/usr/bin/env python3
"""
Тест детекции типов (`core/file_kinds.py`) и проверки синтаксиса
(`core/syntax_check.py`) + интеграции в `code_editor`.

Запуск: venv/bin/python -u tests/test_syntax_check.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.file_kinds import detect_kinds, normalize_kind  # noqa: E402
from core.syntax_check import check_syntax  # noqa: E402
from tools.code_editor import code_editor  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _sess() -> str:
    return tempfile.mkdtemp(prefix="botinok_syn_")


def _w(d: str, name: str, content: str) -> str:
    p = os.path.join(d, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def test_detection() -> None:
    print("-- детекция типов --")
    d = _sess()
    cases = {
        "a.py": ("def f():\n    return 1\n", "python"),
        "b.json": ('{"a": 1}', "json"),
        "c.yaml": ("a: 1\nb: 2\n", "yaml"),
        "e.toml": ("x = 1\n[s]\ny = 2\n", "toml"),
        "f.sh": ("echo hi\n", "bash"),
        "g.js": ("const x = 1;\n", "javascript"),
        "h.ts": ("const x: number = 1;\n", "typescript"),
    }
    for name, (content, expected) in cases.items():
        p = _w(d, name, content)
        got = detect_kinds(p)[0]["kind"]
        check(f"ext {name}", got == expected, got)
    p = _w(d, "noext_py", "#!/usr/bin/env python3\nprint(1)\n")
    check("shebang python", detect_kinds(p)[0]["kind"] == "python", detect_kinds(p))
    p = _w(d, "noext_json", '{"k": [1,2,3]}')
    check("sniff json", detect_kinds(p)[0]["kind"] == "json", detect_kinds(p))
    p = _w(d, "noext_yaml", "key: value\nlist:\n  - a\n")
    check("sniff yaml", detect_kinds(p)[0]["kind"] == "yaml", detect_kinds(p))
    check("normalize py", normalize_kind("PY") == "python" and normalize_kind("sh") == "bash")


def test_checkers() -> None:
    print("-- проверки синтаксиса --")
    good_bad = [
        ("a.py", "def f():\n    return 1\n", "def f(:\n    pass\n"),
        ("b.json", '{"a": 1}', '{"a": }'),
        ("c.yaml", "a: 1\nb: [1, 2]\n", "a: [1, 2\n"),
        ("d.toml", "x = 1\n", "x = \n"),
        ("e.xml", "<a><b/></a>", "<a><b></a>"),
        ("f.js", "const x = () => 1;\n", "const x = ( => ;\n"),
        ("g.sh", "echo hi\n", "if [ 1 ]; then\n"),
        ("h.ts", "const x: number = 1;\n", "const x: = ;\n"),
    ]
    d = _sess()
    for name, good, bad in good_bad:
        pg = _w(d, name, good)
        pb = _w(d, name.replace(".", "_bad."), bad)
        rg = check_syntax(path=pg)
        rb = check_syntax(path=pb)
        check(f"{name} valid", rg["status"] == "ok", rg)
        check(f"{name} invalid", rb["status"] == "error" and rb.get("errors"), rb)


def test_kind_override_and_binary() -> None:
    print("-- kind override / бинарь --")
    d = _sess()
    p = _w(d, "data.txt", '{"a": 1}')
    auto = check_syntax(path=p)
    check("txt auto unsupported", auto["status"] == "unsupported", auto)
    forced = check_syntax(path=p, kind="json")
    check("txt forced json ok", forced["status"] == "ok", forced)

    b = os.path.join(d, "x.bin")
    with open(b, "wb") as f:
        f.write(b"\x00\x01\x02")
    rb = check_syntax(path=b)
    check("binary skipped", rb["status"] == "skipped" and rb.get("kind") == "binary", rb)

    amb = detect_kinds(os.path.join(d, "noext_amb"), head=b'{"a":1}')
    check("candidates list", isinstance(amb, list) and amb and "confidence" in amb[0], amb)


def test_code_editor_integration() -> None:
    print("-- интеграция code_editor --")
    s = _sess()
    p = os.path.join(s, "bad.py")
    r = code_editor(action="write", path=p, content="def f(:\n    pass\n", create=True, session_path=s)
    j = json.loads(r)
    check("write_syntax_reported", j.get("syntax", {}).get("status") == "error", r[:300])
    check("advice_warns", "Синтаксис" in j.get("_advice", "") and "подсказка" in j.get("_advice", ""), j.get("_advice"))
    check("advice_not_imperative", "Исправь" not in j.get("_advice", ""), j.get("_advice"))

    r = code_editor(action="replace", path=p,
                    old_text="def f(:\n    pass", new_text="def f():\n    pass", session_path=s)
    j = json.loads(r)
    check("fix_syntax_ok", j.get("syntax", {}).get("status") == "ok", r[:300])
    check("advice_positive", "OK" in j.get("_advice", ""), j.get("_advice"))

    r = code_editor(action="check", path=p, session_path=s)
    j = json.loads(r)
    check("check_ok", j.get("syntax", {}).get("status") == "ok" and j.get("ok") is True, r[:300])

    r = code_editor(action="check", path=p, kind="python", session_path=s)
    check("check_kind", json.loads(r).get("syntax", {}).get("kind") == "python", r[:200])

    r = code_editor(action="lint", path=p, session_path=s)
    check("alias_lint", json.loads(r).get("action") == "check", r[:200])


def main() -> int:
    print("=" * 70)
    print("syntax check + file kinds test")
    print("=" * 70)
    test_detection()
    test_checkers()
    test_kind_override_and_binary()
    test_code_editor_integration()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ syntax check: все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
