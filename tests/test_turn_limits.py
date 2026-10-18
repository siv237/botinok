#!/usr/bin/env python3
"""Пределы хода НЕ стирают память: обнуление сессии на 80-м вызове инструментов.

Регрессия: при `tool_rounds > MAX_TOOL_ROUNDS_PER_TURN` харнес вызывал
`_ollama_summarize_and_reset_context(...)` → `messages.clear()` + SESSION_PROTOCOL,
то есть на 80-м вызове инструментов сессия обнулялась целиком, хотя контекст был
заполнен на проценты. То же делал детектор повторов.

Проверяется:
  * предел раундов настраивается ([Ollama] MaxToolRounds, 0 — без предела);
  * полная очистка памяти осталась ровно для одного случая — реального
    исчерпания контекста (HARD_CTX_PCT), и только там;
  * `messages.clear()` в модуле ровно один;
  * ветки «предел раундов» и «повтор» не вызывают очистку;
  * промпты-пометки существуют и подставляют предел.

Запуск: venv/bin/python -u tests/test_turn_limits.py
        venv/bin/python -m pytest tests/test_turn_limits.py -q
"""

import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import textual_integration as ti        # noqa: E402
from core.session_manager import SessionManager    # noqa: E402

FAILURES = []

TI_SOURCE = open(os.path.join(ROOT, "core", "textual_integration.py"), encoding="utf-8").read()
# Комментарии упоминают messages.clear() как историю — статические проверки
# должны смотреть на код, а не на текст комментариев.
TI_CODE = re.sub(r"(?m)^\s*#.*$", "", TI_SOURCE)


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeConfig:
    def __init__(self, value):
        self.value = value

    def getint(self, section, option, fallback=None):
        if self.value is None:
            return fallback
        return self.value


class FakeSM:
    def __init__(self, value):
        self.config = FakeConfig(value)


def main() -> int:
    print("\n[1] предел раундов настраивается")
    check("default_80", ti._max_tool_rounds(FakeSM(None)) == ti.MAX_TOOL_ROUNDS_PER_TURN)
    check("config_25", ti._max_tool_rounds(FakeSM(25)) == 25)
    check("config_zero_disables", ti._max_tool_rounds(FakeSM(0)) == 0)
    check("negative_becomes_zero", ti._max_tool_rounds(FakeSM(-5)) == 0)
    check("garbage_falls_back", ti._max_tool_rounds(FakeSM("мусор")) == ti.MAX_TOOL_ROUNDS_PER_TURN)

    print("\n[2] полная очистка осталась только для исчерпания контекста")
    calls = [m.start() for m in re.finditer(r"_ollama_summarize_and_reset_context\(", TI_CODE)]
    # первое вхождение — определение функции, дальше только вызовы
    reasons = re.findall(r"reason=f?[\"']([^\"']+)", TI_CODE)
    reset_reasons = [r for r in reasons if "hard_ctx_threshold" in r
                     or "max_tool_rounds" in r or "repetition" in r]
    check("only_ctx_reason_left",
          reset_reasons and all(r.startswith("hard_ctx_threshold_reached") for r in reset_reasons),
          str(reset_reasons))
    check("no_rounds_reset_reason", not any("max_tool_rounds_exceeded" in r for r in reasons),
          str([r for r in reasons if "max_tool_rounds" in r]))
    check("no_repetition_reset_reason", not any(r.startswith("repetition_detected") for r in reasons),
          str([r for r in reasons if r.startswith("repetition_detected")]))
    # считаем именно инструкцию (в докстроках/комментариях упоминания не в счёт)
    clears = [l for l in TI_CODE.splitlines() if l.strip() == "messages.clear()"]
    check("single_messages_clear", len(clears) == 1, f"найдено: {len(clears)}")

    print("\n[3] ветки лимитов завершают ход, а не стирают память")
    rounds_branch = re.search(r"if max_rounds and tool_rounds > max_rounds:(.*?)\n            if current_model",
                              TI_CODE, re.S)
    check("rounds_branch_found", rounds_branch is not None)
    if rounds_branch:
        body = rounds_branch.group(1)
        check("rounds_branch_no_reset", "_ollama_summarize_and_reset_context" not in body
              and "messages.clear()" not in body)
        check("rounds_branch_finalizes", "_finalize_turn(" in body and "break" in body)
        check("rounds_branch_note", "tool_rounds_limit" in body)
    rep_branch = re.search(r"if _detect_repetition\(full_response\):(.*?)\n            _flush_thinking_buf",
                           TI_CODE, re.S)
    check("repeat_branch_found", rep_branch is not None)
    if rep_branch:
        body = rep_branch.group(1)
        check("repeat_branch_no_reset", "_ollama_summarize_and_reset_context" not in body
              and "messages.clear()" not in body)
        check("repeat_branch_note", "repetition_notice" in body)

    print("\n[4] промпты-пометки")
    with tempfile.TemporaryDirectory() as sess:
        sm = SessionManager()
        text = sm.load_prompt(sess, "tool_rounds_limit", LIMIT="80")
        check("rounds_prompt_renders", "80" in text and "финальный ответ" in text, text[:120])
        rep = sm.load_prompt(sess, "repetition_notice")
        check("repeat_prompt_nonempty", bool(rep.strip()) and "Не повторяй" in rep, rep[:120])

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ ПРЕДЕЛЫ ХОДА ПАМЯТЬ НЕ СТИРАЮТ")
    return 0


def test_turn_limits() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
