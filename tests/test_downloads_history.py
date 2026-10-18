#!/usr/bin/env python3
"""Регрессия `web action=downloads`: быстрая проверка по умолчанию.

Симптом (найден на живой истории): `web action=downloads` зависал на минуты,
потому что `download_manager.verify()` пересчитывал sha256 каждого файла
истории, включая гигабайтные модели (29 ГБ в истории этой машины), да ещё и
читая файл целиком в память (`f.read()`).

Проверяется:
  * по умолчанию sha256 не пересчитывается (проверка наличие/размер/каталог);
  * `verify=true` включает глубокую сверку, несовпадение хеша видно;
  * успешная глубокая сверка кэшируется (повторно файл не хешируется);
  * `record(status="completed")` помечает свежую загрузку проверенной;
  * предварительная проверка «уже скачано» больше не хеширует файл;
  * `sha256_file` читает потоком и даёт корректный хеш;
  * строковый `verify="false"` трактуется как False.

Запуск: venv/bin/python -u tests/test_downloads_history.py
        venv/bin/python -m pytest tests/test_downloads_history.py -q
"""

import hashlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.tool_manager import ToolManager          # noqa: E402
from tools import download_manager as dlm          # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class NoHash:
    """Заглушка: любой вызов sha256 — провал теста (значит, файл читали)."""

    def __init__(self, real):
        self.real = real
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        raise AssertionError("sha256 вызван — файл читали целиком")

    def __getattr__(self, item):
        return getattr(self.real, item)


