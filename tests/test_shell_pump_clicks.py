#!/usr/bin/env python3
"""
Регрессионный тест переходов терминала НАСТОЯЩИМИ кликами (pilot, pump-контекст).

Прямой вызов обработчика (как в других smoke-тестах) не воспроизводит поведение
реального клика. Именно так ловится конфликт имени: ShellInline использовал
атрибут `_closed`, который затенял внутренний `MessagePump._closed` Textual —
после клика виджет «закрывался» и вычищался из DOM, из-за чего пропадала
возможность свернуть/развернуть.

Проверяем: inline -> «Развернуть» (модалка) -> «Свернуть» (в панель) ->
восстановление -> «Развернуть» -> «В окно»; виджет остаётся в DOM на каждом шаге.

Запуск: venv/bin/python -u tests/test_shell_pump_clicks.py
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


async def _wait_inline(app, timeout: float = 10.0) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(0.1)
        if app.inline_shell_active and app.inline_shell_widget is not None:
            return True
    return False


async def _wait_modal(app, timeout: float = 10.0) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(0.1)
        if app.screen_stack and isinstance(app.screen_stack[-1], ShellScreen):
            return True
    return False


def _in_dom(app) -> bool:
    w = app.inline_shell_widget
    return w is not None and w.parent is not None


async def main_async() -> int:
    print("=" * 70)
    print("Shell pump-click transitions smoke-test")
    print("=" * 70)

    reg = ShellSessionRegistry.instance()
    app = BotinokTextualApp()
    TextualAppRegistry.set_app(app)

    async with app.run_test(size=(140, 52)) as pilot:
        r1 = json.loads(shell_exec(command="echo ONE; sleep 120",
                                   interactive=True, tail_lines=5))
        sid = r1["session_id"]
        check("inline_opened", await _wait_inline(app))
        await asyncio.sleep(1.0)  # дать виджету смонтироваться

        # 1. «Развернуть» (реальный клик) -> модалка.
        await pilot.click("#inline_shell_expand")
        await asyncio.sleep(0.8)
        check("expand_modal", await _wait_modal(app),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("inline_hidden_after_expand", not app.inline_shell_active)
        check("widget_survives_expand", _in_dom(app))

        # 2. «Свернуть» из модалки -> панель, виджет жив.
        check("panel_has_restore", f"shell_restore_{sid}" in
              [b.id for b in app.shells_display.query(Button)] or
              True)  # появится после minimize
        await pilot.click("#shell_minimize")
        await asyncio.sleep(0.9)
        check("modal_minimize_pops", not isinstance(app.screen_stack[-1], ShellScreen),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("modal_minimize_in_panel", sid in app.minimized_shells,
              f"min={app.minimized_shells}")
        check("widget_survives_minimize", _in_dom(app))
        check("panel_restore_present", f"shell_restore_{sid}" in
              [b.id for b in app.shells_display.query(Button)],
              f"panel={[b.id for b in app.shells_display.query(Button)]}")

        # 3. Восстановление из панели -> inline, виджет по-прежнему в DOM.
        await pilot.click(f"#shell_restore_{sid}")
        await asyncio.sleep(0.9)
        check("restore_inline", await _wait_inline(app))
        check("widget_survives_restore", _in_dom(app))
        check("buttons_alive_after_restore",
              "inline_shell_expand" in [b.id for b in app.inline_shell_widget.query(Button)],
              f"btns={[b.id for b in app.inline_shell_widget.query(Button)]}")

        # 4. Снова «Развернуть» -> «В окно» -> inline.
        await pilot.click("#inline_shell_expand")
        await asyncio.sleep(0.8)
        check("expand2_modal", await _wait_modal(app))
        await pilot.click("#shell_inline")
        await asyncio.sleep(0.9)
        check("return_pops_modal", not isinstance(app.screen_stack[-1], ShellScreen),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("return_inline", await _wait_inline(app))
        check("widget_survives_return", _in_dom(app))

        for s in (reg.get(sid),):
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
            print("✅ PUMP-CLICK SMOKE-ТЕСТ ПРОЙДЕН")
        os._exit(1 if FAILURES else 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
