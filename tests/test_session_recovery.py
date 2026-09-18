#!/usr/bin/env python3
"""
Тест сохранности сессии: прерывание не должно портить history.

Проверяем, что context.json пишется атомарно (tmp+replace) с бэкапом, и что при
повреждении история восстанавливается из .bak или из снапшота messages.json.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session_manager import SessionManager  # noqa: E402

FAILURES = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("Session recovery smoke-test")
    print("=" * 70)
    # Изоляция: сессии теста пишутся в tmp, а не в рабочие ~/.botinok/sessions.
    tmp = tempfile.mkdtemp(prefix="botinok_recovery_")
    os.environ["BOTINOK_SESSIONS_DIR"] = tmp
    sm = SessionManager()

    # 1. Атомарная запись + бэкап: после 2 записей появляется .bak
    session = sm.create_session("recovery-test")
    ctx = os.path.join(session, "context.json")
    sm.update_context(session, "user", "раз")
    sm.update_context(session, "assistant", "два")
    check("bak_created", os.path.exists(ctx + ".bak"))
    check("tmp_removed", not os.path.exists(ctx + ".tmp"))

    # 2. Портим context.json — update_context должен восстановиться из .bak
    with open(ctx, "w", encoding="utf-8") as f:
        f.write('{"history": [')  # обрубленный JSON
    sm.update_context(session, "user", "три")  # должно прочитать .bak и дописать
    with open(ctx, encoding="utf-8") as f:
        data = json.load(f)  # не должно бросить
    roles = [e.get("role") for e in data.get("history", [])]
    contents = [e.get("content") for e in data.get("history", [])]
    # Восстановление из .bak даёт предыдущую целую версию (последняя запись,
    # оборванная при записи, может потеряться — это допустимо), файл валиден.
    check("recovered_from_bak",
          len(roles) >= 2 and roles[-1] == "user" and "раз" in contents,
          str(contents))

    # 3. Оба файла битые — fallback на messages.json
    session2 = sm.create_session("recovery-snapshot")
    sm.save_messages_snapshot(session2, [{"role": "user", "content": "привет"},
                                         {"role": "assistant", "content": "ответ"}])
    ctx2 = os.path.join(session2, "context.json")
    with open(ctx2, "w", encoding="utf-8") as f:
        f.write("{broken")
    entries = sm.load_history_entries(session2)
    check("fallback_snapshot", len(entries) == 2 and entries[0]["content"] == "привет",
          str(entries)[:200])
    # После update_context повреждённый файл отложен, история засеяна из снапшота
    sm.update_context(session2, "user", "ещё")
    with open(ctx2, encoding="utf-8") as f:
        data2 = json.load(f)
    check("seeded_from_snapshot", len(data2.get("history", [])) >= 3, str(len(data2.get("history", []))))

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ SESSION RECOVERY SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
