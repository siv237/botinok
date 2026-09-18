#!/usr/bin/env python3
"""
Smoke-тест dangerous mode и подтверждений.

Проверяем:
  * в простом режиме опасные действия вне сессии блокируются, а внутри — нет;
  * запрос переключения в dangerous mode (kind="switch") и его отказ;
  * автосогласие на сессию (галочка), флаг в шапке и отключение по клику.

Запуск: venv/bin/python -u tests/test_dangerous_mode.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Checkbox, OptionList  # noqa: E402

from core.textual_app import BotinokTextualApp  # noqa: E402
from core.shell_session import TextualAppRegistry  # noqa: E402
from core.tool_manager import ToolManager  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class _Key:
    def __init__(self, k: str) -> None:
        self.key = k
        self.character = k

    def stop(self) -> None:
        pass


class _Click:
    def __init__(self, widget) -> None:
        self.widget = widget
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True


def test_tool_gate() -> None:
    print("-- ToolManager gate (простой режим) --")
    os.environ["BOTINOK_DANGEROUS"] = "0"
    tm = ToolManager()
    session = tempfile.mkdtemp(prefix="botinok_sess_")
    outside = tempfile.mkdtemp(prefix="botinok_out_")

    r = tm.call_tool("file_system", {"action": "mkdir", "path": os.path.join(session, "sub")},
                     session_path=session)
    check("fs_mkdir_inside_ok", "Создана директория" in r, r)

    r = tm.call_tool("file_system", {"action": "mkdir", "path": os.path.join(outside, "sub")},
                     session_path=session)
    check("fs_mkdir_outside_blocked", r.startswith("Error"), r)

    r = tm.call_tool("shell_exec", {"action": "run", "command": "echo hi"}, session_path=session)
    check("shell_run_blocked", r.startswith("Error"), r)

    r = tm.call_tool("code_editor", {"action": "write", "path": os.path.join(session, "a.txt"),
                                     "content": "x", "create": True}, session_path=session)
    check("editor_write_inside_ok", '"changed": true' in r, r)

    r = tm.call_tool("code_editor", {"action": "write", "path": os.path.join(outside, "a.txt"),
                                     "content": "x", "create": True}, session_path=session)
    check("editor_write_outside_blocked", r.startswith("Error"), r)


async def test_ui() -> None:
    print("-- UI: switch / автосогласие / шапка --")
    app = BotinokTextualApp()
    TextualAppRegistry.set_app(app)
    async with app.run_test(size=(140, 52)) as pilot:
        # Запрос переключения в dangerous mode: только да/нет, без галочки.
        app.show_confirmation_prompt("code_editor", '{"action": "write"}', "", "switch")
        await pilot.pause()
        w = app.inline_confirm_widget
        check("switch_inline", w is not None and w._switch_kind)
        opts = [o.id for o in w.query_one(OptionList)._options]
        check("switch_options", opts == ["yes", "no"], str(opts))
        check("switch_no_auto", not w.query(Checkbox))
        w.on_key(_Key("n"))
        await pilot.pause()
        check("switch_denied_flag", app.dangerous_switch_denied is True)

        # Обычное подтверждение: галочка автосогласия.
        app.show_confirmation_prompt("shell_exec", '{"command": "ls"}', "", "confirm")
        await pilot.pause()
        w = app.inline_confirm_widget
        check("confirm_has_auto", bool(w.query(Checkbox)))
        w._auto.value = True
        w.on_key(_Key("y"))
        await pilot.pause()
        check("auto_confirm_set", app.dangerous_auto_confirm is True)
        check("header_flag_on", app.auto_flag.has_class("on"))

        # Автосогласие пропускает окно подтверждения.
        app.show_confirmation_prompt("shell_exec", '{"command": "pwd"}', "", "confirm")
        await pilot.pause()
        check("auto_short_circuit",
              app._confirmation_result is True and app.inline_confirm_widget is None)

        # Клик по флагу в шапке отключает автосогласие.
        app.on_click(_Click(app.auto_flag))
        await pilot.pause()
        check("click_disables", app.dangerous_auto_confirm is False)
        check("header_flag_off", not app.auto_flag.has_class("on"))


async def main_async() -> int:
    print("=" * 70)
    print("Dangerous mode smoke-test")
    print("=" * 70)
    test_tool_gate()
    await test_ui()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ DANGEROUS MODE SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
