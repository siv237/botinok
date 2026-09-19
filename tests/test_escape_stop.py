#!/usr/bin/env python3
"""
Тест остановки по Esc — выстраданный инвариант.

Проверяем:
- Esc при активном ходе (стрим ИЛИ работающий инструмент) останавливает агента;
- фокус на встроенном терминале больше НЕ проглатывает Esc (не уходит в PTY);
- в покое Esc по-прежнему очищает ввод, а не «стоп».

Запуск: venv/bin/python -u tests/test_escape_stop.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.textual_app import BotinokTextualApp  # noqa: E402
from core.shell_screen import maybe_stop_from_terminal  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def test_terminal_escape_unit() -> None:
    class Ev:
        def __init__(self, key):
            self.key = key
            self.stopped = False

        def stop(self):
            self.stopped = True

    class App:
        def __init__(self, active):
            self._active = active
            self.stopped = 0
            self.logged = 0

        def turn_in_progress(self):
            return self._active

        def request_stop(self):
            self.stopped += 1

        def _log_stop_once(self):
            self.logged += 1

    class W:
        def __init__(self, app):
            self.app = app

    # Идёт ход → Esc из терминала останавливает и НЕ уходит в PTY.
    ev = Ev("escape")
    app = App(True)
    ok = maybe_stop_from_terminal(W(app), ev)
    check("terminal_escape_stops", ok and ev.stopped and app.stopped == 1,
          f"ok={ok} stopped={ev.stopped} req={app.stopped}")

    # Покой → Esc не трогаем (прокидываем дальше).
    ev2 = Ev("escape")
    app2 = App(False)
    ok2 = maybe_stop_from_terminal(W(app2), ev2)
    check("terminal_escape_idle_pass", (not ok2) and (not ev2.stopped) and app2.stopped == 0,
          f"ok={ok2} stopped={ev2.stopped}")

    # Не Esc — не наше дело.
    ev3 = Ev("a")
    ok3 = maybe_stop_from_terminal(W(App(True)), ev3)
    check("terminal_other_key_pass", not ok3)


async def main() -> int:
    print("=" * 70)
    print("Escape stop smoke-test")
    print("=" * 70)

    test_terminal_escape_unit()

    app = BotinokTextualApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await asyncio.sleep(0.3)

        # 1. Стрим, фокус в композере → Esc останавливает.
        app.set_focus(app.input_widget)
        app.is_streaming = True
        app.active_tools = []
        app._stop_requested = False
        await pilot.press("escape")
        await asyncio.sleep(0.15)
        check("escape_stops_stream", app._stop_requested)

        # 2. Нет стрима, но работает инструмент → Esc тоже останавливает.
        app.is_streaming = False
        app.active_tools = [{"name": "shell_exec", "status": "running",
                             "start_time": 0, "query": "", "result": "", "size_kb": 0}]
        app._stop_requested = False
        await pilot.press("escape")
        await asyncio.sleep(0.15)
        check("escape_stops_running_tool", app._stop_requested)

        # 3. Фокус на кнопке крестика мысли → Esc всё равно останавливает.
        app.active_tools = []
        app.is_streaming = True
        app._queued_inputs.append("x")
        app._render_thought_queue()
        await asyncio.sleep(0.1)
        from textual.widgets import Button
        btns = list(app.query(Button))
        if btns:
            app.set_focus(btns[0])
        app._stop_requested = False
        await pilot.press("escape")
        await asyncio.sleep(0.15)
        check("escape_stops_button_focus", app._stop_requested)

        # 4. Покой: Esc очищает ввод, а не останавливает.
        app.is_streaming = False
        app.active_tools = []
        app._stop_requested = False
        app.input_widget.text = "какой-то текст"
        app.set_focus(app.input_widget)
        await pilot.press("escape")
        await asyncio.sleep(0.15)
        check("escape_idle_clears_input", app.input_widget.text == "" and not app._stop_requested,
              f"text={app.input_widget.text!r} stop={app._stop_requested}")

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ ESCAPE STOP SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
