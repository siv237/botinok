#!/usr/bin/env python3
"""
Тест ступенчатого раскрытия инструментов (tools/tools_catalog.py):
  * каталог краткий и содержит все инструменты;
  * enable добавляет инструмент в payload-набор и персистится;
  * always-on (tools/sign_step/session_memory) нельзя сломать; неизвестное имя — ошибка;
  * disable и перезагрузка состояния.

Запуск: venv/bin/python -u tests/test_tools_catalog.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import tools_catalog as tc  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    from core.tool_manager import ToolManager
    tm = ToolManager()

    # 1) каталог
    cat = tc.catalog_text(tm)
    check("catalog_has_core", all(n in cat for n in ("web", "github", "vision")), "")
    check("session_memory_always_on_not_in_catalog", "\n- session_memory:" not in cat)
    check("catalog_compact", len(cat) < 4000, str(len(cat)))
    check("catalog_mentions_enable", "enable" in cat)
    check("tools_meta_not_in_catalog", "\n- tools:" not in cat)

    # 2) базовый набор payload
    with tempfile.TemporaryDirectory() as td:
        sess = os.path.join(td, "s")
        os.makedirs(sess)
        base = tc.enabled_tools(sess)
        check("always_on_present", {"tools", "sign_step", "session_memory"} <= base, str(base))
        check("others_off_by_default", "web" not in base and "github" not in base)

        # 3) enable
        r = tc.tools_catalog_tool(action="enable", name="web", session_path=sess)
        check("enable_ok", r.startswith("ok"), r[:100])
        check("enabled_in_set", "web" in tc.enabled_tools(sess))
        check("persisted", os.path.exists(os.path.join(sess, "enabled_tools.json")))
        saved = json.load(open(os.path.join(sess, "enabled_tools.json")))
        check("persist_content", "web" in saved, str(saved))

        # 4) перезагрузка состояния из файла
        tc._enabled.pop(sess, None)
        check("reload_from_disk", "web" in tc.enabled_tools(sess))

        # 5) always-on и неизвестные имена
        check("always_on_noop", "и так всегда" in tc.tools_catalog_tool(action="enable", name="sign_step", session_path=sess))
        check("unknown_tool_error", tc.tools_catalog_tool(action="enable", name="нет_такого", session_path=sess).startswith("Error"))
        check("no_name_error", tc.tools_catalog_tool(action="enable", name="", session_path=sess).startswith("Error"))
        check("bad_action_error", tc.tools_catalog_tool(action="прыгни", session_path=sess).startswith("Error"))

        # 6) disable
        tc.tools_catalog_tool(action="enable", name="github", session_path=sess)
        tc.tools_catalog_tool(action="disable", name="github", session_path=sess)
        check("disabled", "github" not in tc.enabled_tools(sess))

        # 7) list
        lst = tc.tools_catalog_tool(action="list", session_path=sess)
        check("list_returns_catalog", "ИНСТРУМЕНТЫ" in lst)

    # 8) фильтрация payload (логика TI): только разрешённые имена
    defs = tm.get_tool_definitions()
    sess2 = "/tmp/nonexistent_sess_catalog_test"
    tc._enabled[sess2] = {"web"}
    allowed = tc.enabled_tools(sess2)
    filtered = [t for t in defs.values() if ((t or {}).get("function") or {}).get("name") in allowed]
    names = {t["function"]["name"] for t in filtered}
    check("payload_filtered", names == {"tools", "sign_step", "session_memory", "web"}, str(sorted(names)))
    tc._enabled.pop(sess2, None)

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ TOOLS CATALOG ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
