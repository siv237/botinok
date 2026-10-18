#!/usr/bin/env python3
"""Маскирование секретов в аудит-логе вызовов инструментов (tools.log).

Повод: в живой сессии в `tools.log` лежал токен HuggingFace открытым текстом —
агент передавал его заголовком `Authorization: Bearer hf_…`, а лог писал
аргументы дословно (и их же читает `session_memory`).

Проверяется: токены в заголовках/URL/dict-полях маскируются, обычные данные не
портятся, а сам вызов инструмента получает исходные значения.
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.redact import MASK, redact, redact_text          # noqa: E402
from core.session_manager import SessionManager            # noqa: E402

FAILURES = []

# Синтетические (недействительные) токены: собираем из частей, чтобы в файле не
# лежал литерал, похожий на настоящий секрет (иначе push-protection GitHub и
# утечка в историю).
HF_TOKEN = "hf_" + "0" * 34
OPENAI_TOKEN = "sk-" + "0" * 32


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("\n[1] маскирование значений")
    cases = [
        (f"Authorization: Bearer {HF_TOKEN}", "Bearer"),
        (f"authorization={HF_TOKEN}", "authorization"),
        (f"api_key: {OPENAI_TOKEN}", "api_key"),
        ("password=hunter2secret", "password"),
        (f"https://user:{HF_TOKEN}@example.com/x", "https://"),
    ]
    for text, marker in cases:
        out = redact_text(text)
        check(f"mask_{marker}", HF_TOKEN not in out and OPENAI_TOKEN not in out
              and "hunter2secret" not in out and MASK in out, out)
    # токены без ключа-подсказки (просто в строке)
    check("mask_bare_hf", HF_TOKEN not in redact_text(f"см. {HF_TOKEN} тут"))
    check("mask_bare_openai", OPENAI_TOKEN not in redact_text(f"ключ {OPENAI_TOKEN}"))

    print("\n[2] обычные данные не портятся")
    for text in ["query=погода", "url=https://example.com/page?q=1",
                 "path=/home/user/project/file.txt", "text=token of appreciation"]:
        check(f"keep_{text[:18]}", redact_text(text) == text, redact_text(text))

    print("\n[3] dict/list аргументы")
    args = {"headers": [f"Authorization: Bearer {HF_TOKEN}"],
            "api_key": HF_TOKEN, "query": "погода", "url": "https://x/y"}
    red = redact(args)
    check("dict_secret_key_masked", red["api_key"] == MASK, str(red["api_key"]))
    check("dict_header_masked", HF_TOKEN not in red["headers"][0], red["headers"][0])
    check("dict_plain_kept", red["query"] == "погода" and red["url"] == "https://x/y", str(red))
    check("original_untouched", args["api_key"] == HF_TOKEN)

    print("\n[4] запись в tools.log сессии")
    with tempfile.TemporaryDirectory() as sess:
        sm = SessionManager()
        sm.log_tool_call(sess, "web",
                         {"action": "json", "headers": [f"Authorization: Bearer {HF_TOKEN}"]},
                         f"ответ с {HF_TOKEN} внутри", status="completed")
        raw = open(os.path.join(sess, "tools.log"), encoding="utf-8").read()
        entry = json.loads(raw.strip().splitlines()[-1])
        check("log_no_token_in_args", HF_TOKEN not in json.dumps(entry["arguments"], ensure_ascii=False),
              str(entry["arguments"])[:160])
        check("log_no_token_in_result", HF_TOKEN not in entry["full_result"], entry["full_result"][:120])
        check("log_masked_marker", MASK in json.dumps(entry, ensure_ascii=False))
        check("log_keeps_structure", entry["tool"] == "web" and entry["status"] == "completed"
              and isinstance(entry["arguments"]["headers"], list))

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ МАСКИРОВАНИЕ СЕКРЕТОВ ПРОЙДЕНО")
    return 0


def test_log_redaction() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
