#!/usr/bin/env python3
"""
Тест добивки обрыва по finish_reason=length (этап 7 плана
wiki/concepts/context_memory_research.md):
  * openai_compat пробрасывает done_reason ("length") в финальный чанк;
  * _stitch_response склеивает части, убирая перекрытие и дубль строки на шве.

Запуск: venv/bin/python -u tests/test_length_stitch.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.openai_compat import OpenAIStreamResponse  # noqa: E402
from core.textual_integration import _stitch_response  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeResp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)


def sse(obj):
    return ("data: " + json.dumps(obj) + "\n\n").encode("utf-8")


def main() -> int:
    # 1) done_reason из finish_reason
    lines = [
        sse({"choices": [{"delta": {"content": "начало"}, "index": 0}]}),
        sse({"choices": [{"delta": {}, "index": 0, "finish_reason": "length"}]}),
        sse({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}),
        b"data: [DONE]\n\n",
    ]
    out = [json.loads(l.decode("utf-8")) for l in OpenAIStreamResponse(FakeResp(lines)).iter_lines()]
    final = out[-1]
    check("done_reason_length", final.get("done") and final.get("done_reason") == "length", str(final)[:150])
    check("usage_mapped", final.get("prompt_eval_count") == 10 and final.get("eval_count") == 5)

    lines2 = [
        sse({"choices": [{"delta": {"content": "x"}, "index": 0, "finish_reason": "stop"}]}),
        b"data: [DONE]\n\n",
    ]
    out2 = [json.loads(l.decode("utf-8")) for l in OpenAIStreamResponse(FakeResp(lines2)).iter_lines()]
    check("done_reason_stop", out2[-1].get("done_reason") == "stop", str(out2[-1])[:150])

    # 2) сшивка: чистое продолжение
    check("stitch_plain", _stitch_response(["Раз, два.", " Три."]) == "Раз, два. Три.")

    # 3) сшивка: перекрытие слов на шве (модель повторила хвост)
    merged = _stitch_response(["Длинный текст про погоду в горо", "про погоду в городе X."])
    check("stitch_overlap_removed", merged == "Длинный текст про погоду в городе X.", merged)

    # 4) сшивка: дублирующая строка на шве
    merged2 = _stitch_response(["строка одна\nстрока две\n", "строка две\nстрока три\n"])
    check("stitch_dup_line_removed", merged2.count("строка две") == 1, repr(merged2))

    # 5) пустые части и одиночная часть
    check("stitch_single", _stitch_response(["только одно"]) == "только одно")
    check("stitch_empties", _stitch_response(["", "a", "", "b"]) == "ab")
    check("stitch_three_parts", _stitch_response(["aa bb", "bb cc", "cc dd"]) == "aa bb cc dd")

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ LENGTH STITCH ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
