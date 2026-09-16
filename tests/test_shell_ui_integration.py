"""Интеграционный тест: реальное Textual-приложение + инструмент shell_exec.

Воспроизводит сценарий боя: ботинок вызывает shell_exec из рабочего потока
(textual_integration.py крутит _stream_turn в worker-thread), где ContextVar
active_app НЕ наследуется. Экран должен открываться через глобальный реестр
+ app.call_from_thread.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, "/home/user/prj/botinok")

from textual.app import App
from textual.widgets import Input, RichLog, Static

from core.shell_screen import ShellScreen
from core.shell_session import ShellSessionRegistry, TextualAppRegistry
from tools.shell_exec import _active_textual_app, shell_exec


class HostApp(App):
    CSS = ShellScreen.CSS

    def compose(self):
        yield Static("host")


@pytest.fixture
def registry():
    reg = ShellSessionRegistry.instance()
    yield reg
    for sid in [s["session_id"] for s in reg.list()]:
        s = reg.get(sid)
        if s is not None:
            try:
                s.kill()
            except Exception:
                pass


@pytest.fixture
def app():
    TextualAppRegistry.clear()
    a = HostApp()
    TextualAppRegistry.set_app(a)
    yield a
    TextualAppRegistry.clear()


async def _wait_screen_pushed(pilot, app, timeout=15.0):
    """Ждём, пока fire-and-forget push экрана докинется в стек."""
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        await pilot.pause(0.1)
        if len(app.screen_stack) >= 2:
            return True
    return False


@pytest.mark.asyncio
async def test_app_found_under_run_test(app):
    """ContextVar active_app установлен внутри app.run_test()."""
    async with app.run_test() as pilot:
        found = _active_textual_app()
        assert found is app or found is not None


@pytest.mark.asyncio
async def test_screen_opens_and_receives_input(app, registry):
    """Главной сценарий: экран открылся, вывод идёт в RichLog, ввод доходит до PTY."""
    async with app.run_test() as pilot:
        # Вызов инструмента имитирует рабочий поток бота: shell_exec()
        # пушит экран через app.call_from_thread (fire-and-forget).
        r = json.loads(shell_exec(
            command='echo UIOK; read -p "PICK> " v; echo "PICKED=$v"',
            interactive=True, tail_lines=30,
        ))
        sid = r["session_id"]
        assert sid.startswith("sh_")

        # Экран докинулся асинхронно — дождёмся его.
        assert await _wait_screen_pushed(pilot, app)
        scr = app.screen_stack[-1]
        assert isinstance(scr, ShellScreen)

        # Вывод сессии появился в RichLog экрана.
        for _ in range(60):
            await pilot.pause(0.1)
            log = scr.query_one("#shell_log", RichLog)
            log_text = "\n".join(getattr(l, "text", "") for l in log.lines)
            if "UIOK" in log_text:
                break
        assert "UIOK" in log_text

        # Пользовательский ввод через Input экрана доходит до PTY.
        inp = scr.query_one("#shell_input", Input)
        inp.value = "item7"
        scr.on_input_submitted(Input.Submitted(inp, "item7"))
        for _ in range(60):
            await pilot.pause(0.1)
            if "PICKED=item7" in scr.session.get_output():
                break
        assert "PICKED=item7" in scr.session.get_output()

        # Закрытие: _close() синхронно вынимает экран из стека.
        before = len(app.screen_stack)
        scr._close()
        await pilot.pause(0.2)
        assert len(app.screen_stack) < before

        # Сессия остаётся жить в реестре после закрытия экрана.
        assert registry.get(sid) is not None


@pytest.mark.asyncio
async def test_headless_without_app(registry):
    """Без Textual-приложения shell_exec всё равно работает (headless)."""
    TextualAppRegistry.clear()
    r = json.loads(shell_exec(
        command="echo HEADLESS_OK",
        interactive=True, tail_lines=20,
    ))
    assert r["session_id"].startswith("sh_")
    assert "HEADLESS_OK" in r.get("output_tail", "")
    s = registry.get(r["session_id"])
    assert s is not None
    assert s.wait(5)
    assert s.returncode == 0
