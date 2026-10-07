#!/usr/bin/env python3
"""
Механический совет session_memory при чтении файлов сессии через file_system.

Боевой кейс: модель упорно грепает/читает context.json и tools.log, получая
сырой JSON в контекст. Теперь read-only действия по путям внутри каталога
сессий (корень, папка сессии, файлы истории) получают в ответе указатель на
session_memory; обычные файлы и вложенные артефакты — без шума.

Запуск: venv/bin/python -u tests/test_fs_session_hint.py
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_sessions_root = tempfile.mkdtemp(prefix="botinok_fs_hint_")
os.environ["BOTINOK_SESSIONS_DIR"] = _sessions_root

from tools.file_system import file_system_tool  # noqa: E402

FAILURES = []
HINT_MARK = "session_memory"


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    sess = os.path.join(_sessions_root, "20261007_test")
    os.makedirs(os.path.join(sess, "downloads"), exist_ok=True)
    os.makedirs(os.path.join(sess, "artifacts"), exist_ok=True)
    ctx = os.path.join(sess, "context.json")
    with open(ctx, "w", encoding="utf-8") as f:
        f.write('{"history": [{"role": "user", "content": "привет"}]}')
    with open(os.path.join(sess, "downloads", "page.html"), "w", encoding="utf-8") as f:
        f.write("<html>семинар совещание</html>")
    with open(os.path.join(sess, "artifacts", "tool_web_call_1.txt"), "w",
              encoding="utf-8") as f:
        f.write("семинар совещание хабаровск семинар совещание\nвторая строка\nтретья про семинар\n")
    with open(os.path.join(sess, "artifacts", "tool_web_call_2.txt"), "w",
              encoding="utf-8") as f:
        f.write("ничего полезного\nтолько совещание вскользь\n")
    outside = os.path.join(tempfile.mkdtemp(prefix="botinok_fs_out_"), "notes.txt")
    with open(outside, "w", encoding="utf-8") as f:
        f.write("обычный файл")

    out = file_system_tool(action="read", path=ctx)
    check("read_context_json_hinted", HINT_MARK in out)

    out = file_system_tool(action="grep", path=_sessions_root, content_query="привет",
                           recursive=True)
    check("grep_sessions_root_hinted", HINT_MARK in out)

    out = file_system_tool(action="list", path=sess)
    check("list_session_dir_hinted", HINT_MARK in out)

    out = file_system_tool(action="read", path=outside)
    check("outside_file_no_hint", HINT_MARK not in out)

    out = file_system_tool(action="grep", path=os.path.join(sess, "downloads", "page.html"),
                           content_query="семинар")
    check("downloads_untouched", HINT_MARK not in out, f"out={out[:120]}")

    out = file_system_tool(action="grep", path=os.path.join(sess, "artifacts", "tool_web_call_2.txt"),
                           content_query="семинар|совещание")
    check("artifact_autosearch_runs", "ВСЕМ артефактам" in out, f"out={out[:200]}")
    check("artifact_autosearch_ranks_best", "tool_web_call_1.txt" in out.split("💡")[1],
          f"out={out[-300:]}")

    out = file_system_tool(action="grep", path=os.path.join(sess, "artifacts", "tool_web_call_2.txt"),
                           content_query="хабаровск")
    check("empty_grep_gets_treasure", "Совпадений не найдено" in out and "tool_web_call_1.txt" in out,
          f"out={out[-300:]}")

    out = file_system_tool(action="read", path=os.path.join(sess, "artifacts", "tool_web_call_1.txt"))
    check("artifact_read_pointer", HINT_MARK in out)

    out = file_system_tool(action="read", path=os.path.join(sess, "missing.json"))
    check("error_result_no_hint", HINT_MARK not in out)

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ FS SESSION HINT ТЕСТ ПРОЙДЕН")
    return 0


def test_all() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
