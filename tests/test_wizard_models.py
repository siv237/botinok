#!/usr/bin/env python3
"""
Тесты core/config_wizard: распознавание контекста модели у разных
провайдеров (в т.ч. LiteLLM с max_input_tokens) и check_openai с ключом.

Запуск: venv/bin/python -u tests/test_wizard_models.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

import core.config_wizard as cw  # noqa: E402
from core.config_wizard import ConfigWizard  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


def test_model_context():
    mc = ConfigWizard._model_context
    check("ollama context_length", mc({"context_length": 262144}) == 262144)
    check("llama.cpp n_ctx в meta.llama",
          mc({"meta": {"llama": {"n_ctx": 8192}}}) == 8192)
    check("vLLM max_model_len", mc({"max_model_len": 32768}) == 32768)
    check("LiteLLM max_input_tokens",
          mc({"id": "example-model", "max_input_tokens": 262144}) == 262144)
    check("llama-server max_total_tokens",
          mc({"max_total_tokens": 4096}) == 4096)
    check("нет контекста — None", mc({"id": "x"}) is None)
    check("не dict — None", mc("junk") is None)


class FakeResp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload

    def json(self):
        return self._p


def test_check_openai(monkey=getattr(cw, "requests", requests)):
    """check_openai: /v1/models с Bearer, парсинг id+context, 401 без ключа."""
    served = {}

    class R:
        @staticmethod
        def get(url, timeout=None, verify=True, headers=None):
            served['headers'] = headers
            if url.endswith("/props"):
                raise requests.exceptions.ConnectionError("no props")
            if url == "https://gw.test/v1/models":
                auth = (headers or {}).get("Authorization", "")
                if auth != "Bearer sk-1":
                    return FakeResp(401, {"error": "No api key"})
                return FakeResp(200, {"data": [
                    {"id": "example-model", "max_input_tokens": 262144},
                    {"id": "other-model"},
                ]})
            return FakeResp(404, {})

    real = cw.requests
    cw.requests = R
    w = object.__new__(ConfigWizard)
    try:
        ok, models, cert = w.check_openai("https://gw.test", "sk-1")
        check("успех с ключом", ok and cert is None)
        ids = [m['id'] for m in models]
        check("список id", ids == ["example-model", "other-model"], str(ids))
        ctx = {m['id']: m.get('context') for m in models}
        check("контекст из max_input_tokens",
              ctx["example-model"] == 262144, str(ctx))
        check("без контекста — None", ctx["other-model"] is None)
        check("Bearer передан", served['headers'].get("Authorization") == "Bearer sk-1")

        ok2, models2, _ = w.check_openai("https://gw.test", "")
        check("без ключа — неуспех (401)", not ok2 and models2 == [])
    finally:
        cw.requests = real


def main() -> int:
    print("=" * 60)
    print("wizard models/context tests")
    print("=" * 60)
    test_model_context()
    test_check_openai()
    print("-" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
