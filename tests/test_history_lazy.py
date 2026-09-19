#!/usr/bin/env python3
"""
Тест ленивой загрузки истории на длинной сессии:
- при старте рисуется только хвост (не тысячи виджетов);
- есть кнопка «Показать более раннее» и догрузка работает;
- спойлеры из истории СВЁРНУТЫ;
- индикатор загрузки убирается.

Запуск: venv/bin/python -u tests/test_history_lazy.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session_manager import SessionManager  # noqa: E402
from core.textual_app import BotinokTextualApp  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _long_session(n: int = 600) -> str:
    sm = SessionManager()
    session = sm.create_session("lazy-history")
    for i in range(n):
        sm.update_context(session, "user", f"вопрос номер {i} — проверка [x]")
        thinking = f"размышление по вопросу {i} " * 5
        tool_calls = [{
            "id": f"call_{i}", "type": "function",
            "function": {"name": "file_system",
                         "arguments": {"action": "list", "path": f"/tmp/{i}"}},
        }]
        sm.update_context(session, "assistant", f"ответ {i}", thinking=thinking,
                          tool_calls=tool_calls)
        sm.update_context(session, "tool", f"TOOL_RESULT_SUMMARY\nрезультат {i} [y]",
                          tool_call_id=f"call_{i}", name="file_system")
    return session


async def main() -> int:
    print("=" * 70)
    print("Lazy history smoke-test")
    print("=" * 70)

    os.environ["BOTINOK_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="botinok_lazy_")
    session = _long_session(600)

    app = BotinokTextualApp(session_path=session)
    async with app.run_test(size=(140, 45)) as pilot:  # noqa: F841
        await asyncio.sleep(1.2)

        total = len(app._history_all)
        check("history_loaded", total >= 600, f"total={total}")
        check("initial_not_full", app._history_from > 0,
              f"history_from={app._history_from} total={total}")
        # Хвост ограничен (примерно 200 записей), а не вся история.
        check("initial_children_limited", len(app.chat.children) < 900,
              f"children={len(app.chat.children)}")
        check("load_older_button", app._load_older_button is not None)
        check("loading_indicator_removed", app._loading_widget is None)

        from textual.widgets import Collapsible
        cols = list(app.query(Collapsible))
        check("spoilers_present", len(cols) > 0, f"n={len(cols)}")
        check("spoilers_collapsed", all(c.collapsed for c in cols),
              f"opened={sum(1 for c in cols if not c.collapsed)}")

        before_from = app._history_from
        before_children = len(app.chat.children)
        app._load_older_history()
        await asyncio.sleep(0.8)
        check("load_older_decreases", app._history_from < before_from,
              f"{before_from} -> {app._history_from}")
        check("load_older_adds_widgets", len(app.chat.children) > before_children,
              f"{before_children} -> {len(app.chat.children)}")

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ LAZY HISTORY SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
