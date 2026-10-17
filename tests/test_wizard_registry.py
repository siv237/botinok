#!/usr/bin/env python3
"""
Тесты визарда и реестра провайдеров: ветка «выбрать из базы» и ГЛАВНОЕ —
никаких обращений в интернет за реестром без явного согласия пользователя.

Запуск: venv/bin/python -u tests/test_wizard_registry.py
"""

import configparser
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.config_wizard as cw  # noqa: E402
import core.provider_registry as pr  # noqa: E402

FAILURES = []
_TMP = tempfile.mkdtemp(prefix="botinok_wiz_reg_")

ENTRIES = [
    {'id': 'fireworks', 'name': 'Fireworks AI', 'host': 'api.fireworks.ai',
     'api': 'https://api.fireworks.ai/inference/v1'},
    {'id': 'openrouter', 'name': 'OpenRouter', 'host': 'openrouter.ai',
     'api': 'https://openrouter.ai/api/v1'},
]


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def make_wizard(cached, refresh_result):
    w = object.__new__(cw.ConfigWizard)
    cfg = configparser.ConfigParser()
    cfg.add_section('Ollama')
    w.config = cfg
    w.sm = type("FakeSM", (), {
        "config_path": os.path.join(tempfile.mkdtemp(dir=_TMP), "config.cfg")})()
    calls = {'refresh': 0}
    pr.load = lambda sm: list(cached)
    def _refresh(sm, timeout=25):
        calls['refresh'] += 1
        return list(refresh_result) if refresh_result is not None else []
    pr.refresh = _refresh
    pr.age_text = lambda sm: "только что"
    pr.updated_date = lambda sm: "2026-10-17 06:00"
    return w, calls


def scripted(confirms, prompts, selects, seen=None, seen_sel=None):
    conf, prom, sel = list(confirms), list(prompts), list(selects)

    def _prompt(message, default="", password=False, buttons=None):
        if seen is not None:
            seen.append(buttons)
        return prom.pop(0) if prom else None

    def _select(title, options, default=None, filterable=False):
        if seen_sel is not None:
            seen_sel.append(filterable)
        return sel.pop(0) if sel else None

    cw.textual_confirm = lambda m, default=True: conf.pop(0) if conf else None
    cw.textual_prompt = _prompt
    cw.textual_select = _select


def test_pick_search_no_network():
    w, calls = make_wizard(ENTRIES, None)
    sel_seen = []
    scripted([], [], [ENTRIES[0]['api']], seen_sel=sel_seen)
    picked = w._pick_provider()
    check("выбор из базы", picked == ENTRIES[0]['api'], str(picked))
    check("выбор НЕ ходит в сеть", calls['refresh'] == 0, str(calls))
    check("список с фильтром", sel_seen and sel_seen[0] is True, str(sel_seen))


def test_pick_refresh_is_explicit():
    w, calls = make_wizard(ENTRIES, ENTRIES)
    scripted([], [], ["__refresh__", ENTRIES[0]['api']])
    picked = w._pick_provider()
    check("обновление по пункту списка", calls['refresh'] == 1, str(calls))
    check("после обновления выбор работает", picked == ENTRIES[0]['api'])


def test_pick_empty_load_button():
    w, calls = make_wizard([], ENTRIES)
    scripted([], [], [None])
    check("пусто + отмена — None", w._pick_provider() is None)
    check("пусто + отмена — без сети", calls['refresh'] == 0, str(calls))

    w, calls = make_wizard([], ENTRIES)
    scripted([], [], ["__refresh__", ENTRIES[0]['api']])
    picked = w._pick_provider()
    check("пусто + загрузка — скачивает", calls['refresh'] == 1, str(calls))
    check("пусто + загрузка — выбор", picked == ENTRIES[0]['api'])


def test_question_mark_branch_no_registry_network():
    """Ввод «?» открывает базу; реестр не качается, если кэш уже есть."""
    w, calls = make_wizard(ENTRIES, None)
    w._pick_provider = lambda: ENTRIES[0]['api']
    w.check_openai = lambda url, key="", verify=True: (
        True, [{'id': 'm', 'context': None}], None, url)
    # prompt: "?" -> затем адрес (пусто, берём подставленный из базы) -> ключ
    seen = []
    scripted([True], ["?", "", "k"], [], seen=seen)
    models = w._configure_openai()
    check("ветка «?» сработала", models == [{'id': 'm', 'context': None}], str(models))
    check("«?» не качает реестр", calls['refresh'] == 0, str(calls))
    check("подставлен адрес из базы",
          w.config.get('Ollama', 'BaseUrl') == ENTRIES[0]['api'],
          w.config.get('Ollama', 'BaseUrl', fallback='?'))
    btn_values = [v for b in seen if b for _lbl, v in b]
    check("кнопка поиска передана в поле ввода", "?" in btn_values, str(btn_values))


def main():
    print("=" * 60)
    print("wizard registry tests")
    print("=" * 60)
    test_pick_search_no_network()
    test_pick_refresh_is_explicit()
    test_pick_empty_load_button()
    test_question_mark_branch_no_registry_network()
    print("-" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
