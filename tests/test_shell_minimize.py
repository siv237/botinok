#!/usr/bin/env python3
"""
Smoke-тест встроенного терминала: inline по умолчанию, разворот/возврат,
сворачивание и закрытие.

Проверяем новый UX (0.5):
  * shell из агента открывается ВСТРОЕННОЙ панелью над чатом, а не модалкой;
  * в панели есть кнопки «Развернуть»/«Свернуть»/«Закрыть»;
  * «Развернуть» открывает модальное окно ShellScreen, панель исчезает;
  * «В окно» в модалке возвращает панель на место, модалка снимается;
  * «Свернуть» убирает панель — сессия жива и видна в панели свёрнутых;
  * возврат из панели снова встраивает терминал;
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
from core.shell_screen import ShellScreen, ShellInline  # noqa: E402
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


def _press(widget, button_id: str) -> bool:
    """Нажать кнопку виджета напрямую (без pilot: после pop_screen harness не
    может дождаться обработки сообщений — известное ограничение Textual)."""
    btn = next((b for b in _buttons(widget) if b.id == button_id), None)
    if btn is None:
        return False
    widget.on_button_pressed(Button.Pressed(btn))
    return True


async def _nap(t: float = 0.4) -> None:
    await asyncio.sleep(t)


async def _wait_inline(app, timeout: float = 15.0) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(0.1)
        if app.inline_shell_active and app.inline_shell_widget is not None:
            return True
    return False


async def _wait_modal(app, timeout: float = 15.0) -> bool:
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(0.1)
        if app.screen_stack and isinstance(app.screen_stack[-1], ShellScreen):
            return True
    return False


async def _session_id(app) -> str:
    w = app.inline_shell_widget
    return getattr(getattr(w, "session", None), "session_id", "")


async def main_async() -> int:
    print("=" * 70)
    print("Embedded shell inline/expand/return/minimize smoke-test")
    print("=" * 70)

    reg = ShellSessionRegistry.instance()
    app = BotinokTextualApp()
    TextualAppRegistry.set_app(app)

    async with app.run_test(size=(140, 52)) as pilot:  # noqa: F841
        # 1. По умолчанию — встроенная панель над чатом, не модалка.
        r = json.loads(shell_exec(command="echo ONE; sleep 60", interactive=True, tail_lines=5))
        sid1 = r["session_id"]
        check("inline_opened", await _wait_inline(app))
        check("inline_is_expected_session", await _session_id(app) == sid1,
              f"sid={await _session_id(app)} want={sid1}")
        check("no_modal_by_default", not isinstance(app.screen_stack[-1], ShellScreen),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("container_active", app.inline_shell_container.has_class("active"))
        check("inline_widget_type", isinstance(app.inline_shell_widget, ShellInline))
        ids = [b.id for b in _buttons(app.inline_shell_widget)]
        check("inline_has_buttons",
              {"inline_shell_expand", "inline_shell_minimize", "inline_shell_close"} <= set(ids),
              f"ids={ids}")

        # Панель терминалов: сверху всегда активная строка с тикающим счётчиком.
        await _nap(0.3)
        check("panel_visible_while_inline", app.shells_display.has_class("has-items"))
        check("panel_has_active_row", app._shells_active_widget is not None)
        active_txt = ""
        try:
            from textual.widgets import Static
            active_txt = str(app.query_one("#shells_active", Static).content)
        except Exception:
            active_txt = ""
        check("active_row_has_counter", "активный" in active_txt and "s" in active_txt,
              f"text={active_txt!r}")

        # 2. Второй запуск: новый inline, первый автоматически свёрнут.
        r2 = json.loads(shell_exec(command="echo TWO; sleep 60", interactive=True, tail_lines=5))
        sid2 = r2["session_id"]
        check("second_inline", await _wait_inline(app) and await _session_id(app) == sid2)
        check("first_auto_minimized", sid1 in app.minimized_shells,
              f"min={app.minimized_shells}")

        # 3. «Развернуть» -> модальное окно, inline исчезает.
        check("press_expand", _press(app.inline_shell_widget, "inline_shell_expand"))
        await _nap()
        check("expand_pushes_modal", await _wait_modal(app),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("inline_gone_on_expand", not app.inline_shell_active)
        check("expanded_session_matches",
              getattr(app.screen_stack[-1].session, "session_id", "") == sid2)
        modal_ids = [b.id for b in _buttons(app.screen_stack[-1])]
        check("modal_has_inline_button", "shell_inline" in modal_ids, f"ids={modal_ids}")

        # 4. «Свернуть» ИМЕННО из модалки (не «В окно»): модалка снимается,
        #    сессия уходит в полоску, UI остаётся живым (не виснет).
        check("press_modal_minimize", _press(app.screen_stack[-1], "shell_minimize"))
        await _nap(0.8)
        check("modal_minimize_pops", not isinstance(app.screen_stack[-1], ShellScreen),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("modal_minimize_in_panel", sid2 in app.minimized_shells,
              f"min={app.minimized_shells}")
        check("modal_minimize_row",
              f"shell_restore_{sid2}" in [b.id for b in _buttons(app.shells_display)])

        # 5. Возврат из панели снова встраивает терминал.
        restore = next((b for b in _buttons(app.shells_display)
                        if b.id == f"shell_restore_{sid2}"), None)
        check("panel_restore_button_found", restore is not None)
        if restore is not None:
            check("press_panel_restore", _press(app, f"shell_restore_{sid2}"))
        check("restore_embeds_inline", await _wait_inline(app) and await _session_id(app) == sid2,
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("restore_removes_from_panel", sid2 not in app.minimized_shells,
              f"min={app.minimized_shells}")

        # 6. «Развернуть» -> «В окно»: модалка снимается, панель возвращается.
        check("press_expand2", _press(app.inline_shell_widget, "inline_shell_expand"))
        check("expand2_modal", await _wait_modal(app))
        check("press_return", _press(app.screen_stack[-1], "shell_inline"))
        check("return_embeds_inline", await _wait_inline(app) and await _session_id(app) == sid2)
        await _nap(0.3)
        check("modal_popped", not isinstance(app.screen_stack[-1], ShellScreen),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")

        # 7. «Свернуть» inline -> панель убрана, обе сессии в панели свёрнутых.
        check("press_minimize", _press(app.inline_shell_widget, "inline_shell_minimize"))
        await _nap()
        check("minimize_removes_inline", not app.inline_shell_active)
        check("container_inactive", not app.inline_shell_container.has_class("active"))
        # Скрытый терминал не должен удерживать фокус (иначе клавиатура «в никуда»).
        focused_id = getattr(app.focused, "id", "") if app.focused is not None else ""
        check("focus_left_hidden_terminal", focused_id != "inline_shell_input",
              f"focused={focused_id!r}")
        check("both_in_panel", {sid1, sid2} <= app.minimized_shells,
              f"min={app.minimized_shells}")
        check("sessions_alive", reg.get(sid1).is_running() and reg.get(sid2).is_running())
        panel_ids = [b.id for b in _buttons(app.shells_display)]
        check("panel_lists_both",
              f"shell_restore_{sid1}" in panel_ids and f"shell_restore_{sid2}" in panel_ids,
              f"panel={panel_ids}")
        check("panel_has_kill_buttons",
              f"shell_kill_{sid1}" in panel_ids and f"shell_kill_{sid2}" in panel_ids,
              f"panel={panel_ids}")
        check("panel_rows_single_line",
              all(e["row"].size.height <= 1 for e in app._shell_widgets.values()),
              f"rows={[(e['row'].size.width, e['row'].size.height)
                       for e in app._shell_widgets.values()]}")

        # 8. Развернуть sid2 из панели и «Закрыть» из модалки: снимается, сессия
        #    завершается (та же deferred-схема, что и у «Свернуть» из модалки).
        check("press_panel_restore2", _press(app, f"shell_restore_{sid2}"))
        check("restore2_inline", await _wait_inline(app) and await _session_id(app) == sid2)
        check("press_expand3", _press(app.inline_shell_widget, "inline_shell_expand"))
        check("expand3_modal", await _wait_modal(app))
        # Пока процесс идёт, кнопка — «Прервать»: SIGINT, модалка остаётся.
        check("press_modal_interrupt", _press(app.screen_stack[-1], "shell_close"))
        for _ in range(50):
            await _nap(0.1)
            if not reg.get(sid2).is_running():
                break
        await _nap(0.3)
        check("modal_interrupt_stops", not reg.get(sid2).is_running())
        check("modal_still_open", isinstance(app.screen_stack[-1], ShellScreen))
        # Теперь кнопка — «Закрыть»: снимает модалку и завершает сессию.
        check("press_modal_close", _press(app.screen_stack[-1], "shell_close"))
        await _nap(0.8)
        check("modal_close_pops", not isinstance(app.screen_stack[-1], ShellScreen),
              f"stack={[type(x).__name__ for x in app.screen_stack]}")
        check("modal_close_terminates", not reg.get(sid2).is_running())
        check("modal_close_removes_panel", sid2 not in app.minimized_shells,
              f"min={app.minimized_shells}")
        check("modal_close_no_inline", not app.inline_shell_active)

        # 9. Кнопка «✕» завершает оставшуюся свёрнутую сессию.
        kill_btn = next((b for b in _buttons(app.shells_display)
                         if b.id == f"shell_kill_{sid1}"), None)
        check("panel_kill_button_found", kill_btn is not None)
        if kill_btn is not None:
            check("press_panel_kill", _press(app, f"shell_kill_{sid1}"))
        await _nap()
        check("panel_kill_terminates", not reg.get(sid1).is_running())
        check("panel_kill_removes", sid1 not in app.minimized_shells,
              f"min={app.minimized_shells}")

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
            print("✅ INLINE/EXPAND/RETURN SMOKE-ТЕСТ ПРОЙДЕН")
        # Textual test-harness дедлочит __aexit__ после pop модалки в не-tty —
        # выходим принудительно (см. test_shell_screen.py).
        os._exit(1 if FAILURES else 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