def _write_history(path: str, entries: list) -> None:
    data = {}
    for e in entries:
        data[f"{e['url']}\n{e.get('dest') or ''}"] = e
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _entry(url, dest, size=None, sha=None, status="completed"):
    return {"url": url, "dest": dest, "status": status, "total": size, "sha256": sha,
            "updated": "2026-10-18T10:00:00"}


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="bt_dl_")
    old_env = os.environ.get("BOTINOK_DOWNLOAD_HISTORY")
    os.environ["BOTINOK_DOWNLOAD_HISTORY"] = os.path.join(tmp, "history.json")
    tm = ToolManager()
    real_sha256 = hashlib.sha256

    def make_file(name: str, data: bytes) -> str:
        path = os.path.join(tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    try:
        ok = make_file("ok.bin", b"A" * 4096)
        bad = make_file("bad.bin", b"B" * 4096)
        short = make_file("short.bin", b"C" * 100)
        ok_sha = hashlib.sha256(b"A" * 4096).hexdigest()
        _write_history(os.environ["BOTINOK_DOWNLOAD_HISTORY"], [
            _entry("https://x/ok", ok, 4096, ok_sha),
            _entry("https://x/bad", bad, 4096, "0" * 64),
            _entry("https://x/gone", os.path.join(tmp, "nope.bin"), 10, None),
            _entry("https://x/short", short, 999, None),
        ])

        print("\n[1] быстрый режим: sha256 не читается")
        guard = NoHash(real_sha256)
        dlm.hashlib.sha256 = guard
        out = str(tm.call_tool("web", {"action": "downloads"}))
        check("no_hashing_by_default", guard.calls == 0, f"вызовов sha256: {guard.calls}")
        check("fast_mode_reported", "быстрая проверка" in out, out[:120])
        check("wrong_sha_not_flagged", "sha256 не совпадает" not in out, out[:200])
        check("missing_file_flagged", "файл отсутствует" in out, out[:400])
        check("short_file_flagged", "недокачан" in out, out[:400])
        fast_reason = dlm.verify(_entry("u", ok, 4096, ok_sha), deep=False)[1]
        check("fast_reason_no_sha", "sha256 не пересчитывался" in fast_reason, fast_reason)

        print("\n[2] строковый verify=false — это False (без хеширования)")
        out = str(tm.call_tool("web", {"action": "downloads", "verify": "false"}))
        check("string_false_no_hash", guard.calls == 0, f"вызовов sha256: {guard.calls}")

        print("\n[3] verify=true: глубокая сверка находит битый хеш")
        dlm.hashlib.sha256 = real_sha256
        out = str(tm.call_tool("web", {"action": "downloads", "verify": "true"}))
        check("deep_mode_reported", "sha256 сверяется" in out, out[:120])
        check("deep_flags_bad_sha", "sha256 не совпадает" in out, out[:400])
        ok_deep = dlm.verify(_entry("u", ok, 4096, ok_sha), deep=True)
        bad_deep = dlm.verify(_entry("u", bad, 4096, "0" * 64), deep=True)
        check("deep_reason_ok", ok_deep[0] and "сверен" in ok_deep[1], str(ok_deep))
        check("deep_reason_bad", not bad_deep[0] and "не совпадает" in bad_deep[1], str(bad_deep))

        print("\n[4] кэш: повторная глубокая проверка не хеширует снова")
        hist = dlm._load(None)
        cached = [e for e in hist.values() if e.get("dest") == ok][0]
        check("cache_written", bool(cached.get("verified_mtime_ns")), str(cached)[:160])
        guard2 = NoHash(real_sha256)
        dlm.hashlib.sha256 = guard2
        _write_history(os.environ["BOTINOK_DOWNLOAD_HISTORY"], [cached])
        out = str(tm.call_tool("web", {"action": "downloads", "verify": "true"}))
        check("cached_no_rehash", guard2.calls == 0, f"вызовов sha256: {guard2.calls}")
        cached_reason = dlm.verify(dlm._load(None) and cached, deep=True)[1]
        check("cached_ok", "сверен ранее" in cached_reason, cached_reason)

        print("\n[5] record(completed) помечает файл проверенным")
        dlm.hashlib.sha256 = real_sha256
        dlm.record(None, "https://x/new", ok, "completed", total=4096, sha256=ok_sha)
        fresh = dlm.find(None, "https://x/new", ok)
        check("record_sets_verified", bool(fresh.get("verified_mtime_ns")), str(fresh)[:160])
        guard3 = NoHash(real_sha256)
        dlm.hashlib.sha256 = guard3
        _write_history(os.environ["BOTINOK_DOWNLOAD_HISTORY"], [fresh])
        out = str(tm.call_tool("web", {"action": "downloads", "verify": "true"}))
        check("fresh_download_not_rehashed", guard3.calls == 0, f"вызовов sha256: {guard3.calls}")

        print("\n[6] предварительная проверка «уже скачано» не хеширует")
        guard4 = NoHash(real_sha256)
        dlm.hashlib.sha256 = guard4
        _write_history(os.environ["BOTINOK_DOWNLOAD_HISTORY"],
                       [_entry("https://x/ok", ok, 4096, "0" * 64)])
        out = str(tm.call_tool("web", {"action": "download", "url": "https://x/ok",
                                       "output_path": ok}, session_path=tmp))
        check("precheck_no_hash", guard4.calls == 0, f"вызовов sha256: {guard4.calls}")
        check("precheck_already_downloaded", "Уже скачано ранее" in out, out[:160])

        print("\n[7] sha256_file читает потоком и корректен")
        dlm.hashlib.sha256 = real_sha256
        big = make_file("big.bin", os.urandom(3 * 1024 * 1024))
        check("sha256_file_correct",
              dlm.sha256_file(big) == hashlib.sha256(open(big, "rb").read()).hexdigest())
        check("web_sha256_helper_correct",
              __import__("tools.web", fromlist=["_sha256_file"])._sha256_file(big)
              == dlm.sha256_file(big))
    finally:
        dlm.hashlib.sha256 = real_sha256
        if old_env is None:
            os.environ.pop("BOTINOK_DOWNLOAD_HISTORY", None)
        else:
            os.environ["BOTINOK_DOWNLOAD_HISTORY"] = old_env
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ ИСТОРИЯ ЗАГРУЗОК: РЕГРЕССИЙ НЕТ")
    return 0


def test_downloads_history() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
