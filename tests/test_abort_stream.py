#!/usr/bin/env python3
"""
Тест прерывания стрима модели.

Проверяем, что `_abort_stream` реально рвёт соединение: сервер видит разрыв
(BrokenPipe) и перестаёт писать — значит Ollama/LLM прекратит генерацию, а не
продолжит считать впустую.
"""

import http.server
import json
import os
import socketserver
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from core.textual_integration import _abort_stream  # noqa: E402

FAILURES = []
DISCONNECTED = threading.Event()


class StreamHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for i in range(400):
                data = (json.dumps({"message": {"content": f"tok{i}"}}) + "\n").encode()
                self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()
                time.sleep(0.02)
        except (BrokenPipeError, ConnectionResetError, OSError):
            DISCONNECTED.set()


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    print("=" * 70)
    print("Abort stream smoke-test")
    print("=" * 70)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), StreamHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/stream"

    response = requests.get(url, stream=True, timeout=10)
    got = {"n": 0, "done": False}

    def reader():
        try:
            for _ in response.iter_lines():
                got["n"] += 1
        except Exception:
            pass
        got["done"] = True

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    time.sleep(0.6)
    check("stream_started", got["n"] > 0, str(got["n"]))

    t0 = time.time()
    _abort_stream(response)
    th.join(timeout=3)
    dt = time.time() - t0

    check("reader_stopped", got["done"] and not th.is_alive(), f"alive={th.is_alive()}")
    check("reader_stopped_fast", dt < 3, f"{dt:.2f}s")
    time.sleep(0.3)
    check("server_saw_disconnect", DISCONNECTED.is_set(),
          "сервер не увидел разрыв — соединение не порвано")

    httpd.shutdown()
    httpd.server_close()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ ABORT STREAM SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
