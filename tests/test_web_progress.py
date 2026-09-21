#!/usr/bin/env python3
"""
Тесты живого прогресса инструмента web (для панели «Инструменты»).

Проверяем, что web реально зовёт progress_callback: поиск (найдено N),
загрузка httpx (скорость/прогресс), разбор readout aria2c, поиск картинок.

Запуск: venv/bin/python -u tests/test_web_progress.py
"""

import functools
import http.server
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import web as _web  # noqa: E402

FAILURES = []
TINY_JPEG = b"\xff\xd8\xff\xe0" + b"J" * 5000


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/img.jpg":
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(TINY_JPEG)))
            self.end_headers()
            self.wfile.write(TINY_JPEG)
        elif path == "/gallery":
            html = ('<!doctype html><html><body>'
                    '<img src="/img.jpg" alt="ok">'
                    '<img src="/missing" alt="bad">'
                    '</body></html>')
            self._send(html.encode(), "text/html; charset=utf-8")
        elif path == "/file.bin":
            body = b"x" * 20000
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(b"nope", "text/plain", status=404)

    def _send(self, body, ctype, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def main() -> int:
    print("=" * 70)
    print("web progress smoke-test")
    print("=" * 70)

    # --- regex readout aria2c ---
    line = "[#1a2b3c 1.2MiB/3.4MiB(35%) CN:4 DL:850KiB ETA:3s]"
    m = _web._ARIA_READOUT_RE.search(line)
    check("aria_readout_parsed", bool(m), line)
    if m:
        check("aria_readout_fields", (m.group(1), m.group(2), m.group(3), m.group(4))
              == ("1.2MiB", "3.4MiB", "35", "850KiB"),
              f"{m.groups()}")

    # --- _emit_progress совместим с cb(text) и cb(text, force=) ---
    got = []
    _web._emit_progress(lambda t, force=False: got.append((t, force)), "x", True)
    check("emit_force", got == [("x", True)], str(got))
    got2 = []
    _web._emit_progress(lambda t: got2.append(t), "y")
    check("emit_plain", got2 == ["y"], str(got2))

    # --- поиск: сообщает число найденных ---
    saved_fetch, saved_parse = _web._fetch, _web._parse_ddg_html
    _web._fetch = lambda *a, **k: (b"<html></html>", "http://x", "text/html", 200, False)
    _web._parse_ddg_html = lambda text, n: [
        {"title": "A", "url": "https://e1", "snippet": ""},
        {"title": "B", "url": "https://e2", "snippet": ""},
    ]
    events = []
    try:
        _web._action_search("q", None, 5, 1000, 5, None, None,
                            lambda *a, **k: events.append(a[0] if a else ""))
    finally:
        _web._fetch, _web._parse_ddg_html = saved_fetch, saved_parse
    check("search_emits_count", any("найдено 2" in e for e in events), str(events))

    httpd, base = serve()
    tmp = tempfile.mkdtemp(prefix="botinok_prog_")
    try:
        # --- загрузка httpx: прогресс + финал ---
        events2 = []
        ok, err = _web._httpx_download(f"{base}/file.bin", os.path.join(tmp, "f.bin"),
                                       None, 10, None, None,
                                       lambda *a, **k: events2.append(a[0] if a else ""))
        check("httpx_download_ok", ok, err)
        check("httpx_emits_progress", any(e.startswith("⬇") for e in events2), str(events2))
        check("httpx_emits_final", any("✅" in e for e in events2), str(events2))
        check("httpx_speed_in_text", any("/s" in e for e in events2), str(events2))

        # --- поиск картинок: сообщает живых ---
        events3 = []
        body, prov, nxt, meta = _web._action_images(
            None, f"{base}/gallery", None, 10, 200000, 2, None, None,
            progress_callback=lambda *a, **k: events3.append(a[0] if a else ""))
        check("images_emits", any("живых" in e for e in events3) or meta.get("working"),
              str(events3))
        check("images_found_one", meta.get("working", 0) >= 1, str(meta))
    finally:
        httpd.shutdown()
        httpd.server_close()

    # --- панель: detail сохраняется/обновляется ---
    from core.textual_app import BotinokTextualApp

    class Stub:
        _fmt_kb = staticmethod(BotinokTextualApp._fmt_kb)
        _fmt_dur = staticmethod(BotinokTextualApp._fmt_dur)
        _tool_state = BotinokTextualApp._tool_state
        _truncate = staticmethod(BotinokTextualApp._truncate)
        _rich_escape = BotinokTextualApp._rich_escape
        _build_tool_title = BotinokTextualApp._build_tool_title

        def update_stats_display(self):
            pass
    s = Stub()
    s.active_tools = [{"name": "web", "query": "q", "status": "running",
                       "size_kb": 0, "detail": "", "start_time": 0}]
    s._tools_dirty = False
    BotinokTextualApp.update_tool_detail(s, "web", "⬇ 1.2 MB/s")
    check("panel_detail_set", s.active_tools[0]["detail"] == "⬇ 1.2 MB/s"
          and s._tools_dirty is True, str(s.active_tools[0]))
    s._tools_dirty = False
    BotinokTextualApp.update_tool_activity(s, "web", "completed", 12.0, "", "✅ готово")
    check("panel_detail_via_update", s.active_tools[0]["detail"] == "✅ готово", str(s.active_tools[0]))

    # --- «состояние» для правого края: detail, иначе время ---
    import time as _t
    check("state_detail", BotinokTextualApp._tool_state(
        Stub, {"detail": "🔎 найдено 8", "status": "running", "start_time": _t.time()}) == "🔎 найдено 8")
    check("state_running_timer", BotinokTextualApp._tool_state(
        Stub, {"detail": "", "status": "running", "start_time": _t.time() - 5}).startswith("⏱"))
    check("state_done_duration", BotinokTextualApp._tool_state(
        Stub, {"detail": "", "status": "completed", "start_time": 100, "end_time": 103}) == "3с")
    check("state_done_size", BotinokTextualApp._tool_state(
        Stub, {"detail": "", "status": "completed", "size_kb": 0.66,
               "start_time": 100, "end_time": 103}) == "0.66 KB · 3с")
    check("state_done_detail_and_size", BotinokTextualApp._tool_state(
        Stub, {"detail": "✅ скачано", "status": "completed", "size_kb": 53.9,
               "start_time": 100, "end_time": 101}) == "✅ скачано · 53.90 KB")
    check("state_no_size_dupe", BotinokTextualApp._tool_state(
        Stub, {"detail": "✅ 0.66 KB", "status": "completed", "size_kb": 0.66,
               "start_time": 100, "end_time": 101}) == "✅ 0.66 KB")
    check("state_empty", BotinokTextualApp._tool_state(
        Stub, {"detail": "", "status": "completed", "start_time": 0, "end_time": 0}) == "")

    # --- заголовок всегда одной строкой и не длиннее панели ---
    long_name = {"name": "session_memory_very_long_name", "status": "completed",
                 "detail": "application/json очень длинное состояние прогресса",
                 "size_kb": 12.5, "start_time": 0, "end_time": 0}
    import re as _re
    s2 = Stub()
    for width in (120, 80, 60, 40):
        title = BotinokTextualApp._build_tool_title(s2, long_name, width)
        plain = _re.sub(r"\[/?[^\]]*\]", "", title)
        check(f"title_fits_{width}", len(plain) <= max(16, width - 4) + 1,
              f"len={len(plain)} w={width}: {plain}")

    # --- legacy-обёртки доносят progress_callback до web ---
    from tools import web_search, open_url, web_extract

    captured = {}
    saved_exec = _web.execute

    def fake_exec(**kw):
        captured.update(kw)
        return "ok"
    _web.execute = fake_exec
    try:
        seen = []
        web_search.ddg_search("q", session_path="/tmp", progress_callback=lambda *a, **k: seen.append(1))
        check("wrapper_web_search_forwards", "progress_callback" in captured, str(captured.keys()))
        captured.clear()
        open_url.open_url("example.com", session_path="/tmp", progress_callback=lambda *a, **k: None)
        check("wrapper_open_url_forwards", "progress_callback" in captured, str(captured.keys()))
        captured.clear()
        web_extract.execute("http://x", progress_callback=lambda *a, **k: None)
        check("wrapper_web_extract_forwards", "progress_callback" in captured, str(captured.keys()))
    finally:
        _web.execute = saved_exec

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ WEB PROGRESS SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
