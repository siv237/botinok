#!/usr/bin/env python3
"""
Тесты версии BOTINOK: git — источник истины, `.version` — fallback,
и `.version` обновляется после git pull.

Причина правки: баннер читал `.version` (его пишет install.sh), а `--update`
его не обновлял — версия навсегда оставалась «10.06.2026 | cd57».

Запуск: venv/bin/python -u tests/test_version.py
"""

import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import botinok as B  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("version smoke-test")
    print("=" * 70)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # --- в git-репозитории версия берётся из git ---
    real_hash = subprocess.run(['git', 'log', '-1', '--format=%h'],
                               capture_output=True, text=True, cwd=root).stdout.strip()
    date, h = B._get_version_info(root)
    check("git_date_format", bool(re.match(r"^\d{2}\.\d{2}\.\d{4}$", date)), date)
    check("git_hash", h and real_hash.startswith(h), f"{h} vs {real_hash}")
    check("module_version_uses_git", B._COMMIT_HASH == h, f"{B._COMMIT_HASH} vs {h}")

    # --- fallback: файл .version ---
    tmp = tempfile.mkdtemp(prefix="botinok_ver_")
    with open(os.path.join(tmp, ".version"), "w") as f:
        f.write("0.2 | 10.06.2026 | cd57\n")
    check("read_version_file", B._read_version_file(tmp) == ("10.06.2026", "cd57"))
    check("fallback_without_git", B._get_version_info(tmp) == ("10.06.2026", "cd57"))

    # --- запись .version после pull (git-инфо подменяем) ---
    saved = B._git_version_info
    B._git_version_info = lambda d: ("02.02.2026", "beef")
    try:
        B._write_version_file(tmp)
        content = open(os.path.join(tmp, ".version")).read().strip()
        check("write_version_file", content == "0.4 | 02.02.2026 | beef", content)
    finally:
        B._git_version_info = saved

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ VERSION SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
