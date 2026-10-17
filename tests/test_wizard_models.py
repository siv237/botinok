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
        ok, models, cert, base = w.check_openai("https://gw.test", "sk-1")
        check("успех с ключом", ok and cert is None)
        check("корень API — адрес как есть", base == "https://gw.test", str(base))
        ids = [m['id'] for m in models]
        check("список id", ids == ["example-model", "other-model"], str(ids))
        ctx = {m['id']: m.get('context') for m in models}
        check("контекст из max_input_tokens",
              ctx["example-model"] == 262144, str(ctx))
        check("без контекста — None", ctx["other-model"] is None)
        check("Bearer передан", served['headers'].get("Authorization") == "Bearer sk-1")

        ok2, models2, _, _ = w.check_openai("https://gw.test", "")
        check("без ключа — неуспех (401)", not ok2 and models2 == [])
    finally:
        cw.requests = real


def test_url_smarts():
    """Прощение ввода: схема, слэши, типовые точки входа и корень API."""
    n = ConfigWizard._normalize_url
    check("схема https для публичного хоста", n("api.fireworks.ai") == ("https://api.fireworks.ai", True))
    check("схема http для localhost", n("localhost:11434") == ("http://localhost:11434", True))
    check("схема http для частной сети", n("192.168.1.5:8080")[0] == "http://192.168.1.5:8080")
    check("схема уже есть — не трогаем", n("https://x.test/v1/") == ("https://x.test/v1", False))

    cands = ConfigWizard._candidate_model_urls("https://api.fireworks.ai")
    check("дописан провайдерский префикс /inference/v1/models",
          "https://api.fireworks.ai/inference/v1/models" in cands, str(cands[:4]))
    cands2 = ConfigWizard._candidate_model_urls("http://localhost:8080/v1")
    check("без дубля /v1", "http://localhost:8080/v1/models" in cands2
          and "http://localhost:8080/v1/v1/models" not in cands2)
    check("вставленный эндпоинт чата обрезан",
          "https://x.test/v1/models" in
          ConfigWizard._candidate_model_urls("https://x.test/v1/chat/completions"))

    b = ConfigWizard._api_base_from_models_url
    check("корень с /inference", b("https://api.fireworks.ai/inference/v1/models")
          == "https://api.fireworks.ai/inference")
    check("корень без /v1", b("http://localhost:8080/v1/models") == "http://localhost:8080")
    check("корень из /models", b("http://host/models") == "http://host")


def test_discover_endpoints():
    """Авто-корректор находит точку входа за провайдерским префиксом."""
    class R:
        @staticmethod
        def get(url, timeout=None, verify=True, headers=None):
            if url.endswith("/props"):
                raise requests.exceptions.ConnectionError("no props")
            if url == "https://fw.test/inference/v1/models":
                return FakeResp(200, {"data": [{"id": "m", "context_length": 1000}]})
            return FakeResp(404, {})

    real = cw.requests
    cw.requests = R
    w = object.__new__(ConfigWizard)
    try:
        found = w.discover_model_endpoints("fw.test", "k")
        bases = [b for b, _ in found]
        check("автопоиск нашёл /inference",
              "https://fw.test/inference" in bases, str(bases))
        got = next((m for b, m in found if b == "https://fw.test/inference"), [])
        check("модель получена", [x['id'] for x in got] == ["m"])
        check("контекст провайдера", got[0]['context'] == 1000)
    finally:
        cw.requests = real


def main() -> int:
    print("=" * 60)
    print("wizard models/context tests")
    print("=" * 60)
    test_model_context()
    test_check_openai()
    test_url_smarts()
    test_discover_endpoints()
    print("-" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
