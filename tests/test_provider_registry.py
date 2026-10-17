#!/usr/bin/env python3
"""
Тесты core/provider_registry: сжатие реестра, поиск, lookup по хосту и
локальный кэш. Без сети (requests.get подменяется).

Запуск: venv/bin/python -u tests/test_provider_registry.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

import core.provider_registry as pr  # noqa: E402

FAILURES = []
_TMP = tempfile.mkdtemp(prefix="botinok_registry_")


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeSM:
    def __init__(self):
        self.config_path = os.path.join(tempfile.mkdtemp(dir=_TMP), "config.cfg")


RAW = {
    "fireworks": {"name": "Fireworks AI",
                  "api": "https://api.fireworks.ai/inference/v1/"},
    "openrouter": {"name": "OpenRouter", "api": "https://openrouter.ai/api/v1"},
    "zai": {"name": "Z.ai", "api": "https://api.z.ai/api/paas/v4"},
    "noapi": {"name": "No API"},  # без api — не попадает
    "dupe": {"name": "Dup", "api": "https://openrouter.ai/api/v1"},  # тот же хост
}


def test_build():
    p = pr.build_providers(RAW)
    hosts = {e['host'] for e in p}
    check("без api отброшен", "noapi" not in {e['id'] for e in p})
    check("дубликат хоста отброшен", len([e for e in p if e['host'] == 'openrouter.ai']) == 1)
    check("хост извлечён", "api.fireworks.ai" in hosts and "api.z.ai" in hosts)
    check("хвостовой слэш убран",
          any(e['api'] == "https://api.fireworks.ai/inference/v1" for e in p))


def test_lookup_and_search():
    p = pr.build_providers(RAW)
    check("lookup по хосту",
          pr.lookup(p, "https://api.fireworks.ai/inference/v1") ==
          "https://api.fireworks.ai/inference/v1")
    check("lookup без схемы",
          pr.lookup(p, "api.fireworks.ai") == "https://api.fireworks.ai/inference/v1")
    check("lookup неизвестного хоста", pr.lookup(p, "nope.example") is None)
    names = [e['name'] for e in pr.search(p, "fire")]
    check("поиск по имени", names == ["Fireworks AI"], str(names))
    hosts = [e['host'] for e in pr.search(p, "z.ai")]
    check("поиск по домену", hosts == ["api.z.ai"], str(hosts))
    check("пустой запрос — весь список", len(pr.search(p, "")) == len(p))
    check("несовпадение — пусто", pr.search(p, "zzz") == [])


def test_cache_and_no_network():
    sm = FakeSM()
    check("пустой кэш — нет сети", pr.load(sm) == [] and pr.age_text(sm) == "нет данных")

    def boom(*a, **k):
        raise AssertionError("load() не должен ходить в сеть")

    real = pr.requests.get
    pr.requests.get = boom
    try:
        check("load не ходит в сеть", pr.load(sm) == [])
    finally:
        pr.requests.get = real

    class R:
        status_code = 200
        @staticmethod
        def json():
            return RAW

    real = pr.requests.get
    pr.requests.get = lambda *a, **k: R()
    try:
        got = pr.refresh(sm)
        check("refresh скачал и вернул", got is not None and len(got) == 3)
        check("кэш записан", len(pr.load(sm)) == 3)
        check("кэш свежий", pr.is_fresh(sm))
        check("age_text не пустой", pr.age_text(sm) != "нет данных")
        check("updated_at > 0", pr.updated_at(sm) > 0)
    finally:
        pr.requests.get = real


def main():
    print("=" * 60)
    print("provider registry tests")
    print("=" * 60)
    test_build()
    test_lookup_and_search()
    test_cache_and_no_network()
    print("-" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
