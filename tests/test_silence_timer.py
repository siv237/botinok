#!/usr/bin/env python3
"""
Тест: «Модель молчит» считается с момента остановки видимых счётчиков
(байты идут — не «зависло»), и панельный счётчик «Выжато» (сколько контекста
сжато триммом/ресетом).

Запуск: venv/bin/python -u tests/test_silence_timer.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Static  # noqa: E402

from core.textual_app import BotinokTextualApp  # noqa: E402
import core.textual_integration as ti  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _panel(app) -> str:
    return str(app.query_one("#stats_rows", Static).content)


def test_compression_counter():
    before = ti.get_compression_stats()
    msgs = [{"role": "system", "content": "SYS"}]
    for i in range(60):
        msgs.append({"role": "user", "content": f"q{i} " + "д" * 4000})
    trimmed = ti._prepare_messages_for_ollama(_StubSM(), "sess", msgs, num_ctx=2000)
    after = ti.get_compression_stats()
    check("trim_counted", len(trimmed) < len(msgs)
          and after["trims"] == before["trims"] + 1
          and after["tokens"] > before["tokens"], f"after={after}")

    sm = _StubSM()
    hist = [{"role": "system", "content": "ID"},
            {"role": "user", "content": "задача"},
            {"role": "assistant", "content": "работа"}]
    orig_is, orig_once = ti.is_openai_backend, ti.chat_once
    ti.is_openai_backend = lambda sm: True
    ti.chat_once = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("offline"))
    try:
        ti._ollama_summarize_and_reset_context(sm, "m", "sess", hist, 262144, reason="t")
    finally:
        ti.is_openai_backend, ti.chat_once = orig_is, orig_once
    after2 = ti.get_compression_stats()
    check("reset_counted", after2["resets"] == after["resets"] + 1
          and after2["tokens"] > after["tokens"], f"after2={after2}")


class _StubConfig:
    def get(self, section, option, fallback=None):
        return fallback

    def getboolean(self, section, option, fallback=None):
        return fallback


class _StubSM:
    def __init__(self):
        self.config = _StubConfig()
        self.artifacts = {}

    def save_artifact(self, session_path, name, data):
        self.artifacts[name] = data
        return f"{session_path}/artifacts/{name}"

    def load_prompt(self, session_path, name, **kw):
        return f"[{name}]"


async def main_async() -> int:
    print("== счётчик «Выжато» ==")
    test_compression_counter()

    print("== таймер молчания по видимым счётчикам ==")
    app = BotinokTextualApp()
    async with app.run_test(size=(150, 60)) as pilot:
        now = time.time()
        app.set_model_info("qwen3.5:9b", server="openai")
        app.stats_data.update({"status": "Generating...", "elapsed": 60.0,
                               "session_ctx": 5000, "session_ctx_max": 32768,
                               "compressed_tokens": 12345, "compress_trims": 4,
                               "compress_resets": 1})
        app.is_streaming = True
        app._start_time = now - 60.0
        app._stream_started_at = now - 60.0
        app._phase_started_at = now - 60.0
        app._stream_thinking = "м" * 5000
        app._stream_content = ""
        app._last_tool_content = ""
        # байты перестали приходить 70 с назад, счётчик не растёт:
        app._last_chunk_time = now - 70.0
        app._visible_total = 5000
        app._visible_at = now - 70.0
        app.update_stats_display()
        await asyncio.sleep(0.2)
        txt = _panel(app)
        check("stalled_shows_hang", "зависло" in txt and "70.1 с" in txt.replace("70.0", "70.1") or "долго молчит" in txt, txt[-400:])
        check("compressed_row", "Память сжималась" in txt and "12345" in txt and "поджал 4" in txt, txt[-400:])

        # счётчик снова растёт (циферки бегут) — молчание обнуляется,
        # несмотря на старый _last_chunk_time
        app._stream_thinking = "м" * 6000
        app._last_chunk_time = now - 70.0
        app.update_stats_display()
        await asyncio.sleep(0.2)
        txt2 = _panel(app)
        check("growing_counters_not_hung", "зависло" not in txt2, txt2[-400:])
        check("growing_shows_norm", "норма" in txt2, txt2[-400:])
    return 0


def main() -> int:
    print("=" * 70)
    print("Silence timer & compression counter")
    print("=" * 70)
    rc = asyncio.run(main_async())
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ SILENCE TIMER / COMPRESSED ТЕСТ ПРОЙДЕН")
    return rc


if __name__ == "__main__":
    sys.exit(main())
