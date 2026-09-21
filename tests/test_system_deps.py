#!/usr/bin/env python3
"""
Тесты установки системных зависимостей (botinok.py).

Проверяем планировщик/логику БЕЗ реальной установки: подменяем наличие
бинарников, права и запуск пакетного менеджера.

Запуск: venv/bin/python -u tests/test_system_deps.py
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import botinok as B  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("system deps smoke-test")
    print("=" * 70)

    bins = {b for b, _ in B._SYSTEM_TOOLS}
    check("chafa_in_deps", "chafa" in bins, str(bins))
    check("ffmpeg_in_deps", "ffmpeg" in bins, str(bins))
    check("core_bins_in_deps", {"aria2c", "lynx", "jq", "file", "curl", "git"} <= bins)

    saved_which = B.shutil.which
    saved_geteuid = os.geteuid

    # --- детект отсутствующего бинарника и дедуп пакетов ---
    real_which = shutil.which

    def only_chafa_missing(name):
        return None if name == "chafa" else real_which(name)
    B.shutil.which = only_chafa_missing
    try:
        missing = B._missing_system_tools()
        check("missing_detects_chafa", any(b == "chafa" for b, _ in missing), str(missing))
        check("missing_packages_dedup", B._missing_packages() == ["chafa"],
              str(B._missing_packages()))
    finally:
        B.shutil.which = saved_which

    # --- всё на месте -> ничего не делаем ---
    B._missing_system_tools = lambda: []
    check("ensure_all_present", "на месте" in B._ensure_system_deps())

    # --- не root и нет sudo -> понятное сообщение, без запуска ---
    B._missing_system_tools = lambda: [("chafa", "chafa")]
    B.os.geteuid = lambda: 1000
    B.shutil.which = lambda name: None if name == "sudo" else "/usr/bin/apt-get"
    try:
        msg = B._ensure_system_deps()
        check("ensure_needs_root", "root" in msg.lower() or "права" in msg.lower(), msg)
    finally:
        B.os.geteuid = saved_geteuid
        B.shutil.which = saved_which

    # --- root + apt: сначала update индексов, затем install всех пакетов ---
    captured = []

    def fake_run(cmd, timeout=900):
        captured.append(list(cmd))
        B._missing_system_tools = lambda: []  # после "установки" всё на месте

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    B._missing_system_tools = lambda: [("chafa", "chafa"), ("ffmpeg", "ffmpeg")]
    B._pkg_manager = lambda: ("apt-get", ["apt-get", "install", "-y"],
                              ["apt-get", "update", "-y"])
    B.os.geteuid = lambda: 0
    B._run_priv = fake_run
    try:
        msg = B._ensure_system_deps()
    finally:
        B.os.geteuid = saved_geteuid
    check("ensure_apt_update_then_install",
          any("update" in c for c in captured)
          and any("install" in c and "chafa" in c and "ffmpeg" in c for c in captured),
          str(captured))
    check("ensure_reports_installed", "установлены" in msg, msg)

    # --- нет пакетного менеджера -> перечисляет пакеты вручную ---
    B._missing_system_tools = lambda: [("aria2c", "aria2")]
    B._pkg_manager = lambda: (None, None, None)
    B.os.geteuid = lambda: 0
    try:
        msg = B._ensure_system_deps()
        check("ensure_no_manager", "aria2" in msg and "менеджер" in msg.lower(), msg)
    finally:
        B.os.geteuid = saved_geteuid

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ SYSTEM DEPS SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
