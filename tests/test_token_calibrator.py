#!/usr/bin/env python3
"""
Smoke-тест core/token_calibrator: каскад ключей, робастная медиана, дрейф,
персистентность, фильтр выбросов и проброс reasoning_tokens в openai_compat.

Запуск: venv/bin/python -u tests/test_token_calibrator.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import token_calibrator as tc  # noqa: E402
from core.openai_compat import OpenAIStreamResponse  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _fresh_store():
    tc.reset_for_tests()
    path = os.path.join(tempfile.mkdtemp(), "token_calib.json")
    tc.init(path)
    return path


def test_prior_and_cascade():
    _fresh_store()
    dep = tc.deploy_fingerprint("m1", "srv")
    tok, status, n = tc.estimate(dep, "completion", "plain", 1000)
    check("prior_before_data", status == "prior" and n == 0, f"{status} n={n}")

    # 25 замеров: лист (n<30) ещё не готов, родительский агрегат (n>=20) — да.
    for _ in range(25):
        tc.record_api_call(dep, "plain", {}, 0, response_chars=100, completion_tokens=30)
    tok, status, n = tc.estimate(dep, "completion", "plain", 1000)
    check("parent_cascade", status == "calibrated" and abs(tok - 300) <= 20,
          f"{status} n={n} tok={tok}")
    check("ready_true", tc.ready(dep, "completion", "plain"))

    # Робастность: 5 жирных выбросов не сдвигают медиану.
    for _ in range(5):
        tc.record_api_call(dep, "plain", {}, 0, response_chars=100, completion_tokens=1000)
    tok, status, _ = tc.estimate(dep, "completion", "plain", 1000)
    check("median_robust_to_outliers", abs(tok - 300) <= 40, f"tok={tok}")


def test_prompt_channel_and_range_filter():
    _fresh_store()
    dep = tc.deploy_fingerprint("m2", "srv")
    for _ in range(30):
        tc.record_api_call(dep, "tool_round", {"user": 200, "tool": 300}, 250)
    tok, status, n = tc.estimate(dep, "prompt", "tool_round", 1000)
    check("prompt_channel", status == "calibrated" and abs(tok - 500) <= 40,
          f"{status} n={n} tok={tok}")
    #physically impossible ratio must be dropped
    tc.record_api_call(dep, "plain", {"user": 1_000_000}, 1)
    st = tc.get_stats()
    check("range_filter", all(v["n"] <= 30 for v in st.values()),
          json.dumps(st))


def test_drift():
    _fresh_store()
    dep = tc.deploy_fingerprint("m3", "srv")
    for _ in range(30):
        tc.record_api_call(dep, "plain", {}, 0, response_chars=200, completion_tokens=100)
    check("stable_before_drift", tc.ready(dep, "completion", "plain"))
    for _ in range(30):
        tc.record_api_call(dep, "plain", {}, 0, response_chars=100, completion_tokens=100)
    st = tc.get_stats()
    leaf = st.get(f"{dep}|completion|plain") or {}
    check("drift_flag", bool(leaf.get("drift")), json.dumps(st))
    check("drift_not_ready", not tc.ready(dep, "completion", "plain"))


def test_persistence():
    path = _fresh_store()
    dep = tc.deploy_fingerprint("m4", "srv")
    for _ in range(30):
        tc.record_api_call(dep, "plain", {}, 0, response_chars=100, completion_tokens=40)
    tc.flush()
    check("file_written", os.path.exists(path))
    tc.reset_for_tests()
    tc.init(path)
    tok, status, n = tc.estimate(dep, "completion", "plain", 1000)
    check("reload_keeps_state", status == "calibrated" and n == 30 and abs(tok - 400) <= 20,
          f"{status} n={n} tok={tok}")


def test_answer_direction():
    _fresh_store()
    dep = tc.deploy_fingerprint("m5", "srv")
    # 160 completion − 100 reasoning = 60 токенов чистого ответа на 100 символов.
    for _ in range(30):
        tc.record_api_call(dep, "plain", {}, 0, response_chars=100,
                           thinking_chars=200, completion_tokens=160,
                           reasoning_tokens=100)
    tok, status, n = tc.estimate(dep, "answer", "plain", 1000)
    check("answer_channel", status == "calibrated" and abs(tok - 600) <= 40,
          f"{status} n={n} tok={tok}")
    # completion-агрегат считает по всем символам: (160)/(300) ≈ 0.53 → ~533.
    tok_c, status_c, _ = tc.estimate(dep, "completion", "plain", 1000)
    check("completion_mixed", status_c == "calibrated" and abs(tok_c - 533) <= 40,
          f"{status_c} tok={tok_c}")


def test_sse_reasoning_passthrough():
    class FakeResp:
        status_code = 200

        def __init__(self, lines):
            self._lines = lines

        def iter_lines(self):
            return iter(self._lines)

        def close(self):
            pass

    lines = [
        b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}',
        b'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":5,'
        b'"completion_tokens_details":{"reasoning_tokens":3}}}',
        b'data: [DONE]',
    ]
    chunks = [json.loads(c.decode("utf-8"))
              for c in OpenAIStreamResponse(FakeResp(lines)).iter_lines()]
    final = chunks[-1]
    check("sse_final_usage", final.get("prompt_eval_count") == 11
          and final.get("eval_count") == 5, json.dumps(final))
    check("sse_reasoning_tokens", final.get("reasoning_tokens") == 3, json.dumps(final))


def main():
    for fn in (test_prior_and_cascade, test_prompt_channel_and_range_filter,
               test_drift, test_persistence, test_answer_direction,
               test_sse_reasoning_passthrough):
        print(f"== {fn.__name__}")
        fn()
    print("\n" + ("ВСЕ ТЕСТЫ ПРОЙДЕНЫ" if not FAILURES else f"ПРОВАЛ: {FAILURES}"))
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
