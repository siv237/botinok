#!/usr/bin/env python3
"""
Тест мгновенной остановки: Esc должен прерывать запущенный процесс вместе со
всеми порождёнными («внуками»), не оставляя ничего висеть.
"""

import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import process_control as pc  # noqa: E402

FAILURES = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("Process control smoke-test")
    print("=" * 70)
    pc.clear_stop()

    # 1. run() прерывается сразу по request_stop
    def stopper():
        time.sleep(0.3)
        pc.request_stop()

    threading.Thread(target=stopper, daemon=True).start()
    t0 = time.time()
    cp = pc.run(["sleep", "30"], timeout=60, capture_output=True, text=True)
    dt = time.time() - t0
    check("run_interrupted_fast", dt < 5, f"{dt:.2f}s")
    check("run_returncode_killed", cp.returncode is not None and cp.returncode != 0,
          str(cp.returncode))

    # 2. Процесс без run(): зарегистрирован и убит, вместе с потомком.
    pc.clear_stop()
    marker = "31.777"  # уникальный маркер, чтобы найти именно наш sleep
    tree = subprocess.Popen(["bash", "-c", f"sleep {marker} & sleep {marker}"],
                            start_new_session=True)
    pc.register(tree)
    time.sleep(0.3)

    def _count():
        try:
            r = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
            return len([x for x in r.stdout.split() if x.strip()])
        except Exception:
            return -1

    before = _count()
    pc.request_stop()
    try:
        tree.wait(timeout=3)
    except Exception:
        pass
    time.sleep(0.5)
    after = _count()
    check("tree_had_children", before >= 1, str(before))
    check("no_leftover_after_stop", after == 0, f"before={before} after={after}")
    pc.unregister(tree)

    pc.clear_stop()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ PROCESS CONTROL SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
