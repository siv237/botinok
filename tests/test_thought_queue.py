#!/usr/bin/env python3
"""
Smoke-тест очереди «мыслей»: висят внизу с крестиком, отменяются до отправки,
уходят в поток одним блоком, Esc возвращает их в строку ввода.

Запуск: venv/bin/python -u tests/test_thought_queue.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.textual_app import BotinokTextualApp  # noqa: E402
import core.textual_integration as ti  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def test_call_ui_result() -> None:
    """call_from_thread возвращает результат напрямую — без .result() и повторного
    вызова (иначе очередь мыслей забиралась дважды и терялась)."""
    calls = []

    def fn():
        calls.append(1)
        return "T"

    class FakeApp:
        def call_from_thread(self, f, *a, **k):
            return f(*a, **k)

    res = ti._call_ui_result(FakeApp(), fn)
    check("ui_result_value", res == "T", repr(res))
    check("ui_result_called_once", calls == [1], f"calls={len(calls)}")


async def main() -> int:
    print("=" * 70)
    print("Thought queue smoke-test")
    print("=" * 70)

    test_call_ui_result()

    app = BotinokTextualApp()
    async with app.run_test(size=(140, 45)) as pilot:  # noqa: F841
        app.is_streaming = True

        # Добавляем две мысли — панель видна, чипы с крестиками есть.
        app._queued_inputs.append("мысль первая")
        app._queued_inputs.append("мысль вторая")
        app._render_thought_queue()
        app._update_queue_placeholder()
        await asyncio.sleep(0.1)

        from textual.containers import Vertical
        from textual.widgets import Button
        q = app.query_one("#thought_queue", Vertical)
        check("queue_visible", q.has_class("-visible"))
        buttons = list(q.query(Button))
        check("queue_two_chips", len(buttons) == 2, f"buttons={len(buttons)}")

        # Отмена одной мысли крестиком (до отправки).
        app._remove_queued(0)
        await asyncio.sleep(0.05)
        check("cancel_one", app._queued_inputs == ["мысль вторая"], f"{app._queued_inputs}")

        # Доставка: все накопленные мысли уходят ОДНИМ блоком и очередь пустеет.
        app._queued_inputs.append("мысль третья")
        app._render_thought_queue()
        block = app.take_queued_thoughts()
        await asyncio.sleep(0.05)
        check("batch_single_block", block == "мысль вторая\n\nмысль третья", repr(block))
        check("queue_cleared", app._queued_inputs == [])
        check("panel_hidden_after_take", not app.query_one("#thought_queue", Vertical).has_class("-visible"))

        # Повторный забор не отдаёт то же дважды.
        check("take_twice_empty", app.take_queued_thoughts() == "")

        # Доставленная мысль: видна в чате как сообщение пользователя и отмечена
        # в панели промтов как «мысль» (с меткой времени отправки).
        app._queued_inputs.append("мысль доставлена")
        block = app.take_queued_thoughts()
        before = len(app.chat.children)
        app.deliver_thought_block(block)
        await asyncio.sleep(0.1)
        check("thought_visible_in_chat", len(app.chat.children) > before,
              f"before={before} after={len(app.chat.children)}")
        kinds = [e.get("kind") for e in app.diag_entries]
        check("thought_in_diag", bool(kinds) and kinds[-1] == "thought", f"{kinds[-3:]}")
        check("thought_has_time", isinstance(app.diag_entries[-1].get("ts"), float))
        prefix, body = app._diag_row_parts(app.diag_entries[-1])
        check("thought_title_marked", "💭" in prefix and "ысль" in prefix, prefix)
        check("thought_label_body", "мысль доставлена" in body, body)

        # Шапка окна не переносится.
        import re as _re
        from core.text_width import cell_width

        def _plain(s: str) -> str:
            return _re.sub(r"\[/?[^\]]*\]", "", s)

        dw = app.diag.size.width or 0
        app._update_diag()
        head_plain = _plain(app.diag.title)
        check("header_fits", dw == 0 or cell_width(head_plain) <= dw,
              f"w={dw} head={cell_width(head_plain)} {head_plain!r}")

        # Длинный текст НЕ обрезается: он лежит в отдельной колонке и переносится
        # самим Textual (висячий отступ обеспечивает раскладка, а не ручной счёт).
        long_text = ("послушай давай остановись прочти и ничего не делай не продолжай "
                     "а обсудим как готов будешь ") * 2
        app._record_diag(long_text, kind="thought")
        app._update_diag()
        await asyncio.sleep(0.1)
        lp, lb = app._diag_row_parts(app.diag_entries[-1])
        check("long_text_full", long_text.strip() in _plain(lb),
              f"len={len(_plain(lb))} want={len(long_text.strip())}")
        thought_key = app.diag_entries[-1].get("key")
        refs = app._diag_widgets.get(thought_key)
        check("thought_card_created", refs is not None, f"keys={list(app._diag_widgets)[-3:]}")
        check("thought_row_two_columns",
              refs is not None and len(refs) == 3 and refs[1].has_class("diag_prefix")
              and refs[2].has_class("diag_text"),
              "ожидается (row, prefix, text)")

        # Обычный запрос: метка «📝 Запрос»; строки идут свежими СВЕРХУ.
        app._record_diag("обычный запрос")
        app._update_diag()
        await asyncio.sleep(0.1)
        pp, _ = app._diag_row_parts(app.diag_entries[-1])
        check("prompt_label", "📝 Запрос" in pp, pp)
        rows = list(app.diag_list.children)
        newest_id = app._diag_id(app.diag_entries[-1]["key"])
        check("diag_newest_first", bool(rows) and rows[0].id == newest_id,
              f"first={rows[0].id if rows else None} want={newest_id}")

        # Esc: очередь мыслей возвращается в строку ввода одним блоком.
        app._queued_inputs.append("мысль A")
        app._queued_inputs.append("мысль B")
        app._render_thought_queue()
        app._stop_requested = True
        app.flush_tool_buffer()
        await asyncio.sleep(0.1)
        check("esc_returns_block",
              app.input_widget.text == "мысль A\n\nмысль B", repr(app.input_widget.text))
        check("esc_queue_empty", app._queued_inputs == [])

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ THOUGHT QUEUE SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
