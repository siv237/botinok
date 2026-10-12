#!/usr/bin/env python3
"""
Сид истории веб-зеркала: служебные пинки харнеса (sign_step, авто-продолжение
после очистки контекста, финальный ответ) не должны ехать в браузер как
реплики пользователя; мысли «(во время работы)» — как мысли.

Запуск: venv/bin/python -u tests/test_mirror_history_filter.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.textual_app import BotinokTextualApp  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    d = tempfile.mkdtemp(prefix="botinok_mirror_hist_")
    msgs = [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "здравствуйте"},
        {"role": "user",
         "content": "Перед завершением хода вызови инструмент sign_step, если…"},
        {"role": "user",
         "content": ("Продолжай выполнение последнего запроса пользователя после "
                     "авто-очистки контекста.\nlast_user_prompt: продолжай\n"
                     "session_path: /x\nfull_history_artifact: /y.json")},
        {"role": "user",
         "content": "Сформулируй финальный ответ на последний запрос пользователя.\n…"},
        {"role": "user",
         "content": ("🌐 WEB-ЗАДАЧИ (фон):\n✅ готова «vt-gui-proxy» (job_id=w007-fbb623) "
                     "— забери: web action=job job_id=w007-fbb623\n"
                     "Опрос: web action=jobs. Не считай эти задачи готовыми, пока не придёт ✅.")},
        {"role": "user", "content": "(во время работы) посмотри ещё погоду"},
        {"role": "assistant", "content": "ок"},
    ]
    with open(os.path.join(d, "messages.json"), "w", encoding="utf-8") as f:
        json.dump({"messages": msgs}, f, ensure_ascii=False)

    class Dummy:
        session_path = d

    groups = BotinokTextualApp._mirror_history_groups(Dummy())
    events = [e for g in groups for e in g]
    users = [e["text"] for e in events if e["t"] == "user"]
    thoughts = [e["text"] for e in events if e["t"] == "thought"]
    check("реальные реплики целы", users == ["привет"], str(users))
    check("пинк sign_step отфильтрован",
          all("sign_step" not in u for u in users), str(users))
    check("пинк авто-продолжения отфильтрован",
          all("авто-очистки" not in u for u in users), str(users))
    check("пинк финального ответа отфильтрован",
          all("Сформулируй финальный" not in u for u in users), str(users))
    check("пинк фоновых web-задач отфильтрован",
          all("WEB-ЗАДАЧИ" not in u for u in users), str(users))
    check("мысль показана как мысль", thoughts == ["посмотри ещё погоду"], str(thoughts))
    print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if not FAILURES else 'ПРОВАЛЫ: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
