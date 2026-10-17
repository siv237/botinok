#!/usr/bin/env python3
"""
Тест кнопки под полем ввода в textual_prompt: стрелка «вниз» переводит фокус
на кнопку, выбор кнопки возвращает её value; Enter в поле — отправляет текст.

Запуск: venv/bin/python -u tests/test_prompt_button.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Input, OptionList  # noqa: E402

from core.textual_prompts import _SelectApp, _TextApp  # noqa: E402

FAILURES = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


async def _run(actions, default="", buttons=None):
    app = _TextApp("addr?", default=default, buttons=buttons)
    async with app.run_test() as pilot:
        for a in actions:
            await pilot.press(a)
    return app, app.result


def test_button_navigation():
    app, result = asyncio.run(_run(["down", "enter"],
                                   buttons=[("🔎 Поиск", "?")]))
    check("выбор кнопки возвращает value", result == "?", str(result))


def test_enter_submits_text():
    _app, result = asyncio.run(_run(["enter"], default="http://y",
                                    buttons=[("b", "?")]))
    check("Enter в поле отправляет текст", result == "http://y", str(result))


def test_up_returns_to_input():
    async def go():
        app = _TextApp("addr?", default="", buttons=[("b", "?")])
        async with app.run_test() as pilot:
            inp = app.query_one("#t_input", Input)
            await pilot.press("down")
            moved = app.focused is app.query_one("#t_buttons", OptionList)
            await pilot.press("up")
            back = app.focused is inp
            await pilot.press("enter")
        return moved, back, app.result
    moved, back, result = asyncio.run(go())
    check("вниз — фокус на кнопках", moved)
    check("вверх — фокус на поле", back)
    check("Enter после возврата — текст", result == "", str(result))


def test_without_buttons():
    _app, result = asyncio.run(_run(["down", "enter"], default="z"))
    check("без кнопок down не ломает ввод", result == "z", str(result))


CHOICES = [("accounts/fireworks/models/qwen3-8b", "q8"),
           ("accounts/fireworks/models/kimi-k3", "k3"),
           ("accounts/fireworks/routers/kimi-k3-fast", "k3f")]


async def _select(keys, default=None):
    app = _SelectApp("pick", CHOICES, default, filterable=True)
    async with app.run_test() as pilot:
        for k in keys:
            await pilot.press(k)
        visible = app.query_one("#q_options", OptionList).option_count
    return visible, app.result


def test_filter_narrows_and_selects():
    visible, result = asyncio.run(_select(["k", "i", "m", "i", "down", "enter"]))
    check("фильтр сузил список", visible == 2, str(visible))
    check("выбор из отфильтрованного", result == "k3", str(result))


def test_filter_enter_in_field_selects_first():
    _visible, result = asyncio.run(_select(["q", "w", "enter"]))
    check("Enter в поле выбирает первый матч", result == "q8", str(result))


def test_select_without_filter():
    async def go():
        app = _SelectApp("pick", CHOICES, "k3", filterable=False)
        async with app.run_test() as pilot:
            await pilot.press("enter")
        return app.result
    check("без фильтра выбор как раньше", asyncio.run(go()) == "k3")


def main():
    print("=" * 60)
    print("prompt button tests")
    print("=" * 60)
    test_button_navigation()
    test_enter_submits_text()
    test_up_returns_to_input()
    test_without_buttons()
    test_filter_narrows_and_selects()
    test_filter_enter_in_field_selects_first()
    test_select_without_filter()
    print("-" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
