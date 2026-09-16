#!/usr/bin/env python3
"""
Интеграционный тест инструмента tools/shell_exec.py как «отдельной сессии».

Сценарий «агент смотрит со стороны»:
  1. run      — запускаем интерактивную команду (сессия не держит агента).
  2. status   — пока команда жива, проверяем, что агент свободен.
  3. read/search — читаем вывод и ищем промпт, не выгружая весь буфер.
  4. send     — отвечаем на вопрос программы (логин/пароль).
  5. send_key — выбираем пункт меню.
  6. wait     — дожидаемся завершения.
  7. kill     — прерываем зависшую команду.
  8. list     — реестр сессий.

UI-экран (ShellScreen) тестируется отдельно — здесь headless-режим.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.shell_exec import shell_exec  # noqa: E402

TESTS: list = []
FAILURES: list = []


def test(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


def _run(command: str, **kw) -> dict:
    raw = shell_exec(command=command, action="run", **kw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise AssertionError(f"невалидный JSON ответа: {raw[:200]!r}")


def _do(action: str, **kw) -> dict:
    raw = shell_exec(action=action, **kw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise AssertionError(f"невалидный JSON ответа: {raw[:200]!r}")


# ------------------------------------------------------------------ tests

@test("run_start_interactive_session")
def _01():
    r = _run("echo HI_FROM_SHELL; sleep 1", interactive=True)
    assert "session_id" in r, f"нет session_id: {r}"
    assert r["running"] is True, f"сессия должна жить: {r}"
    assert r["returncode"] is None, "returncode должен быть None"
    assert "HI_FROM_SHELL" in r["output_tail"], f"нет вывода: {r['output_tail']!r}"
    # Сессия не держит: статус можно дёргать параллельно
    st = _do("status", session_id=r["session_id"])
    assert st["running"] is True
    assert st["session_id"] == r["session_id"]


@test("agent_reads_output_without_blocking")
def _02():
    r = _run("for i in $(seq 1 10); do echo \"OUT_$i\"; sleep 0.1; done",
             interactive=True)
    sid = r["session_id"]
    # Команда ещё работает, а агент уже читаетtail
    rd = _do("read", session_id=sid, tail_lines=5)
    assert "OUT_" in rd["output_tail"] or rd["running"], f"не читается: {rd}"
    # ...и может что-то делать параллельно
    time.sleep(1.5)
    rd2 = _do("read", session_id=sid, tail_lines=5)
    assert "OUT_10" in rd2["output_tail"], f"не дождались вывода: {rd2}"


@test("agent_searches_output")
def _03():
    r = _run("for i in $(seq 1 30); do echo \"ITEM_$i val=$((i*3))\"; done; sleep 0.2",
             interactive=True)
    sid = r["session_id"]
    sr = _do("search", session_id=sid, pattern="ITEM_21")
    assert "ITEM_21" in sr["matches"], f"не найдено: {sr}"
    sr2 = _do("search", session_id=sid, pattern=r"val=6[0-9]", regex=True, context=1)
    assert "val=60" in sr2["matches"] or "val=63" in sr2["matches"], f"regex: {sr2}"


@test("agent_answers_password_prompt")
def _04():
    cmd = ('echo "LOGIN_PROMPT"; read -s -p "Password: " pw; echo ""; '
           'echo "AUTH_OK=$pw"')
    r = _run(cmd, interactive=True)
    sid = r["session_id"]
    # Ищем промпт со стороны
    found = False
    for _ in range(60):
        sr = _do("search", session_id=sid, pattern="Password:")
        if "Password:" in sr["matches"]:
            found = True
            break
        time.sleep(0.1)
    assert found, "промпт пароля не найден"
    # Отвечаем в ту же сессию
    sr2 = _do("send", session_id=sid, input="S3cretPass")
    assert "AUTH_OK=S3cretPass" in sr2["output_tail"], f"пароль не дошёл: {sr2}"


@test("agent_selects_menu_item")
def _05():
    cmd = ("PS3='menu> '; options=('red' 'green' 'blue'); "
           "select opt in \"${options[@]}\"; do echo \"PICKED=$opt\"; break; done")
    r = _run(cmd, interactive=True)
    sid = r["session_id"]
    for _ in range(60):
        sr = _do("search", session_id=sid, pattern="menu>")
        if "menu>" in sr["matches"]:
            break
        time.sleep(0.1)
    _do("send_key", session_id=sid, key="2")
    time.sleep(0.2)
    _do("send_key", session_id=sid, key="enter")
    wr = _do("wait", session_id=sid, wait_timeout=5)
    assert "PICKED=green" in wr["output_tail"], f"меню не выбрано: {wr}"


@test("wait_and_returncode")
def _06():
    r = _run("exit 7", interactive=True)
    wr = _do("wait", session_id=r["session_id"], wait_timeout=5)
    assert wr["returncode"] == 7, f"returncode: {wr}"
    assert wr["running"] is False


@test("kill_hung_session")
def _07():
    r = _run("sleep 120", interactive=True)
    sid = r["session_id"]
    assert r["running"] is True
    kr = _do("kill", session_id=sid)
    assert kr["killed"] is True
    assert kr["returncode"] is not None
    assert kr["running"] is False


@test("list_sessions")
def _08():
    r = _run("echo LIST_TEST", interactive=True)
    lr = _do("list")
    assert any(s["session_id"] == r["session_id"] for s in lr["sessions"]), f"нет в списке: {lr}"
    # Несуществующая сессия → понятная ошибка
    bad = _do("status", session_id="nope_123")
    assert "error" in bad, f"ожидали error: {bad}"
    assert "available" in bad


@test("batch_mode_compat")
def _09():
    """batch-режим для совместимости: команда отрабатывает синхронно."""
    r = _run("echo BATCH_OK", interactive=False, timeout_sec=10)
    assert r["mode"] == "batch"
    assert r["returncode"] == 0
    assert "BATCH_OK" in r["output_tail"]


@test("empty_command_rejected")
def _10():
    r = _run("   ", interactive=True)
    assert "error" in r, f"ожидали error: {r}"


# ------------------------------------------------------------------ runner

def main() -> int:
    print("=" * 70)
    print("shell_exec tool tests — «shell как отдельная сессия» (headless)")
    print("=" * 70)
    passed = 0
    failed = 0
    for name, fn in TESTS:
        t0 = time.time()
        try:
            fn()
            dt = (time.time() - t0) * 1000
            print(f"  [PASS] {name}  ({dt:.0f} ms)")
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
            FAILURES.append((name, str(e)))
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            FAILURES.append((name, f"{type(e).__name__}: {e}"))
    print("=" * 70)
    print(f"Итого: {passed} passed, {failed} failed, всего {len(TESTS)}")
    if failed:
        print("\nПровалы:")
        for n, e in FAILURES:
            print(f"  - {n}: {e}")
        return 1
    print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
