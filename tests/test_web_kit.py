#!/usr/bin/env python3
"""
Smoke-тест единого веб-добывателя (`tools/web.py`) и legacy-обёрток.

Поднимаем локальный HTTP-сервер (без сети) и проверяем:
  * action=json (проекция и сводка), open, extract, download, auto-роутинг;
  * харнес (_meta / provenance / Совет / Следующие шаги);
  * тело ответа сервера пробрасывается на ошибке (без доменной конкретики);
  * блокировку небезопасного jq;
  * регрессию curl: jq_filter больше не даёт TypeError;
  * парсер результатов поиска (без обращения к DuckDuckGo);
  * гейт записи вне сессии для web.

Запуск: venv/bin/python -u tests/test_web_kit.py
"""

import hashlib
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import curl as curl_tool  # noqa: E402
from tools import vision as vision_tool  # noqa: E402
from tools import web as web_tool  # noqa: E402
from tools import web_extract as web_extract_tool  # noqa: E402
from tools import web_search as web_search_tool  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


try:
    from PIL import Image as _PILImage
    from io import BytesIO as _BytesIO
    _img = _PILImage.new("RGB", (16, 16), (30, 120, 200))
    _buf = _BytesIO()
    _img.save(_buf, format="JPEG")
    TINY_JPEG = _buf.getvalue()
except Exception:
    TINY_JPEG = b""

PAGE_HTML = """<!doctype html><html><head>
<title>Demo Page</title>
<meta name="description" content="demo description">
<meta property="og:image" content="/og/promo.jpg">
</head><body>
<nav>menu</nav>
<main>
<img src="/static/logo.svg" alt="logo">
<img data-src="/gallery/lazy-photo.jpg" alt="ленивое фото">
<h1>Заголовок статьи</h1>
<p>Первый абзац текста страницы.</p>
<h2>Раздел</h2>
<p>Второй абзац с <a href="/other">ссылкой</a>.</p>
<table><thead><tr><th>Колонка</th><th>Число</th></tr></thead>
<tbody><tr><td>Значение</td><td>24</td></tr></tbody></table>
<img src="/img/pic.png" alt="картинка">
</main>
<footer>подвал</footer></body></html>"""

DATA_JSON = json.dumps({
    "zone": "Example/Zone",
    "daily": {"time": ["2026-09-18", "2026-09-19"], "temperature": [24, 25]},
})

