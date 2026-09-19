#!/usr/bin/env python3
"""
Интеграционный тест: имитация потока модели + прерывание по Esc.

Поднимаем локальный mock-сервер, который льёт токены бесконечно, запускаем
реальный `ask_ollama_textual` (headless) и проверяем ОБА пути:
  - Backend=ollama  → /api/chat (NDJSON);
  - Backend=openai  → /v1/chat/completions (SSE) — как в реальной работе.

Для каждого: дождаться стрима, имитировать Esc и требовать немедленный обрыв
(< 2 c) и разрыв соединения на сервере.

Запуск: venv/bin/python -u tests/test_escape_stream.py
"""

import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.textual_integration as ti  # noqa: E402
from core.textual_app import BotinokTextualApp  # noqa: E402
from core.session_manager import SessionManager  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class MockModel:
    """Общий сервер для Ollama NDJSON и OpenAI SSE, с флагом разрыва."""

    def __init__(self):
        self.disconnected = threading.Event()
        self.got_request = threading.Event()
        self.hang = False  # если True — сервер не отвечает (висит без заголовков)
        self._httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), self._handler())
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass

    def _handler(self):
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _json(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._json({"models": []})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    self.rfile.read(n)
                except Exception:
                    pass
                outer.got_request.set()
                if outer.hang:
                    # Сервер «завис»: соединение принято, ответ не отдаётся.
                    time.sleep(3600)
                    return
                openai = self.path.endswith("/v1/chat/completions")
                self.send_response(200)
                self.send_header("Content-Type",
                                 "text/event-stream" if openai else "application/x-ndjson")
                self.end_headers()
                try:
                    i = 0
                    big = "размышление " * 40  # ~480 символов за чанк — грузит UI
                    while True:
                        i += 1
                        if openai:
                            chunk = {"choices": [{"delta": {"reasoning_content": f"{big}{i} "},
                                                  "finish_reason": None}]}
                            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                        else:
                            chunk = {"message": {"role": "assistant",
                                                 "thinking": f"{big}{i} "}, "done": False}
                            self.wfile.write((json.dumps(chunk) + "\n").encode())
                        self.wfile.flush()
                        time.sleep(0.0)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    outer.disconnected.set()

        return H


def run_case(backend: str, mock: MockModel, hang: bool = False) -> None:
    print(f"--- Backend={backend}{' (зависший сервер)' if hang else ''} ---")
    mock.disconnected.clear()
    mock.got_request.clear()
    mock.hang = hang
    sm = SessionManager()
    sm.config.set("Ollama", "BaseUrl", mock.url)
    sm.config.set("Ollama", "Backend", backend)
    session = sm.create_session(f"esc-stream-{backend}")

    orig_sm = ti.SessionManager
    ti.SessionManager = lambda: sm
    orig_run = BotinokTextualApp.run
    BotinokTextualApp.run = lambda self, *a, **k: orig_run(self, headless=True, size=(120, 40))

    from core.shell_session import TextualAppRegistry
    TextualAppRegistry.clear()

    messages = [{"role": "user", "content": "привет"}]

    def run_agent():
        try:
            ti.ask_ollama_textual("test-model", messages, session, num_ctx=4096,
                                  initial_prompt="привет")
        except Exception as e:
            print("   agent error:", f"{type(e).__name__}: {e}")

    th = threading.Thread(target=run_agent, daemon=True)
    th.start()

    app = None
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            from core.shell_session import TextualAppRegistry
            app = TextualAppRegistry.get_app()
            if app is not None:
                break
        except Exception:
            pass
        time.sleep(0.1)
    check(f"{backend}_app_started", app is not None)
    if app is None:
        ti.SessionManager = orig_sm
        BotinokTextualApp.run = orig_run
        return

    # --- Зависший сервер: соединение принято, ответа нет. Esc должен вернуть
    # управление немедленно, не дожидаясь таймаута запроса. ---
    if hang:
        got = mock.got_request.wait(timeout=8)
        check(f"{backend}_request_in_flight", got)
        t0 = time.time()
        try:
            app.call_from_thread(app.request_stop)
        except Exception:
            app.request_stop()
        returned = False
        while time.time() - t0 < 3:
            if str(app.stats_data.get("status", "")) in ("Ready", "Готов к работе"):
                returned = True
                break
            time.sleep(0.05)
        dt = time.time() - t0
        check(f"{backend}_hang_esc_returns", returned,
              f"status={app.stats_data.get('status')!r}")
        check(f"{backend}_hang_esc_fast", dt < 2.0, f"{dt:.2f}s")
        mock.hang = False
        try:
            app.call_from_thread(app.exit)
        except Exception:
            pass
        th.join(timeout=5)
        ti.SessionManager = orig_sm
        BotinokTextualApp.run = orig_run
        return

    deadline = time.time() + 10
    while time.time() < deadline and not getattr(app, "is_streaming", False):
        time.sleep(0.05)
    check(f"{backend}_stream_started", getattr(app, "is_streaming", False))
    time.sleep(0.4)

    t0 = time.time()
    try:
        app.call_from_thread(app.request_stop)   # имитация Esc
    except Exception:
        app.request_stop()

    aborted = False
    while time.time() - t0 < 6:
        if not getattr(app, "is_streaming", False):
            aborted = True
            break
        time.sleep(0.05)
    dt = time.time() - t0
    check(f"{backend}_stream_aborted", aborted,
          f"is_streaming={getattr(app, 'is_streaming', False)} dt={dt:.2f}")
    check(f"{backend}_aborted_fast", dt < 2.0, f"{dt:.2f}s")
    time.sleep(0.3)
    check(f"{backend}_server_disconnect", mock.disconnected.is_set(),
          "сервер не увидел разрыв")

    try:
        app.call_from_thread(app.exit)
    except Exception:
        pass
    th.join(timeout=5)
    ti.SessionManager = orig_sm
    BotinokTextualApp.run = orig_run


def main() -> int:
    print("=" * 70)
    print("Escape during live stream (mock model) smoke-test")
    print("=" * 70)

    os.environ["BOTINOK_SESSIONS_DIR"] = tempfile.mkdtemp(prefix="botinok_escstream_")
    mock = MockModel()
    try:
        run_case("ollama", mock)
        run_case("openai", mock)
        run_case("openai", mock, hang=True)
    finally:
        mock.stop()

    print("=" * 70)
    if FAILURES:
        print(f"Провалы: {FAILURES}")
        os._exit(1)
    print("✅ ESCAPE DURING STREAM SMOKE-ТЕСТ ПРОЙДЕН")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
