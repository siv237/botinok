#!/usr/bin/env python3
"""
Тесты core/api_key_gate: распознавание ошибок ключа, ссылка на выдачу,
сохранение в персональный конфиг; модалка ApiKeyScreen (Textual Pilot).

Запуск: venv/bin/python -u tests/test_api_key_gate.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.api_key_gate as gate  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


class FakeSM:
    def __init__(self, pairs):
        import configparser
        self.config = configparser.ConfigParser()
        self.config['Ollama'] = dict(pairs)


def test_is_auth_error():
    check("401 без текста", gate.is_auth_error(401))
    check("401 LiteLLM", gate.is_auth_error(401, "Authentication Error, No api key passed in."))
    check("403 с текстом про ключ", gate.is_auth_error(403, "The api key is not valid"))
    check("403 без текста про ключ — не оно", not gate.is_auth_error(403, "disk quota exceeded"))
    check("400 — не оно", not gate.is_auth_error(400, "model not found"))
    check("500 — не оно", not gate.is_auth_error(500, "boom"))
    check("мусор вместо кода", not gate.is_auth_error(None, "x"))


def test_key_entry_url():
    sm = FakeSM({'KeyUrl': 'https://llm.dgk.ru/register', 'BaseUrl': 'https://api.example/x'})
    check("KeyUrl из конфига", gate.key_entry_url(sm) == 'https://llm.dgk.ru/register')
    sm = FakeSM({'BaseUrl': 'https://llm.dgk.ru/v1'})
    check("fallback: корень BaseUrl", gate.key_entry_url(sm) == 'https://llm.dgk.ru/')
    sm = FakeSM({'BaseUrl': 'http://localhost:11434'})
    check("fallback http без пути", gate.key_entry_url(sm) == 'http://localhost:11434/')
    sm = FakeSM({})
    check("пустой конфиг — пусто", gate.key_entry_url(sm) == '')


def test_save_api_key():
    tmp = tempfile.mkdtemp()
    old_home = os.environ.get('HOME')
    os.environ['HOME'] = tmp
    try:
        sm = FakeSM({'BaseUrl': 'https://llm.dgk.ru'})
        path = gate.save_api_key(sm, 'sk-secret-123')
        check("путь в персональном конфиге",
              path == os.path.join(tmp, '.config', 'botinok', 'config.cfg'))
        check("файл создан", os.path.exists(path))
        import configparser
        cp = configparser.ConfigParser()
        cp.read(path)
        check("ключ записан", cp.get('Ollama', 'ApiKey') == 'sk-secret-123')
        check("в живом конфиг-объекте тоже", sm.config.get('Ollama', 'ApiKey') == 'sk-secret-123')
        # перезапись не должна терять другие секции
        cp.add_section('UI')
        cp.set('UI', 'ShowTPS', 'false')
        with open(path, 'w') as f:
            cp.write(f)
        gate.save_api_key(sm, 'sk-new')
        cp2 = configparser.ConfigParser()
        cp2.read(path)
        check("секции пользователя сохранены", cp2.get('UI', 'ShowTPS') == 'false')
        check("ключ обновлён", cp2.get('Ollama', 'ApiKey') == 'sk-new')
        # merge: персональный конфиг не должен терять поля эффективного конфига
        sm2 = FakeSM({'BaseUrl': 'https://llm.dgk.ru', 'Backend': 'openai',
                      'DefaultModel': 'qwen3.8:27b'})
        gate.save_api_key(sm2, 'sk-merge')
        cp3 = configparser.ConfigParser()
        cp3.read(gate.save_api_key(sm2, 'sk-merge'))
        check("merge: BaseUrl перенесён", cp3.get('Ollama', 'BaseUrl') == 'https://llm.dgk.ru')
        check("merge: Backend перенесён", cp3.get('Ollama', 'Backend') == 'openai')
        check("merge: DefaultModel перенесён", cp3.get('Ollama', 'DefaultModel') == 'qwen3.8:27b')
    finally:
        if old_home is not None:
            os.environ['HOME'] = old_home


def test_apikey_screen():
    try:
        from textual.app import App
        from core.textual_app import ApiKeyScreen
    except Exception as e:
        check("импорт ApiKeyScreen", False, str(e))
        return

    class HostApp(App):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.resolved = 'unset'

        def on_mount(self):
            self.push_screen(ApiKeyScreen(
                "llm.dgk.ru", "https://llm.dgk.ru", "No api key passed in.",
                on_resolve=lambda k: setattr(self, 'resolved', k)))

    async def run_case(submit_value):
        app = HostApp()
        async with app.run_test() as pilot:
            from textual.widgets import Input
            await pilot.pause()
            inp = app.screen.query_one("#apikey_input", Input)
            await pilot.click(inp)
            await pilot.press(*list(submit_value))
            await pilot.press("enter")
            await pilot.pause()
        return app.resolved

    try:
        res = asyncio.run(run_case("sk-test-42"))
        check("Enter резолвит введённым ключом", res == "sk-test-42", repr(res))

        res2 = asyncio.run(run_case(""))
        check("пустой Enter — None", res2 is None, repr(res2))
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("ApiKeyScreen Pilot", False, str(e))


def main() -> int:
    print("=" * 60)
    print("api_key_gate tests")
    print("=" * 60)
    test_is_auth_error()
    test_key_entry_url()
    test_save_api_key()
    test_apikey_screen()
    print("-" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
