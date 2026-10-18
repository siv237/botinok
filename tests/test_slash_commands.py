#!/usr/bin/env python3
"""Slash-команды: реестр + автокомплит-список под полем ввода.

- Реестр `core/slash_commands.py`: единственная точка правды для /help и
  списка под Composer; метки без «[» (уезжают в rich-разметку /help).
- Composer: «/» открывает список, набор фильтрует по префиксу, ↓/↑ ходят
  по кандидатам, Tab/Enter дописывают, Esc сначала закрывает список,
  пробел (вставленный командой) список закрывает.

Запуск: venv/bin/python -u tests/test_slash_commands.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.slash_commands import (  # noqa: E402
    SLASH_COMMANDS, prefix_matches, command_label, command_completion, help_rows)

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


def _names(entries):
    return [e[0] for e in entries]


def test_registry():
    all_names = _names(SLASH_COMMANDS)
    check("реестр без дублей", len(all_names) == len(set(all_names)), str(all_names))
    check("«/» alone — все команды",
          _names(prefix_matches("/")) == all_names)
    check("префикс /mo — model, models",
          _names(prefix_matches("/mo")) == ["model", "models"],
          str(_names(prefix_matches("/mo"))))
    check("регистр не важен", _names(prefix_matches("/K")) == ["key"])
    check("не команда — пусто", prefix_matches("привет") == [])
    check("пробел (аргументы) — пусто", prefix_matches("/model qwen") == [])
    check("неизвестный слэш — пусто", prefix_matches("/xyz") == [])


def test_markup_safety():
    """Метки/описания уходят в rich-разметку /help: скобок «[» быть не должно."""
    bad = [(lbl, desc) for lbl, desc in help_rows()
           if "[" in lbl or "[" in desc]
    check("нет «[» в метках и описаниях", not bad, str(bad))
    check("метка со скобкой-аргументом",
          command_label(("ctx", "<n>", "x")) == "/ctx <n>")
    check("completion всегда с пробелом",
          command_completion(("help", "", "x")) == "/help "
          and command_completion(("model", "<name>", "x")) == "/model ")
    labels = [lbl for lbl, _ in help_rows()]
    check("/key в /help", "/key" in labels)
    check("/theme в /help", any(lbl.startswith("/theme") for lbl in labels), str(labels))


def test_popup():
    from core.textual_app import BotinokTextualApp
    from textual.widgets import OptionList

    app = BotinokTextualApp(session_path="")
    submitted_cmds = []
    app.on_slash_command = lambda t: submitted_cmds.append(t)

    async def run():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            c = app.input_widget
            lst = app.query_one("#slash_options", OptionList)

            # «/» — список всех команд.
            await pilot.press("/")
            await pilot.pause()
            check("«/» открывает список", app.slash_popup_visible())
            check("все команды в списке",
                  lst.option_count == len(SLASH_COMMANDS),
                  f"{lst.option_count} != {len(SLASH_COMMANDS)}")

            # Фильтрация по префиксу.
            await pilot.press("m")
            await pilot.pause()
            check("«/m» фильтрует до model, models",
                  lst.option_count == 2 and c.text == "/m",
                  f"count={lst.option_count} text={c.text!r}")
            check("подсветка на первом", lst.highlighted == 0)

            # ↓/↑ по кандидатам.
            await pilot.press("down")
            await pilot.pause()
            check("↓ подсвечивает второй", lst.highlighted == 1, str(lst.highlighted))
            await pilot.press("up")
            await pilot.pause()
            check("↑ возвращает на первый", lst.highlighted == 0, str(lst.highlighted))

            # Tab дописывает выбранное (с пробелом — список закрыт).
            await pilot.press("tab")
            await pilot.pause()
            check("Tab подставил /model ",
                  c.text == "/model ", f"text={c.text!r}")
            check("список закрылся", not app.slash_popup_visible())

            # Enter дописывает неполный префикс, НЕ отправляя.
            c.text = ""
            c._paste_until = 0.0
            for ch in "/cl":
                await pilot.press(ch)
                await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            check("Enter дописал /clear ",
                  c.text == "/clear ", f"text={c.text!r}")
            check("ниче не отправлено пока", submitted_cmds == [], str(submitted_cmds))

            # Второй Enter — отправка (список уже скрыт).
            c._paste_until = 0.0
            await pilot.press("enter")
            await pilot.pause()
            check("второй Enter отправил /clear",
                  submitted_cmds == ["/clear"], str(submitted_cmds))

            # Точное имя команды отправляется сразу одним Enter.
            submitted_cmds.clear()
            c.text = "/help"
            await pilot.pause()
            check("точное имя держит список открытым", app.slash_popup_visible())
            c._paste_until = 0.0
            await pilot.press("enter")
            await pilot.pause()
            check("один Enter с /help — отправка",
                  submitted_cmds == ["/help"], str(submitted_cmds))
            check("ввод очищен после отправки", (c.text or "") == "", repr(c.text))

            # Esc: первый — закрыть список (текст цел), второй — очистить.
            await pilot.press("/")
            await pilot.press("v")
            await pilot.pause()
            esc_state = (app.slash_popup_visible(), c.text)
            c._paste_until = 0.0
            await pilot.press("escape")
            await pilot.pause()
            check("Esc закрывает список, текст цел",
                  esc_state[0] and not app.slash_popup_visible() and c.text == "/v",
                  f"before={esc_state} after={c.text!r}")
            await pilot.press("escape")
            await pilot.pause()
            check("второй Esc очищает ввод", (c.text or "") == "", repr(c.text))

            # Обычный текст список не открывает.
            for ch in "hello":
                await pilot.press(ch)
                await pilot.pause()
            check("обычный текст без списка", not app.slash_popup_visible())

    asyncio.run(run())


def main() -> int:
    print("=" * 60)
    print("slash-команды: реестр + автокомплит")
    print("=" * 60)
    os.environ["BOTINOK_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="botinok_slash_")
    test_registry()
    test_markup_safety()
    test_popup()
    print("-" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())