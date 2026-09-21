#!/usr/bin/env python3
"""
Тесты медиа-инструментов (audio/vision): локальный путь вместо URL и
наследование прокси из net_config.

Локальный мини-прокси отвечает на absolute-URI GET валидными WAV/JPEG, что
позволяет проверить реальную загрузку через прокси без внешней сети.

Запуск: venv/bin/python -u tests/test_audio_local.py
"""

import http.server
import io
import os
import socketserver
import sys
import tempfile
import threading
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import net_config as net  # noqa: E402
from tools import audio as audio_tool  # noqa: E402
from tools import vision as vision_tool  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def make_wav(path: str) -> str:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)  # 0.1 c тишины
    return path


def tiny_jpeg() -> bytes:
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (16, 16), (20, 90, 160)).save(buf, "JPEG")
        return buf.getvalue()
    except Exception:
        return b"\xff\xd8\xff\xe0" + b"J" * 200


JPEG = tiny_jpeg()
WAV_BYTES = None


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """Мини-прокси: на absolute-URI GET отдаёт WAV (если .wav) или JPEG."""
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        ProxyHandler.seen.append(self.path)
        body = WAV_BYTES if self.path.endswith(".wav") else JPEG
        ctype = "audio/wav" if self.path.endswith(".wav") else "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_proxy():
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), ProxyHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def main() -> int:
    global WAV_BYTES
    print("=" * 70)
    print("Media (audio/vision) smoke-test")
    print("=" * 70)

    work = tempfile.mkdtemp(prefix="botinok_media_")
    wav_path = make_wav(os.path.join(work, "tone.wav"))
    WAV_BYTES = open(wav_path, "rb").read()

    # --- определение удалённости ---
    check("remote_http", audio_tool._looks_like_remote("http://x/y.mp3") is True)
    check("remote_local_path", audio_tool._looks_like_remote("/tmp/y.mp3") is False)
    check("remote_file_scheme", audio_tool._looks_like_remote("file:///tmp/y.mp3") is False)

    # --- audio принимает локальный путь в `url` (а не упирается в протокол) ---
    res = audio_tool.execute(url=wav_path)
    check("audio_local_via_url", isinstance(res, dict) and bool(res.get("audio_data")),
          str(res)[:200])
    res = audio_tool.execute(url="file://" + wav_path)
    check("audio_file_scheme_via_url", isinstance(res, dict) and bool(res.get("audio_data")),
          str(res)[:200])
    res = audio_tool.execute(url="/no/such/file.mp3")
    check("audio_missing_file_message",
          isinstance(res, str) and "not found" in res.lower() and "protocol" not in res.lower(),
          str(res)[:200])

    # --- наследование прокси ---
    session = tempfile.mkdtemp(prefix="botinok_media_sess_")
    os.makedirs(os.path.join(session, "project"), exist_ok=True)
    httpd, proxy_url = start_proxy()
    try:
        net.set_proxy(proxy_url, session, scope="session")
        check("audio_proxy_inherited",
              audio_tool._net_proxy(session) == proxy_url, str(audio_tool._net_proxy(session)))
        check("vision_proxy_inherited",
              vision_tool._net_proxy(session) == proxy_url, str(vision_tool._net_proxy(session)))

        data, mime = audio_tool._download_audio("http://example.test/clip.wav", 10, session)
        check("audio_download_via_proxy",
              mime == "audio/wav" and data[:4] == b"RIFF", f"mime={mime} len={len(data)}")

        img, imime = vision_tool._download_image("http://example.test/pic.jpg", 10, session)
        check("vision_download_via_proxy",
              imime.startswith("image/") and img[:3] == b"\xff\xd8\xff",
              f"mime={imime} len={len(img)}")

        check("proxy_actually_used",
              any(p.startswith("http://example.test/") for p in ProxyHandler.seen),
              str(ProxyHandler.seen[:3]))
    finally:
        httpd.shutdown()
        httpd.server_close()
        net.clear(session, scope="session")

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ MEDIA SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
