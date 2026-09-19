#!/usr/bin/env python3
"""
Главный тест загрузки клиента: TUI обязан стартовать даже на «ядовитой» истории,
где в промптах, аргументах инструментов, результатах и панелях есть квадратные
скобки (Rich-markup роняет Collapsible/Static без экранирования).

Если приложение не поднялось — тест падает, независимо от причины.

Запуск: venv/bin/python -u tests/test_startup_client.py
"""

import asyncio
import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session_manager import SessionManager  # noqa: E402
from core.textual_app import BotinokTextualApp  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _poison_session() -> str:
    sm = SessionManager()
    session = sm.create_session("startup-markup")
    # Промпт с '['
    sm.update_context(session, "user", "вопрос [со скобками] и массив [1,2,3]")
    # Аргументы инструмента с JSON-массивом (edits: [{...]) — именно это роняло старт
    tool_calls = [{
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "code_editor",
            "arguments": {
                "action": "apply",
                "edits": [{"new_text": 'BONSAI_EXTRA_ARGS=\\"\\"', "old_text": "a[b]"}],
                "path": "/tmp/x[1]",
            },
        },
    }]
    sm.update_context(session, "assistant", "сейчас поправлю", tool_calls=tool_calls)
    sm.update_context(session, "tool", "TOOL_RESULT_SUMMARY\n[вывод] [1,2,3]",
                      tool_call_id="call_1", name="code_editor")
    sm.update_context(session, "assistant", "готово [ok]")
    # Мысль, ушедшая в поток (с пометкой) — после перезапуска должна
    # восстановиться как «мысль», а не как обычный запрос.
    sm.update_context(session, "user", "(во время работы)\nмысль из истории [x]")
    sm.update_context(session, "assistant", "учёл")
    return session


async def main() -> int:
    print("=" * 70)
    print("STARTUP CLIENT smoke-test (жёсткая проверка загрузки)")
    print("=" * 70)

    tmp = tempfile.mkdtemp(prefix="botinok_startup_")
    os.environ["BOTINOK_SESSIONS_DIR"] = tmp
    session = _poison_session()

    started = False
    try:
        app = BotinokTextualApp(session_path=session, version="test")
        async with app.run_test(size=(140, 45)) as pilot:  # noqa: F841
            # Сюда попадаем только если on_mount/load_history отработали без краша.
            started = True
            check("client_started", True)
            await asyncio.sleep(0.3)
            check("history_rendered", len(app.chat.children) > 0,
                  f"children={len(app.chat.children)}")
            check("composer_present", app.input_widget is not None)

            # Панель диагностики с '['
            app._record_diag("промпт [со скобками]")
            app._update_diag()
            await asyncio.sleep(0.15)
            check("diag_brackets_ok", True)

            # Мысль из истории восстановлена как «мысль» (после перезапуска).
            thoughts = [e for e in app.diag_entries if e.get("kind") == "thought"]
            check("history_thought_restored", bool(thoughts)
                  and any("мысль из истории" in e["text"] for e in thoughts),
                  f"kinds={[e.get('kind') for e in app.diag_entries][-3:]}")
            check("history_thought_no_marker",
                  all("(во время работы)" not in e["text"] for e in thoughts))

            # Раскрытый список запросов НЕ должен съедать чат: история остаётся видна.
            app.diag.collapsed = False
            await asyncio.sleep(0.4)
            check("chat_visible_with_diag", app.chat.size.height > 0,
                  f"chat_h={app.chat.size.height} diag_h={app.diag.size.height}")

            # Записи не теряются: храним полный текст и позицию в истории
            # (задел под клик «перейти/откатиться»).
            check("diag_keeps_index",
                  any(e.get("index") is not None for e in app.diag_entries),
                  f"n={len(app.diag_entries)}")
            check("diag_keeps_full_text",
                  any(len(e["text"]) >= 10 for e in app.diag_entries))

            # Панель инструментов с '[' в запросе/результате
            app.active_tools.append({
                "name": "shell_exec", "status": "completed",
                "query": "echo [x]", "result": "[out] [1,2]",
                "size_kb": 1.0, "start_time": time.time(),
            })
            app._update_tools_panel()
            await asyncio.sleep(0.15)
            check("tools_brackets_ok", True)
    except Exception as e:
        check("client_started", False, f"{type(e).__name__}: {e}")
        print("\n--- traceback ---")
        traceback.print_exc()
        print("--- /traceback ---\n")

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ CLIENT STARTUP SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
