#!/usr/bin/env python3
"""
Тесты неблокирующей PTY-сессии (core/shell_session.py).

Покрывают главные сценарии «shell как отдельная сессия»:
  1. Вывод простой команды читается без блокировки агента.
  2. Сессия НЕ держит агента: команда крутится в фоне, returncode сначала None.
  3. Ответ на вопрос программы: send_input() — ввод пароля/пункта меню.
  4. Спец-клавиши: send_key("enter"/"down"/"y") — выбор пункта меню.
  5. Поиск по выводу: search_output() — агент «читает со стороны».
  6. Параллельное чтение из потока, не блокируя агентский цикл.
  7. Завершение: returncode корректный, is_running() False, kill() работает.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.shell_session import ShellSession, ShellSessionRegistry  # noqa: E402

TESTS: list = []
FAILURES: list = []


def test(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


def _wait_output(s: ShellSession, needle: str, timeout: float = 8.0) -> bool:
    """Ждём, пока в очищенном выводе не появится needle."""
    end = time.time() + timeout
    while time.time() < end:
        if needle in s.get_output():
            return True
        if not s.is_running() and needle not in s.get_output():
            time.sleep(0.1)
            continue
        time.sleep(0.05)
    return False


# ------------------------------------------------------------------ tests

@test("01_simple_output")
def _01():
    s = ShellSession(command="echo hello_world_123", cwd="/tmp")
    s.start()
    assert s.wait(5), "команда не завершилась"
    out = s.get_output()
    assert "hello_world_123" in out, f"нет вывода: {out!r}"
    assert s.returncode == 0, f"returncode={s.returncode}"
    assert not s.is_running()


@test("02_non_blocking")
def _02():
    """Команда крутится в фоне — агент не держится."""
    s = ShellSession(command="sleep 2; echo AFTER_SLEEP", cwd="/tmp")
    s.start()
    time.sleep(0.3)
    # Команда ещё жива, а мы уже управляем: returncode None, вывод пуст
    assert s.is_running(), "сессия должна быть жива"
    assert s.returncode is None, "returncode должен быть None"
    assert "AFTER_SLEEP" not in s.get_output()
    tail0 = s.get_output(tail_lines=5)
    assert tail0 == "", f"вывод должен быть пуст: {tail0!r}"
    assert s.wait(6), "команда не завершилась"
    assert "AFTER_SLEEP" in s.get_output()
    s.close()


@test("03_send_input_answer_question")
def _03():
    """Программа задаёт вопрос — агент/юзер вводит ответ в ту же сессию."""
    cmd = (
        'echo "QUESTION: enter your name:"; '
        "read name; "
        'echo "GOT_NAME=$name"'
    )
    s = ShellSession(command=cmd, cwd="/tmp")
    s.start()
    assert _wait_output(s, "enter your name"), "промпт не появился"
    assert s.is_running(), "программа ждёт ввода"
    sent = s.send_input("AgentBot")
    assert sent > 0, "байты не отправлены"
    assert _wait_output(s, "GOT_NAME=AgentBot"), "ответ не зафиксирован"
    assert s.wait(5)
    assert "AgentBot" in s.get_output()
    s.close()


@test("04_send_key_menu_number")
def _04():
    """Выбор пункта меню: send_key('3') + send_key('enter')."""
    cmd = (
        "PS3='choose> '; "
        "options=('alpha' 'beta' 'gamma'); "
        "select opt in \"${options[@]}\"; do echo \"CHOSEN=$opt\"; break; done"
    )
    s = ShellSession(command=cmd, cwd="/tmp")
    s.start()
    assert _wait_output(s, "choose>"), "меню не появилось"
    assert s.is_running()
    s.send_key("3")
    time.sleep(0.15)
    s.send_key("enter")
    assert _wait_output(s, "CHOSEN=gamma"), f"пункт не выбран: {s.get_output()!r}"
    assert s.wait(5)
    s.close()


@test("04b_send_key_arrows")
def _04b():
    """Спец-клавиши доходят до программы: ловим ESC-последовательность стрелки."""
    # cat переводит режим терминала в raw и отдаёт нажатия как есть.
    cmd = "stty -icanon -echo min 1; cat; stty echo icanon"
    s = ShellSession(command=cmd, cwd="/tmp")
    s.start()
    time.sleep(0.2)
    s.send_key("down")   # \x1b[B
    assert _wait_output(s, "B") or s.get_raw_tail().endswith(b"B") or b"B" in s.get_raw_tail()
    s.send_key("ctrl-c")
    s.wait(3)
    s.close()


@test("04c_password_prompt")
def _04c():
    """Ввод пароля: промпт без \\n виден, ответ доходит, не ломая эхо."""
    cmd = (
        'echo "ENTER_PASSWORD_PROMPT"; '
        "read -s -p 'Password: ' pw; "
        'echo ""; echo "PW_OK=$pw"'
    )
    s = ShellSession(command=cmd, cwd="/tmp")
    s.start()
    assert _wait_output(s, "Password:"), "промпт пароля не появился"
    assert s.is_running()
    s.send_input("secret123")
    assert _wait_output(s, "PW_OK=secret123"), f"пароль не дошёл: {s.get_output()!r}"
    assert s.wait(5)
    s.close()


@test("05_search_output_regex")
def _05():
    cmd = "for i in $(seq 1 20); do echo \"LINE_$i value=$((i*7))\"; done; sleep 0.3"
    s = ShellSession(command=cmd, cwd="/tmp")
    s.start()
    assert s.wait(6)
    # Простой поиск
    r = s.search_output("LINE_15")
    assert "LINE_15" in r, f"не найдено: {r!r}"
    # Regex
    r2 = s.search_output(r"value=7[0-9]", regex=True)
    assert "value=70" in r2 or "value=77" in r2 or "value=7" in r2, f"regex: {r2!r}"
    # Несуществующее
    r3 = s.search_output("ZZZ_NOPE")
    assert "Совпадений не найдено" in r3
    # Контекст
    r4 = s.search_output("LINE_10", context=1)
    assert "LINE_9" in r4 and "LINE_11" in r4, f"контекст: {r4!r}"
    s.close()


@test("06_concurrent_reader")
def _06():
    """Параллельный читатель-подписчик не блокирует агентский цикл."""
    s = ShellSession(command="for i in $(seq 1 50); do echo \"TICK_$i\"; sleep 0.05; done",
                     cwd="/tmp")
    received: list = []
    lock = time.time()

    def on_chunk(chunk: bytes):
        received.append(chunk)

    s.subscribe(on_chunk)
    s.start()
    # Имитируем «агента», который делает что-то своё, пока команда пишет вывод
    t0 = time.time()
    while time.time() - t0 < 2.0:
        if not s.is_running():
            break
        time.sleep(0.1)  # агент «не держится» сессией
    assert len(received) > 10, f"подписчик получил мало чанков: {len(received)}"
    s.unsubscribe(on_chunk)
    s.wait(5)
    s.close()


@test("07_kill_timeout")
def _07():
    """kill() и timeout_sec прибивают зависшую команду."""
    s = ShellSession(command="sleep 60", cwd="/tmp")
    s.start()
    time.sleep(0.3)
    assert s.is_running()
    t0 = time.time()
    s.kill()
    assert s.wait(5), "kill не сработал"
    assert time.time() - t0 < 5, "kill слишком долго"
    assert not s.is_running()
    s.close()

    # timeout
    s2 = ShellSession(command="sleep 60", cwd="/tmp", timeout_sec=1)
    s2.start()
    assert s2.wait(8), "timeout не сработал"
    assert not s2.is_running()
    s2.close()


@test("08_registry")
def _08():
    reg = ShellSessionRegistry.instance()
    s = ShellSession(command="echo registry_test", cwd="/tmp")
    reg.add(s)
    sid = s.session_id
    assert reg.get(sid) is s
    lst = reg.list()
    assert any(x["session_id"] == sid for x in lst), f"нет в списке: {lst}"
    assert reg.get("nonexistent") is None
    reg.remove(sid)
    assert reg.get(sid) is None


@test("09_ansi_color_stripped")
def _09():
    cmd = 'printf "\\033[31mRED_TEXT\\033[0m PLAIN\\n"; echo DONE_ANSI'
    s = ShellSession(command=cmd, cwd="/tmp")
    s.start()
    assert s.wait(5)
    clean = s.get_output()
    assert "RED_TEXT" in clean and "PLAIN" in clean, f"нет текста: {clean!r}"
    assert "\x1b[" not in clean, f"ANSI не вырезан: {clean!r}"
    assert "DONE_ANSI" in clean
    s.close()


@test("10_raw_tail_has_colors")
def _10():
    """Сырой хвост для артефакта сохраняет цвета."""
    cmd = 'printf "\\033[32mGREEN\\033[0m\\n"'
    s = ShellSession(command=cmd, cwd="/tmp")
    s.start()
    assert s.wait(5)
    raw = s.get_raw_tail()
    assert b"\x1b[32m" in raw, f"цвет не сохранён: {raw!r}"
    s.close()


# ------------------------------------------------------------------ runner

def main() -> int:
    print("=" * 70)
    print("ShellSession tests — PTY-сессия, не держащая агента")
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
