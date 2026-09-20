#!/usr/bin/env python3
"""F6: текст чата для пейджера (обычный терминал, выделение без Shift).

Проверяем:
- у приложения есть бинд F6 -> open_chat_in_pager;
- плоский лог чата накапливает сообщения пользователя/ассистента без разметки.

Запуск: venv/bin/python -u tests/test_chat_pager.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Markdown  # noqa: E402

from core.textual_app import BotinokTextualApp, Composer  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


async def main() -> int:
    print("=" * 70)
    print("Chat pager smoke-test")
    print("=" * 70)

    os.environ["BOTINOK_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="botinok_pager_")

    check("f6_on_composer", any(b.key == "f6" for b in Composer.BINDINGS))
    check("action_exists", hasattr(BotinokTextualApp, "action_open_chat_in_pager"))

    app = BotinokTextualApp(session_path="")
    app.on_submit = lambda t: None

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        check("pager_button", bool(app.query("#chat_pager_btn")))
        # F6 действительно доходит до действия (был случай: TextArea съедал клавишу).
        calls = []
        original = BotinokTextualApp.action_open_chat_in_pager

        def spy(self):
            calls.append(1)

        BotinokTextualApp.action_open_chat_in_pager = spy
        try:
            await pilot.press("f6")
            await pilot.pause()
        finally:
            BotinokTextualApp.action_open_chat_in_pager = original
        check("f6_dispatches", len(calls) == 1, f"calls={len(calls)}")

        app.append_user_message("привет")
        app._add_static("[bold green]Assistant:[/bold green]")
        app._add_static("[bold]🔧 tool_call[/bold]")          # служебное — выкинуть
        app._add_static("[dim]⏳ Загрузка сессии…[/dim]")     # плейсхолдер — выкинуть
        app.chat.mount(Markdown("финальный ответ ассистента"))
        await pilot.pause()
        text = app._chat_text()
        check("contains_user", "User: привет" in text, f"text={text!r}")
        check("contains_assistant_label", "Assistant:" in text, f"text={text!r}")
        check("contains_markdown_answer", "финальный ответ ассистента" in text, f"text={text!r}")
        check("markup_stripped", "[bold]" not in text, f"text={text!r}")
        check("no_tool_noise", "🔧" not in text, f"text={text!r}")
        check("no_placeholder", "Загрузка сессии" not in text, f"text={text!r}")

        # Пейджер получает Markdown, отрендеренный в ANSI (таблицы/цвет), а не сырой.
        app.chat.mount(Markdown("| a | b |\n|---|---|\n| 1 | 2 |"))
        await pilot.pause()
        ansi = app._chat_ansi()
        check("ansi_present", "\x1b[" in ansi, f"ansi_len={len(ansi)}")
        check("markdown_table_rendered", ("─" in ansi or "│" in ansi) and ("|---|---|" not in ansi),
              f"tail={ansi[-200:]!r}")
        check("ansi_has_dialog", ("User: привет" in ansi) and ("финальный ответ ассистента" in ansi))

        # Фоны сняты, а цвет/жирность остались.
        app.chat.mount(Markdown("`code` **bold**"))
        await pilot.pause()
        ansi2 = app._chat_ansi()
        import re as _re
        check("no_background_colors",
              _re.search(r"\x1b\[(4[0-9]|10[0-7]|48;)", ansi2) is None,
              f"len={len(ansi2)}")
        check("bold_foreground_kept",
              ("\x1b[1m" in ansi2) and ("\x1b[38;" in ansi2 or "\x1b[3" in ansi2))

    # Полная история из сессии: метки времени + Markdown-таблица.
    from core.session_manager import SessionManager  # noqa: E402

    sm = SessionManager()
    sess = sm.create_session("pager_hist")
    sm.update_context(sess, "user", "привет")
    sm.update_context(sess, "assistant", "**Ответ**\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    app2 = BotinokTextualApp(session_path=sess)
    app2.on_submit = lambda t: None
    async with app2.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        ansi = app2._chat_ansi()
        check("history_user", "User: привет" in ansi, f"ansi={ansi[:80]!r}")
        check("history_timestamp", "──" in ansi and ":" in ansi, f"ansi={ansi[:80]!r}")
        check("history_markdown_table", ("─" in ansi) and ("|---|---|" not in ansi))

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ CHAT PAGER SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
