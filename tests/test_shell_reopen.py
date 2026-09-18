#!/usr/bin/env python3
"""
Smoke-тест: переоткрытие встроенного терминала и статус в заголовке.

Регрессии:
  * после «Закрыть» inline новый shell снова открывается встроенно
    (call_after_refresh не срабатывал на простое — заменили на call_next);
  * в заголовке терминала виден статус и счётчик: «идёт Ns»/«завершён за Ns».

Запуск: venv/bin/python -u tests/test_shell_reopen.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Button, RichLog, Static  # noqa: E402

from core.textual_app import BotinokTextualApp  # noqa: E402
from core.shell_session import ShellSessionRegistry, TextualAppRegistry  # noqa: E402
from tools.shell_exec import shell_exec  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _press(widget, button_id: str) -> bool:
    btn = next((b for b in widget.query(Button) if b.id == button_id), None)
    if btn is None:
        return False
    widget.on_button_pressed(Button.Pressed(btn))
    return True


async def _wait_inline(app, timeout: float = 10.0) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(0.1)
        if app.inline_shell_active and app.inline_shell_widget is not None:
            return True
    return False


def _title(app) -> str:
    try:
        return str(app.query_one("#inline_shell_title", Static).content)
    except Exception:
        return ""


async def main_async() -> int:
    print("=" * 70)
    print("Shell reopen + title status smoke-test")
    print("=" * 70)

    reg = ShellSessionRegistry.instance()
    app = BotinokTextualApp()
    TextualAppRegistry.set_app(app)

    async with app.run_test(size=(140, 52)) as pilot:  # noqa: F841
        # 1. Первый shell — встроенно, заголовок показывает «идёт».
        r1 = json.loads(shell_exec(command="sleep 60", interactive=True, tail_lines=5))
        sid1 = r1["session_id"]
        check("s1_inline", await _wait_inline(app))
        await asyncio.sleep(0.4)
        t1 = _title(app)
        check("title_running", "идёт" in t1 and "s" in t1, f"title={t1!r}")

        # 2. Закрываем inline.
        check("close_pressed", _press(app.inline_shell_widget, "inline_shell_close"))
        await asyncio.sleep(0.5)
        check("closed_inline", not app.inline_shell_active)
        check("closed_session", not reg.get(sid1).is_running())

        # 3. Новый shell обязан снова открыться встроенно (регрессия reopen).
        r2 = json.loads(shell_exec(command="echo DONE; sleep 60",
                                   interactive=True, tail_lines=5))
        sid2 = r2["session_id"]
        check("reopen_inline", await _wait_inline(app))
        check("reopen_same_session",
              getattr(app.inline_shell_widget.session, "session_id", "") == sid2,
              f"sid={getattr(app.inline_shell_widget.session, 'session_id', '')}")

        # 4. Когда процесс завершился — заголовок показывает «завершён за N».
        app.inline_shell_widget.session.send_key("ctrl-c")
        for _ in range(50):
            await asyncio.sleep(0.1)
            if not reg.get(sid2).is_running():
                break
        await asyncio.sleep(0.4)
        t2 = _title(app)
        check("title_finished", "завершено за" in t2, f"title={t2!r}")
        # В логе терминала есть явная строка-маркер завершения.
        try:
            log = app.query_one("#inline_shell_log", RichLog)
            log_text = "\n".join(getattr(l, "text", "") for l in log.lines)
        except Exception as e:
            log_text = f"<err {e}>"
        check("log_done_marker", "завершено" in log_text, f"log={log_text[-200:]!r}")

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
            print("✅ REOPEN/TITLE SMOKE-ТЕСТ ПРОЙДЕН")
        os._exit(1 if FAILURES else 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
