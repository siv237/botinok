#!/usr/bin/env python3
"""
Тест разрешения путей сессии (`core/path_utils.py`) и его влияния на инструменты.

Регрессия из сессии 20260919_145122: относительный путь `project/notes.txt`
резолвился в `<session>/project/project/notes.txt` (двойной `project`).

Запуск: venv/bin/python -u tests/test_path_resolution.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.path_utils import resolve_session_path  # noqa: E402
from core.tool_manager import allowed_in_session  # noqa: E402
from tools.code_editor import code_editor  # noqa: E402
from tools.file_system import file_system_tool as fs  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _sess() -> str:
    d = tempfile.mkdtemp(prefix="botinok_path_")
    os.makedirs(os.path.join(d, "project"), exist_ok=True)
    return d


def test_resolver() -> None:
    print("-- resolve_session_path --")
    s = _sess()
    proj = os.path.realpath(os.path.join(s, "project"))
    check("plain_relative", resolve_session_path("notes.txt", s) == os.path.join(proj, "notes.txt"))
    check("no_double_project", resolve_session_path("project/notes.txt", s) == os.path.join(proj, "notes.txt"))
    check("dot_slash_project", resolve_session_path("./project/notes.txt", s) == os.path.join(proj, "notes.txt"))
    check("nested", resolve_session_path("project/sub/x.txt", s) == os.path.join(proj, "sub", "x.txt"))
    check("abs_unchanged", resolve_session_path("/etc/hosts", s) == os.path.realpath("/etc/hosts"))
    check("no_session", resolve_session_path("x.txt", None) == os.path.realpath("x.txt"))


def test_code_editor_relative() -> None:
    print("-- code_editor: относительные пути --")
    s = _sess()
    r = code_editor(action="write", path="project/notes.txt", content="hi\n", create=True, session_path=s)
    j = json.loads(r)
    check("write_ok", j.get("ok") is True, r)
    correct = os.path.join(s, "project", "notes.txt")
    double = os.path.join(s, "project", "project", "notes.txt")
    check("landed_correct", os.path.isfile(correct), correct)
    check("no_double_dir", not os.path.exists(double), double)
    r = code_editor(action="read", path="project/notes.txt", session_path=s)
    check("read_relative", "hi" in r and "lines 1-1 of 1" in r, r[:160])
    r = code_editor(action="write", path="sub/deep.txt", content="x\n", create=True, session_path=s)
    check("sub_relative", os.path.isfile(os.path.join(s, "project", "sub", "deep.txt")), r[:120])


def test_file_system_relative() -> None:
    print("-- file_system: относительные пути --")
    s = _sess()
    with open(os.path.join(s, "project", "app.py"), "w", encoding="utf-8") as f:
        f.write("def alpha():\n    pass\n")
    r = fs(action="grep", path="project/app.py", content_query="^def ", session_path=s)
    check("grep_relative_file", "alpha" in r, r[:150])
    r = fs(action="read", path="project/app.py", session_path=s)
    check("read_relative", "alpha" in r, r[:150])
    r = fs(action="list", path="project", session_path=s, dangerous_mode=False)
    check("list_relative", "app.py" in r, r[:150])


def test_gate_relative() -> None:
    print("-- гейт безопасности: относительные пути внутри сессии --")
    s = _sess()
    check("ce_write_inside", allowed_in_session("code_editor", {"action": "write", "path": "project/x.txt"}, s) is True)
    check("ce_undo_inside", allowed_in_session("code_editor", {"action": "undo", "path": "x.txt"}, s) is True)
    check("fs_mkdir_inside", allowed_in_session("file_system", {"action": "mkdir", "path": "project/newdir"}, s) is True)
    check("escape_blocked", allowed_in_session("code_editor", {"action": "write", "path": "../../etc/x"}, s) is False)


def test_tool_manager_roundtrip() -> None:
    print("-- ToolManager: запись по относительному пути внутри сессии --")
    from core.tool_manager import ToolManager
    os.environ["BOTINOK_DANGEROUS"] = "0"
    tm = ToolManager()
    s = _sess()
    r = tm.call_tool("code_editor",
                     {"action": "write", "path": "project/gate.txt", "content": "ok\n", "create": True},
                     session_path=s)
    check("tm_relative_write", '"changed": true' in r, r[:160])
    check("tm_no_double", os.path.isfile(os.path.join(s, "project", "gate.txt")), "")


def main() -> int:
    print("=" * 70)
    print("path resolution test")
    print("=" * 70)
    test_resolver()
    test_code_editor_relative()
    test_file_system_relative()
    test_gate_relative()
    test_tool_manager_roundtrip()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ path resolution: все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
