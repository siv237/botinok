#!/usr/bin/env python3
"""
Smoke-тест сворачивания/возврата окон встроенного терминала.

Проверяем:
  * у окна ShellScreen есть кнопки «Свернуть» и «Закрыть»;
  * «Свернуть» убирает окно, сессия остаётся живой и попадает в панель
    свёрнутых терминалов на основном экране;
  * из панели окно можно вернуть (open_shell_session), оно уходит из панели;
  * «Закрыть» завершает сессию и убирает её из панели.

Запуск: venv/bin/python -u tests/test_shell_minimize.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Button  # noqa: E402

from core.textual_app import BotinokTextualApp  # noqa: E402
from core.shell_screen import ShellScreen  # noqa: E402
from core.shell_session import ShellSessionRegistry, TextualAppRegistry  # noqa: E402
from tools.shell_exec import shell_exec  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _buttons(widget):
    try:
        return [b for b in widget.query(Button)]
    except Exception:
        return []


async def _nap(t: float = 0.4) -> None:
    await asyncio.sleep(t)


async def main_async() -> int:
    print("=" * 70)
    print("ShellScreen minimize/restore/close smoke-test")
    print("=" * 70)

    reg = ShellSessionRegistry.instance()
    app = BotinokTextualApp()
    TextualAppRegistry.set_app(app)

    async with app.run_test(size=(140, 52)) as pilot:  # noqa: F841
        r = json.loads(shell_exec(command="echo ONE; sleep 60", interactive=True, tail_lines=5))
        sid1 = r["session_id"]
        await _nap()
        check("screen_opened", isinstance(app.screen_stack[-1], ShellScreen))

        r2 = json.loads(shell_exec(command="echo TWO; sleep 60", interactive=True, tail_lines=5))
        sid2 = r2["session_id"]
        await _nap()
        # Второй запуск открывает своё окно, первое — автоматически свёрнуто.
        check("second_open", isinstance(app.screen_stack[-1], ShellScreen))
        check("first_auto_minimized", sid1 in app.minimized_shells)

        screen = app.screen_stack[-1]
        ids = [b.id for b in _buttons(screen)]
        check("has_buttons", "shell_minimize" in ids and "shell_close" in ids,
              f"ids={ids}")

        # Свернуть текущее окно -> обе сессии в панели.
        minimize = next(b for b in _buttons(screen) if b.id == "shell_minimize")
        screen.on_button_pressed(Button.Pressed(minimize))
        await _nap()
        check("minimize_pops_screen", not isinstance(app.screen_stack[-1], ShellScreen),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("both_minimized", {sid1, sid2} <= app.minimized_shells,
              f"min={app.minimized_shells}")
        check("session1_alive", reg.get(sid1).is_running())
        check("session2_alive", reg.get(sid2).is_running())

        panel_ids = [b.id for b in _buttons(app.shells_display)]
        check("panel_lists_both",
              f"shell_restore_{sid1}" in panel_ids and f"shell_restore_{sid2}" in panel_ids,
              f"panel={panel_ids}")
        check("panel_visible", app.shells_display.has_class("has-items"))

        # Вернуть первое окно.
        app.open_shell_session(reg.get(sid1))
        await _nap()
        check("restore_pushes_screen", isinstance(app.screen_stack[-1], ShellScreen))
        check("restore_removes_from_panel", sid1 not in app.minimized_shells,
              f"min={app.minimized_shells}")

        # Закрыть вернувшееся окно -> сессия завершается и уходит из панели.
        screen2 = app.screen_stack[-1]
        close_btn = next(b for b in _buttons(screen2) if b.id == "shell_close")
        screen2.on_button_pressed(Button.Pressed(close_btn))
        await _nap()
        check("close_terminates_session", not reg.get(sid1).is_running())
        check("close_removes_from_panel", sid1 not in app.minimized_shells)

        for s in (reg.get(sid1), reg.get(sid2)):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        TextualAppRegistry.clear()

        print("=" * 70)
        if FAILURES:
            print(f"Провалы: {FAILURES}")
        else:
            print("✅ MINIMIZE SMOKE-ТЕСТ ПРОЙДЕН")
        # Textual test-harness дедлочит __aexit__ после pop модалки в не-tty —
        # выходим принудительно (см. test_shell_screen.py).
        os._exit(1 if FAILURES else 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
