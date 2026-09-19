#!/usr/bin/env python3
"""
Smoke-тест панели «Производительность»: живые метрики, русские подписи,
профили сервера, трафик «АПИ отдано / АПИ принято», детектор зависаний.

Запуск: venv/bin/python -u tests/test_perf_panel.py
"""

import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Static  # noqa: E402

from core.textual_app import BotinokTextualApp  # noqa: E402
import core.net_meter as net_meter  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _panel(app) -> str:
    return str(app.query_one("#stats_rows", Static).content)


def test_traffic_meter() -> None:
    """Прямой замер трафика на локальном HTTP-сервере (loopback)."""
    import http.server
    import socketserver

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            self.rfile.read(n)
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        import requests  # noqa: F401
        net_meter.reset_turn()
        import requests as rq
        rq.post(f"http://127.0.0.1:{srv.server_address[1]}/api/chat",
                json={"messages": [1, 2, 3, 4]}, timeout=5)
        time.sleep(0.05)
        snap = net_meter.snapshot()
        check("meter_sent", snap["sent_turn"] > 0, f"snap={snap}")
        check("meter_recv", snap["recv_turn"] > 0, f"snap={snap}")
        check("meter_requests", snap["req_turn"] == 1, f"snap={snap}")
        total_sent = snap["sent_total"]
        net_meter.reset_turn()
        after = net_meter.snapshot()
        check("meter_reset_turn", after["sent_turn"] == 0 and after["sent_total"] == total_sent,
              f"after={after}")
        check("format_bytes", net_meter.format_bytes(2_500_000).endswith("МБ"))

        # Паузы не должны занижать среднюю скорость приёма: интервал в 3 с
        # без данных исключается из знаменателя.
        nm = net_meter
        with nm._lock:
            nm._recv_samples.clear()
        b = time.time() - 5.0
        with nm._lock:
            nm._recv_samples.extend([(b, 0), (b + 0.5, 1000),
                                     (b + 1.0, 2000), (b + 4.0, 2000)])
        rate = nm.recv_rate(window=10.0)
        check("recv_rate_ignores_pause", 1500 < rate < 2500, f"rate={rate}")
    finally:
        srv.shutdown()


async def main_async() -> int:
    print("=" * 70)
    print("Performance panel smoke-test")
    print("=" * 70)

    test_traffic_meter()

    app = BotinokTextualApp()
    async with app.run_test(size=(150, 55)) as pilot:  # noqa: F841
        now = time.time()
        app.set_model_info("qwen3.5:9b", server="ollama")
        app.stats_data.update({
            "status": "Generating...", "elapsed": 12.0,
            "session_ctx": 5600, "session_ctx_max": 32768, "last_req_ctx": 7000,
            "vram": "Qwen: 6.20GB", "retries": 0,
        })
        app.is_streaming = True
        app._start_time = now - 12.0
        app._stream_started_at = now - 5.0
        app._first_token_at = now - 4.0
        app._stream_active_time = 1.0  # 160 Б за 1 с активной генерации
        app._phase_started_at = now - 3.0
        app._stream_thinking = "м" * 120
        app._stream_content = "о" * 40
        app._last_tool_content = ""
        app._last_chunk_time = now - 0.3
        app.update_stats_display()
        await asyncio.sleep(0.2)

        txt = _panel(app)
        check("ru_server", "Ollama (локальный)" in txt, txt)
        check("ru_status", "Модель" in txt and ("думает" in txt or "печатает" in txt), txt)
        check("live_thinking", "Размышляет" in txt and "120 Б" in txt, txt)
        check("live_response", "Написал ответ" in txt and "40 Б" in txt, txt)
        check("live_speed", "Б/с" in txt, txt)
        check("no_english", "TTFT" not in txt and "TPS" not in txt and "SessionCtx" not in txt, txt)
        check("ollama_vram", "Видеопамять" in txt, txt)
        check("ollama_tool_draft", "Готовит команду" in txt, txt)
        check("traffic_rows", "АПИ отдано" in txt and "АПИ принято" in txt, txt)

        # Сырые байты: каждый байт двигает число (без округления, скрывающего рост).
        net_meter.reset_turn()
        net_meter.add_sent(3)
        net_meter.add_recv(7)
        net_meter.add_request()
        app.update_stats_display()
        await asyncio.sleep(0.2)
        txt = _panel(app)
        check("bytes_sent_raw", "3 Б" in txt, txt)
        check("bytes_recv_raw", "7 Б" in txt, txt)

        # Живая скорость текста: 160 Б за 1 с активной генерации.
        check("speed_positive", "160.0 Б/с" in txt, txt)

        # Пауза не занижает скорость: первый токен давно, но активное время 1 с.
        app._first_token_at = time.time() - 600.0
        app.update_stats_display()
        await asyncio.sleep(0.2)
        check("text_speed_ignores_pause", "160.0 Б/с" in _panel(app), _panel(app))

        # Зависание: молчание > 30 с — красный статус и подсказка.
        app._last_chunk_time = time.time() - 45.0
        app.update_stats_display()
        await asyncio.sleep(0.2)
        txt = _panel(app)
        check("hang_silence", "долго молчит" in txt, txt)
        check("hang_hint", "Похоже, зависло" in txt, txt)

        # Удержание сессии: растущий счётчик ожидания сервера + попытки.
        app.stats_data["retries"] = 2
        app.stats_data["retry_wait"] = 15.0
        app.update_stats_display()
        await asyncio.sleep(0.2)
        txt = _panel(app)
        check("retries_row", "Ждём сервер" in txt and "15 с" in txt and "попыток: 2" in txt, txt)

        # Профиль OpenAI: строки памяти и черновика команды не показываем.
        app.set_model_info("gpt-x", server="openai")
        app.update_stats_display()
        await asyncio.sleep(0.2)
        txt = _panel(app)
        check("openai_server", "OpenAI-совместимый" in txt, txt)
        check("openai_hides_vram", "Видеопамять" not in txt, txt)
        check("openai_hides_draft", "Готовит команду" not in txt, txt)
        check("openai_keeps_traffic", "АПИ отдано" in txt, txt)

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
    else:
        print("✅ PERFORMANCE PANEL SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(1 if FAILURES else 0)


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
