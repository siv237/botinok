#!/usr/bin/env python3
"""
Smoke-тест устойчивости агента к сбоям API:
- классификация временных HTTP-кодов (держим сессию, а не падаем);
- разбор текста ошибки из разных форматов ответа;
- подпись реального сервера (не всегда «Ollama»).

Запуск: venv/bin/python -u tests/test_api_resilience.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.textual_integration as ti  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("API resilience smoke-test")
    print("=" * 70)

    # Временные коды: их надо пережидать, а не сдаваться.
    for code in (408, 425, 429, 500, 502, 503, 504):
        check(f"transient_{code}", ti._is_transient_http(code))
    # Постоянные клиентские ошибки — не временные.
    for code in (400, 401, 403, 404, 422):
        check(f"permanent_{code}", not ti._is_transient_http(code))

    # Пережидаемые (лечатся повтором): транзиентные + проблемы ключа/лимита
    # (401/403), но не клиентские вроде 400/404/422.
    for code in (408, 429, 500, 502, 503, 504, 401, 403):
        check(f"retryable_{code}", ti._is_retryable_http(code))
    for code in (400, 404, 422):
        check(f"not_retryable_{code}", not ti._is_retryable_http(code))

    # Форматированный блок ошибки для чата и истории.
    block = ti._format_api_error(403, "Недоступно", '{"error":"x"}', "api.example.ai")
    check("fmt_status", "HTTP 403" in block and "api.example.ai" in block, block)
    check("fmt_message", "Недоступно" in block, block)
    check("fmt_body", '{"error":"x"}' in block, block)
    check("fmt_no_dupe_body",
          ti._format_api_error(500, "boom", "boom") ==
          "⚠ Ошибка API: HTTP 500\nboom")

    # Разбор текста ошибки в разных форматах.
    check("err_flat", ti._extract_api_error({"error": "model not found"}) == "model not found")
    check("err_nested", ti._extract_api_error(
        {"error": {"message": "Loading model", "type": "unavailable_error"}}) == "Loading model")
    check("err_detail", ti._extract_api_error({"detail": "bad request"}) == "bad request")
    check("err_unknown", ti._extract_api_error({}) == "Неизвестная ошибка сервера")

    # Подпись сервера: имя реального бэкенда.
    class _Cfg:
        def get(self, *a, **k):
            return "https://api.example.ai"

    class _SM:
        config = _Cfg()

    label = ti._server_label(_SM())
    check("server_label", "api.example.ai" in label, label)

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        return 1
    print("✅ API RESILIENCE SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