DDG_FIXTURE = """<div class="result">
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x">Example A</a>
<a class="result__snippet">Сниппет A</a></div>
<div class="result">
<a class="result__a" href="https://example.org/b">Example B</a>
<a class="result__snippet">Сниппет B</a></div>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/page":
            self._send(PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/data.json":
            self._send(DATA_JSON.encode("utf-8"), "application/json")
        elif path == "/encoded":
            # 400, если значение содержит процент-экранирование (%2F);
            # 200 — если оно декодировано (проверка беззнаковой правки).
            if "%2f" in self.path.lower():
                self._send(b'{"error":true,"reason":"invalid value"}',
                           "application/json", status=400)
            else:
                self._send(DATA_JSON.encode("utf-8"), "application/json")
        elif path == "/badparam":
            self._send(b'{"error":true,"reason":"bad param"}',
                       "application/json", status=400)
        elif path == "/drop":
            # 400, пока присутствует параметр "bad" (сервер называет его).
            if "bad=" in self.path:
                self._send(b'{"error":true,"reason":"invalid bad"}',
                           "application/json", status=400)
            else:
                self._send(DATA_JSON.encode("utf-8"), "application/json")
        elif path == "/namedparam":
            # 400 с причиной, называющей query-параметр "period".
            if "period=current" in self.path:
                self._send(DATA_JSON.encode("utf-8"), "application/json")
            else:
                self._send(b'{"error":true,"reason":"invalid period"}',
                           "application/json", status=400)
        elif path == "/file.bin":
            self._send(b"\x89PNG\r\n\x1a\n" + b"0" * 64, "application/octet-stream")
        elif path == "/big.bin":
            # Больше старого лимита curl (256000) — проверяем отсутствие обрезки.
            self._send(b"\xff\xd8\xff" + b"A" * 300_000, "application/octet-stream")
        elif path == "/stub.jpg":
            # 200, но вместо картинки HTML-заглушка (rate-limit/капча).
            self._send(b"<!doctype html><html><body>Wikimedia Error</body></html>",
                       "text/html; charset=utf-8")
        elif path == "/img.jpg":
            # 403 без браузерного User-Agent — как CDN, которые режут ботов.
            ua = self.headers.get("User-Agent", "")
            if not ua.startswith("Mozilla"):
                self._send(b"forbidden", "text/plain", status=403)
            else:
                self._send(TINY_JPEG, "image/jpeg")
        elif path == "/missing":
            self._send(b"nope", "text/plain", status=404)
        else:
            self._send(b"unknown", "text/plain", status=404)


def start_server():
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def main() -> int:
    print("=" * 70)
    print("Web kit smoke-test")
    print("=" * 70)
    os.environ["BOTINOK_DOWNLOAD_HISTORY"] = os.path.join(
        tempfile.mkdtemp(prefix="botinok_dl_"), "history.json")
    httpd, base = start_server()
    session = tempfile.mkdtemp(prefix="botinok_web_")
    try:
        # help
        h = web_tool.execute(action="help")
        check("help_text", "единый добыватель" in h and "action=json" in h)

        # json + jq
        out = web_tool.execute(action="json", url=f"{base}/data.json", jq=".daily.temperature")
        check("json_jq_projected", "projected" in out and "24" in out and "25" in out, out[:200])

        # json без jq -> сводка + next actions
        out = web_tool.execute(action="json", url=f"{base}/data.json")
        check("json_summary", "Объект" in out and "Следующие шаги" in out, out[:200])

        # open
        out = web_tool.execute(action="open", url=f"{base}/page")
        check("open_readable", "Заголовок статьи" in out and "Первый абзац" in out, out[:200])
        check("open_harness", "provenance=readable" in out and "Совет:" in out)

        # extract
        out = web_tool.execute(action="extract", url=f"{base}/page",
                               extract=["links", "tables"])
        check("extract_links", "other" in out, out[:300])
        check("extract_tables", "Значение" in out and "provenance=extracted" in out, out[:300])
        # Фотографии должны идти перед иконками/логотипами.
        imgs = web_tool.execute(action="extract", url=f"{base}/page", extract=["images"])
        check("image_ranking", imgs.find("pic.png") != -1 and
              (imgs.find("pic.png") < imgs.find("logo.svg")), imgs[:300])

        # download
        out = web_tool.execute(action="download", url=f"{base}/file.bin", session_path=session)
        downloads = os.path.join(session, "downloads")
        saved_any = os.path.isdir(downloads) and any(
            n.startswith("file.bin") for n in os.listdir(downloads))
        check("download_saved", saved_any and "provenance=saved" in out, out[:200])

        # Надёжное извлечение фото: srcset/data-src/og:image тоже попадают в список.
        imgs_full = web_tool.execute(action="extract", url=f"{base}/page", extract=["images"])
        check("images_lazy_and_og",
              "lazy-photo.jpg" in imgs_full and "promo.jpg" in imgs_full, imgs_full[:400])

        # Крупный файл не обрезается старым лимитом curl (256000).
        big_path = os.path.join(session, "big.jpg")
        out = curl_tool.execute(url=f"{base}/big.bin", output_path=big_path)
        check("download_not_truncated",
              os.path.exists(big_path) and os.path.getsize(big_path) == 300_003
              and "truncated" not in out, out[:200])

        # HTML-заглушка вместо файла: не сохраняем, сообщаем.
        stub_path = os.path.join(session, "stub.jpg")
        out = web_tool.execute(action="download", url=f"{base}/stub.jpg", output_path=stub_path)
        check("html_stub_rejected",
              "HTML" in out and not os.path.exists(stub_path), out[:250])

        # Проверка хеша: верный sha принимается, неверный — файл удаляется.
        want = hashlib.sha256(DATA_JSON.encode("utf-8")).hexdigest()
        sha_path = os.path.join(session, "json_by_sha.json")
        out = web_tool.execute(action="download", url=f"{base}/data.json",
                               output_path=sha_path, expected_sha256=want)
        check("download_sha_ok", os.path.exists(sha_path) and want[:12] in out, out[:250])
        bad_path = os.path.join(session, "json_bad_sha.json")
        out = web_tool.execute(action="download", url=f"{base}/data.json",
                               output_path=bad_path, expected_sha256="0" * 64)
        check("download_sha_mismatch",
              "sha256 не совпадает" in out and not os.path.exists(bad_path), out[:250])

        # Торренты/magnet распознаются (без реальной сети).
        check("torrent_detect",
              web_tool._is_torrent("magnet:?xt=urn:btih:abc&dn=Ubuntu")
              and web_tool._is_torrent("http://example.com/distro.iso.torrent")
              and not web_tool._is_torrent("http://example.com/file.iso"),
              "is_torrent")
        md = web_tool._destination("magnet:?xt=urn:btih:abc&dn=Ubuntu-24.04.iso", None, session)
        check("magnet_destination", md and md.endswith(os.path.join("downloads", "Ubuntu-24.04.iso")),
              str(md))

        # Память загрузок (глобальная): показывает, что/куда скачано.
        out = web_tool.execute(action="downloads")
        check("downloads_memory", "big.jpg" in out and "✅" in out, out[:300])
        # Файл пропал — память видит это и предлагает докачку.
        os.remove(big_path)
        out = web_tool.execute(action="downloads")
        check("downloads_pending", "недокачан" in out or "отсутствует" in out
              or "resume=true" in out, out[:400])

        # auto-роутинг JSON
        out = web_tool.execute(action="auto", url=f"{base}/data.json")
        check("auto_json", "provenance=raw" in out, out[:200])

        # auto-роутинг HTML
        out = web_tool.execute(action="auto", url=f"{base}/page")
        check("auto_html", "Заголовок статьи" in out, out[:200])

        # HTTP 404 с подсказкой
        out = web_tool.execute(action="open", url=f"{base}/missing")
        check("http_error_hint", "HTTP 404" in out and "Совет" in out, out[:200])

        # HTTP 400: тело ответа сервера пробрасывается модели
        out = web_tool.execute(action="json", url=f"{base}/badparam")
        check("http_error_body", "Ответ сервера" in out and "bad param" in out, out[:250])

        # Беззнаковая правка кодирования: первый запрос 400, повтор декодированным — 200
        out = web_tool.execute(action="json", url=f"{base}/encoded?period=2026%2F09")
        check("encoded_slash_autofix", "Example/Zone" in out and "fixed=" in out, out[:250])

        # Общая авто-методика: сервер назвал параметр — один повтор без него,
        # данные отдаются, модель не зацикливается.
        out = web_tool.execute(action="json", url=f"{base}/drop?bad=1")
        check("param_drop_autoretry", "Example/Zone" in out and "fixed=dropped bad" in out,
              out[:250])

        # Методика (без доменной конкретики): сервер назвал параметр —
        # инструмент показывает причину, называет параметр и предлагает
        # следующий вызов без него (значения не зашиты в код).
        out = web_tool.execute(action="json", url=f"{base}/namedparam?period=2026")
        check("param_named_in_error", "invalid period" in out and "параметр" in out, out[:250])
        tail = out.split("Следующие шаги", 1)[-1]
        check("param_strip_next_action", "web action=json" in tail and "period" not in tail,
              tail[:250])

        # jq safety
        out = web_tool.execute(action="json", url=f"{base}/data.json", jq='@base64 "x"')
        check("jq_unsafe_blocked", "небезопасн" in out, out[:200])

        # ошибка jq: возвращаем текст ошибки и подсказку по синтаксису
        out = web_tool.execute(action="json", url=f"{base}/data.json",
                               jq=".daily | startswith(1, 2)")
        check("jq_error_hint", "jq error" in out and "💡" in out, out[:250])

        # curl regression: jq_filter больше не TypeError
        out = curl_tool.execute(url=f"{base}/data.json", jq_filter=".zone")
        check("curl_jq_filter", "TypeError" not in out and "Example/Zone" in out, out[:200])

        # curl output_path -> сохранение
        target = os.path.join(session, "via_curl.json")
        out = curl_tool.execute(url=f"{base}/data.json", output_path=target)
        check("curl_output_path", os.path.exists(target) and "provenance=saved" in out, out[:200])

        # web_extract wrapper
        out = web_extract_tool.execute(url=f"{base}/page", extract=["headings"], max_items=10)
        check("web_extract_wrapper", "Заголовок статьи" in out and "provenance=extracted" in out, out[:200])

        # web_search wrapper: без сети тестируем делегирование через monkeypatch
        cached = web_search_tool._web._action_search

        def fake_search(query, headers, timeout_sec, max_bytes, max_items):
            return ("🔎 fake — 1 результатов\n\n1. Result\n   https://example.com",
                    ['web action=open url="https://example.com"'])
        web_search_tool._web._action_search = fake_search
        try:
            out = web_search_tool.ddg_search("запрос")
            check("web_search_wrapper", "provenance=extracted" in out and "https://example.com" in out, out[:200])
        finally:
            web_search_tool._web._action_search = cached

        # парсер DDG без сети
        parsed = web_tool._parse_ddg_html(DDG_FIXTURE, 10)
        check("ddg_parser", len(parsed) == 2 and parsed[0]["url"] == "https://example.com/a",
              str(parsed))

        # vision по URL: CDN требует браузерный User-Agent
        from core.tool_manager import ToolManager
        tm = ToolManager()
        vres = tm.call_tool("vision", {"url": f"{base}/img.jpg", "prompt": "Опиши"})
        check("vision_by_url_ua", isinstance(vres, dict) and bool(vres.get("image_data")),
              str(vres)[:200])

        # гейт: web download вне сессии в простом режиме
        os.environ["BOTINOK_DANGEROUS"] = "0"
        tm = ToolManager()
        outside = os.path.join(tempfile.mkdtemp(prefix="botinok_out_"), "x.bin")
        r = tm.call_tool("web", {"action": "download", "url": f"{base}/file.bin",
                                 "output_path": outside}, session_path=session)
        check("gate_outside_blocked", r.startswith("Error"), r[:200])
        inside = os.path.join(session, "inside.bin")
        r = tm.call_tool("web", {"action": "download", "url": f"{base}/file.bin",
                                 "output_path": inside}, session_path=session)
        check("gate_inside_allowed", os.path.exists(inside), r[:200])
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ WEB KIT SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
