#!/usr/bin/env python3
"""
Smoke-тест встроенного подтверждения опасного действия.

Проверяем, что подтверждение показывается В окне вывода (#inline_confirm),
а не модальным экраном поверх правых панелей; y/n/esc и «отмена с причиной»
работают, после выбора элемент убирается.

Запуск: venv/bin/python -u tests/test_confirm_inline.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Input, OptionList, Static  # noqa: E402

from core.textual_app import BotinokTextualApp, ConfirmationScreen  # noqa: E402
from core.shell_session import TextualAppRegistry  # noqa: E402

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


async def main_async() -> int:
    print("=" * 70)
    print("Inline confirmation smoke-test")
    print("=" * 70)

    app = BotinokTextualApp()
    TextualAppRegistry.set_app(app)

    async with app.run_test(size=(140, 52)) as pilot:  # noqa: F841
        # 1. Показ — встроенно, модалки нет, контейнер активен; команда показана
        #    развёрнутой (shfmt), чтобы было понятно, что агент хочет сделать.
        cmd = ('echo "=== HWMON ===" ; ls /sys/class/hwmon/ ; '
               'for h in /sys/class/hwmon/hwmon*; do echo "-- $h"; ls $h/; done ; echo done')
        app.show_confirmation_prompt(
            "shell_exec", json.dumps({"action": "run", "command": cmd}), "")
        await asyncio.sleep(0.4)
        check("shown_inline", app.inline_confirm_widget is not None)
        check("container_active", app.inline_confirm_container.has_class("active"))
        check("no_modal", not isinstance(app.screen_stack[-1], ConfirmationScreen),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        opts = app.inline_confirm_widget.query_one(OptionList)
        check("options_present", opts is not None)
        # Без вложенной рамки OptionList — иначе артефакты «рамок».
        check("options_no_border", opts.styles.border_top[0] in ("", "none"),
              f"border={opts.styles.border_top[0]!r}")
        # Команда в подтверждении развёрнута на строки (видно, что будет выполнено).
        cmd_w = app.inline_confirm_widget.query_one("#inline_confirm_cmd", Static)
        cmd_text = str(cmd_w.content)
        check("confirm_command_formatted",
              "for h in" in cmd_text and len(cmd_text.splitlines()) >= 5,
              f"cmd={cmd_text!r}")

        # 2. Клавиша n — отказ, элемент убран, событие установлено.
        app.inline_confirm_widget.on_key(_Key("n"))
        await asyncio.sleep(0.4)
        check("reject_result", app._confirmation_result is False)
        check("reject_hidden", app.inline_confirm_widget is None)
        check("reject_inactive", not app.inline_confirm_container.has_class("active"))
        check("reject_event", app._confirmation_event.is_set())

        # 3. Клавиша y — подтверждение.
        app.show_confirmation_prompt("code_editor", '{"action": "delete"}', "")
        await asyncio.sleep(0.3)
        app.inline_confirm_widget.on_key(_Key("y"))
        await asyncio.sleep(0.4)
        check("confirm_result", app._confirmation_result is True)
        check("confirm_hidden", app.inline_confirm_widget is None)

        # 4. «Отменить с причиной» -> ввод -> отказ с причиной.
        app.show_confirmation_prompt("file_system", '{"action": "delete"}', "")
        await asyncio.sleep(0.3)
        widget = app.inline_confirm_widget
        reason_input = Input(placeholder="причина отказа...", id="inline_confirm_reason")
        widget.mount(reason_input)
        await asyncio.sleep(0.2)
        widget._reason_mode = True
        widget.on_input_submitted(Input.Submitted(reason_input, "не сейчас"))
        await asyncio.sleep(0.4)
        check("reason_result", app._confirmation_result is False)
        check("reason_text", "не сейчас" in (app._confirmation_reason or ""),
              f"reason={app._confirmation_reason!r}")
        check("reason_hidden", app.inline_confirm_widget is None)

        TextualAppRegistry.clear()
        print("=" * 70)
        if FAILURES:
            print(f"Провалы: {FAILURES}")
        else:
            print("✅ INLINE CONFIRMATION SMOKE-ТЕСТ ПРОЙДЕН")
        os._exit(1 if FAILURES else 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
