#!/usr/bin/env python3
"""
Тест разворота shell-команды через shfmt и клика по заголовку терминала.

Проверяем:
  * `format_shell_command` разбивает однострочник на строки (shfmt), сохраняя
    «for …; do» и выравнивая тело/`done`;
  * клик по заголовку встроенного терминала показывает развёрнутую команду,
    повторный клик — скрывает;
  * если shfmt недоступен — возвращается исходная команда.

Запуск: venv/bin/python -u tests/test_shell_command_format.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Static  # noqa: E402

import core.shell_screen as shell_screen  # noqa: E402
from core.shell_screen import format_shell_command  # noqa: E402
from core.textual_app import BotinokTextualApp  # noqa: E402
from core.shell_session import ShellSessionRegistry, TextualAppRegistry  # noqa: E402
from tools.shell_exec import shell_exec  # noqa: E402

FAILURES = []
CMD = ('echo "=== HWMON ===" ; ls /sys/class/hwmon/ ; '
       'for h in /sys/class/hwmon/hwmon*; do echo "-- $h"; ls $h/ | head -5; done ; echo done')


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


async def main_async() -> int:
    print("=" * 70)
    print("Shell command format (shfmt) smoke-test")
    print("=" * 70)

    # 1. Форматирование строки: разворот и выравнивание.
    out = format_shell_command(CMD)
    lines = out.splitlines()
    check("split_multiline", len(lines) >= 6, f"lines={lines}")
    check("keeps_for_do", any("for h in" in l and "do" in l for l in lines), f"lines={lines}")
    check("has_done", any(l.strip() == "done" for l in lines), f"lines={lines}")
    check("body_indented", any(l.startswith("  ") for l in lines), f"lines={lines}")
    check("no_semicolon_list", "echo done" in out, f"out={out!r}")

    # 1b. Тело раскрытого вызова в истории сессии (клик по строке) — тоже shfmt.
    tool_body = BotinokTextualApp._format_tool_call(None, "shell_exec", {"command": CMD})
    check("history_tool_body_formatted",
          "for h in" in tool_body and len(tool_body.splitlines()) >= 6,
          f"body={tool_body!r}")

    # 2. Если shfmt недоступен — возвращаем исходную строку.
    saved = shell_screen._SHXFMT_PATH
    try:
        shell_screen._SHXFMT_PATH = "nonexistent"  # заставит _shfmt_binary вернуть None
        shell_screen.format_shell_command.cache_clear()
        check("fallback_without_shfmt", format_shell_command(CMD) == CMD)
    finally:
        shell_screen._SHXFMT_PATH = saved
        shell_screen.format_shell_command.cache_clear()

    # 3. Клик по заголовку встроенного терминала разворачивает команду.
    app = BotinokTextualApp()
    TextualAppRegistry.set_app(app)
    async with app.run_test(size=(140, 52)) as pilot:
        r = json.loads(shell_exec(command=CMD, interactive=True, tail_lines=5))
        sid = r["session_id"]
        check("inline_opened", await _wait_inline(app))
        await asyncio.sleep(0.8)
        cmd_w = app.inline_shell_widget.query_one("#inline_shell_cmd", Static)
        check("hidden_initially", not cmd_w.has_class("show"))
        await pilot.click("#inline_shell_title")
        await asyncio.sleep(0.3)
        check("click_shows", cmd_w.has_class("show"))
        text = str(cmd_w.content)
        check("click_content_formatted", "for h in" in text and len(text.splitlines()) >= 6,
              f"text={text[:200]!r}")
        await pilot.click("#inline_shell_title")
        await asyncio.sleep(0.3)
        check("second_click_hides", not cmd_w.has_class("show"))

        sess = ShellSessionRegistry.instance().get(sid)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass
        TextualAppRegistry.clear()

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
    else:
        print("✅ SHELL COMMAND FORMAT SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(1 if FAILURES else 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
