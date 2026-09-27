#!/usr/bin/env python3
"""
Тесты core/config_wizard: проверка SSL-сертификата и согласие игнорировать.

Без сети: `requests.get` подменяется так, что при `verify=True` бросается
`requests.exceptions.SSLError` (самоподписанный сертификат), а при
`verify=False` приходит валидный ответ. Текстовые диалоги скриптуются.

Запуск: venv/bin/python -u tests/test_wizard_ssl.py
"""

import configparser
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

import core.config_wizard as cw  # noqa: E402
from core.config_wizard import ConfigWizard  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


def make_wizard():
    w = object.__new__(ConfigWizard)
    cfg = configparser.ConfigParser()
    cfg.add_section('Ollama')
    cfg.set('Ollama', 'BaseUrl', 'https://self-signed.local:11434')
    cfg.set('Ollama', 'VerifySSL', 'true')
    w.config = cfg
    return w


def scripted(confirm_answers, prompt_answers):
    """Возвращает (подменённые confirm/prompt) с очередью ответов."""
    conf = list(confirm_answers)
    prom = list(prompt_answers)

    def _confirm(message, default=True):
        return conf.pop(0) if conf else None

    def _prompt(message, default="", password=False):
        return prom.pop(0) if prom else None

    return _confirm, _prompt


def run_case(name, fn):
    print(f"[{name}]")
    orig_get = requests.get
    orig_confirm = cw.textual_confirm
    orig_prompt = cw.textual_prompt
    try:
        fn()
    except Exception as e:
        check(name + " без исключений", False, f"{type(e).__name__}: {e}")
    finally:
        requests.get = orig_get
        cw.textual_confirm = orig_confirm
        cw.textual_prompt = orig_prompt


def install_ssl_stub(seen_verify):
    def fake_get(url, timeout=None, verify=True, headers=None):
        seen_verify.append((url, verify))
        if verify and str(url).startswith("https://"):
            raise requests.exceptions.SSLError("certificate verify failed: self-signed")
        payload = {"models": [{"name": "m1"}], "data": [{"id": "m1"}]}
        return FakeResponse(payload)
    requests.get = fake_get


def case_check_functions():
    w = make_wizard()
    seen = []
    install_ssl_stub(seen)
    ok, models, cert_error = w.check_ollama("https://self-signed.local:11434", verify=True)
    check("check_ollama: провал с cert_error", not ok and bool(cert_error) and not models)
    ok, models, cert_error = w.check_ollama("https://self-signed.local:11434", verify=False)
    check("check_ollama: успех без проверки", ok and models and cert_error is None)

    seen.clear()
    install_ssl_stub(seen)
    ok, models, cert_error = w.check_openai("https://self-signed.local:11434", "k", verify=True)
    check("check_openai: провал с cert_error", not ok and bool(cert_error))
    ok, models, cert_error = w.check_openai("https://self-signed.local:11434", "k", verify=False)
    check("check_openai: успех без проверки", ok and models and cert_error is None)
    check("_is_https", w._is_https("HTTPS://x") and not w._is_https("http://x"))
    check("_cert_error: не SSL", w._cert_error(Exception("Connection refused")) is None)


def case_consent_ignore_ollama():
    w = make_wizard()
    install_ssl_stub([])
    cw.textual_confirm, cw.textual_prompt = scripted([True, True], [])
    result = w._configure_ollama()
    check("ollama: согласие игнорировать → работа", result is not None)
    check("ollama: VerifySSL=false записан",
          w.config.get('Ollama', 'VerifySSL') == 'false')
    check("ollama: BaseUrl сохранён",
          w.config.get('Ollama', 'BaseUrl') == 'https://self-signed.local:11434')


def case_refuse_then_http_ollama():
    w = make_wizard()
    install_ssl_stub([])
    cw.textual_confirm, cw.textual_prompt = scripted([False, True], ['http://localhost:11434'])
    result = w._configure_ollama()
    check("ollama: отказ → другой URL", result is not None)
    check("ollama: VerifySSL=true остаётся",
          w.config.get('Ollama', 'VerifySSL') == 'true')
    check("ollama: сохранён новый URL",
          w.config.get('Ollama', 'BaseUrl') == 'http://localhost:11434')


def case_consent_ignore_openai():
    w = make_wizard()
    install_ssl_stub([])
    cw.textual_confirm, cw.textual_prompt = scripted([True, True], ['', ''])
    result = w._configure_openai()
    check("openai: согласие игнорировать → работа", result is not None)
    check("openai: VerifySSL=false записан",
          w.config.get('Ollama', 'VerifySSL') == 'false')


def main():
    run_case("check_functions", case_check_functions)
    run_case("consent_ignore_ollama", case_consent_ignore_ollama)
    run_case("refuse_then_http_ollama", case_refuse_then_http_ollama)
    run_case("consent_ignore_openai", case_consent_ignore_openai)
    if FAILURES:
        print(f"\nПровалено: {len(FAILURES)} — {FAILURES}")
        return 1
    print("\nВсе проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
