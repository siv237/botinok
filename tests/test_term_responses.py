#!/usr/bin/env python3
"""Ответы терминала на запросы не должны попадать в поле ввода.

При открытии TUI в Composer сыпался мусор вида
`^]10;rgb:0707/3636/4242^\\^]11;rgb:...^\\^[8;24;80t^[4;456;720t[?61;1;21;22;28c` —
это ответы на OSC 10/11, CSI 18t/14t и DA1. Textual 8.x их не распознаёт и
переиздаёт посимвольно как клавиши. Парсер обязан вырезать их целиком,
не трогая DECRPM, позицию курсора и обычные клавиши.

Запуск: venv/bin/python -u tests/test_term_responses.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual import events  # noqa: E402
from textual import messages  # noqa: E402

from core.terminal_keys import BotinokXTermParser  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def parse(data: str):
    parser = BotinokXTermParser()
    evs = list(parser.feed(data))
    time.sleep(0.16)
    evs += list(parser.tick())
    return evs


def keys_of(evs):
    return [e.key for e in evs if isinstance(e, events.Key)]


GARBAGE = ("\x1b]10;rgb:0707/3636/4242\x1b\\"
           "\x1b]11;rgb:fdfd/f6f6/e3e3\x1b\\"
           "\x1b[8;24;80t"
           "\x1b[4;456;720t"
           "\x1b[?61;1;21;22;28c")


def main() -> int:
    print("=" * 70)
    print("Terminal query responses filter")
    print("=" * 70)

    evs = parse(GARBAGE)
    check("garbage_dropped", evs == [], f"events={evs!r}")

    evs = parse("\x1b]10;rgb:0707/3636/4242\x07\x1b[?1;2c\x1b[6;40;80t")
    check("bel_and_da_variants_dropped", evs == [], f"events={evs!r}")

    # Обрывок ответа: пришёл двумя пакетами — склеивается и вырезается.
    parser = BotinokXTermParser()
    evs = list(parser.feed("\x1b]10;rgb:0707/"))
    time.sleep(0.05)
    evs += list(parser.feed("3636/4242\x1b\\"))
    time.sleep(0.16)
    evs += list(parser.tick())
    check("split_response_dropped", evs == [], f"events={evs!r}")

    # Обычные клавиши проходят как раньше.
    check("plain_text", keys_of(parse("hi")) == ["h", "i"])
    check("arrow_up", keys_of(parse("\x1b[A")) == ["up"])
    check("alt_enter_regression", keys_of(parse("\x1b\r")) == ["alt+enter"])
    check("escape_alone", keys_of(parse("\x1b")) == ["escape"])

    # Последовательности, которые парсер обрабатывает сам, не вырезаем.
    evs = parse("\x1b[?2026;1$y")
    check("decrpm_passthrough",
          any(isinstance(e, messages.TerminalSupportsSynchronizedOutput) for e in evs),
          f"events={evs!r}")
    evs = parse("\x1b[5;3R")
    check("cursor_position_passthrough",
          any(isinstance(e, events.CursorPosition) for e in evs),
          f"events={evs!r}")

    # Мусор вокруг обычного ввода: клавиши не теряются.
    check("keys_between_garbage",
          keys_of(parse("a" + GARBAGE + "b")) == ["a", "b"])

    # Просроченный обрывок не должен бесконечно удерживать следующий ввод.
    parser = BotinokXTermParser()
    list(parser.feed("\x1b[1"))
    parser._held_at = time.time() - 10
    evs = list(parser.feed("x"))
    check("expired_tail_not_merged", "x" in keys_of(evs), f"events={evs!r}")

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        return 1
    print("✅ TERM RESPONSES FILTER SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
