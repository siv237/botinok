#!/usr/bin/env python3
"""
Тесты core/net_config: нормализация прокси, хранение, наследование, проверка.

Локальный HTTP-прокси (принимает absolute-URI GET) позволяет проверить
`net.test()` без внешней сети.

Запуск: venv/bin/python -u tests/test_net_config.py
"""

import http.server
import os
import socketserver
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import net_config as net  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


TINY_JPEG = b"\xff\xd8\xff\xe0" + b"J" * 64


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """Мини-прокси: отвечает на absolute-URI GET картинкой."""
    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        ProxyHandler.seen.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(TINY_JPEG)))
        self.end_headers()
        self.wfile.write(TINY_JPEG)

    def do_CONNECT(self):
        # Для https-цели: подтверждаем туннель и закрываем.
        self.send_response(200, "Connection Established")
        self.end_headers()


def start_proxy():
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), ProxyHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def main() -> int:
    print("=" * 70)
    print("net_config smoke-test")
    print("=" * 70)

    # --- normalize_proxy: прощающий ввод ---
    cases = {
        "17277": "http://127.0.0.1:17277",
        "127.0.0.1:17277": "http://127.0.0.1:17277",
        "http://127.0.0.1:17277": "http://127.0.0.1:17277",
        "https://proxy:3128": "https://proxy:3128",
        "user:pass@10.0.0.1:8080": "http://user:pass@10.0.0.1:8080",
        "socks5://127.0.0.1:9050": "socks5://127.0.0.1:9050",
        "proxy.local 8080 u p": "http://u:p@proxy.local:8080",
        "socks5 host 1080": "socks5://host:1080",
        "10.0.0.1 3128": "http://10.0.0.1:3128",
    }
    for raw, want in cases.items():
        try:
            got = net.normalize_proxy(raw)
            check(f"normalize[{raw}]", got == want, f"got={got} want={want}")
        except Exception as e:
            check(f"normalize[{raw}]", False, f"{type(e).__name__}: {e}")

    for off in ("none", "off", "clear", "", "  ", None, 0):
        # 0 не должен проходить (это не порт) — проверяем только None-значения
        if off == 0:
            continue
        check(f"normalize_off[{off!r}]", net.normalize_proxy(off) is None)

    for bad in ("abc", "http://host", "host:abc", "127.0.0.1:99999"):
        try:
            net.normalize_proxy(bad)
            check(f"normalize_bad[{bad}]", False, "ожидалась ValueError")
        except ValueError:
            check(f"normalize_bad[{bad}]", True)

    # --- mask_proxy ---
    check("mask_password", "***" in net.mask_proxy("http://u:secret@h:1")
          and "secret" not in net.mask_proxy("http://u:secret@h:1"))
    check("mask_none", net.mask_proxy(None) == "—")

    # --- normalize_no_proxy ---
    check("no_proxy_list", net.normalize_no_proxy(["a", "b"]) == "a,b")
    check("no_proxy_str", net.normalize_no_proxy(" a, b ,,c ") == "a,b,c")

    # --- proxy_host_port ---
    check("host_port", net.proxy_host_port("http://u:p@h:3128") == ("h", 3128))

    # --- хранилище: изолируем глобальный конфиг ---
    cfg = os.path.join(tempfile.mkdtemp(prefix="botinok_cfg_"), "config.cfg")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("[Tools]\n")
    os.environ["BOTINOK_CONFIG"] = cfg
    session = tempfile.mkdtemp(prefix="botinok_net_")
    os.makedirs(os.path.join(session, "project"), exist_ok=True)

    check("get_none", net.get(session) == (None, "none"))

    # global
    st = net.set_proxy("http://global.proxy:3128", session, scope="global")
    check("set_global", st["scope"] == "global" and st["proxy"] == "http://global.proxy:3128")
    check("get_global", net.get(session) == ("http://global.proxy:3128", "global"))
    check("global_in_file", "global.proxy" in open(cfg, encoding="utf-8").read())

    # session перекрывает global
    net.set_proxy("17277", session, scope="session")
    check("session_overrides_global", net.get(session)[1] == "session"
          and net.get(session)[0] == "http://127.0.0.1:17277")
    check("no_proxy_saved", net.set_proxy("17277", session, no_proxy="localhost,.local",
                                          scope="session")["no_proxy"] == "localhost,.local")

    # --- наследование форм ---
    check("httpx_proxy", net.httpx_proxy(session) == "http://127.0.0.1:17277")
    check("requests_proxies", (net.requests_proxies(session) or {}).get("https")
          == "http://127.0.0.1:17277")
    check("aria2c_args", net.aria2c_args(session)[0] == "--all-proxy=http://127.0.0.1:17277"
          and any(a.startswith("--no-proxy=") for a in net.aria2c_args(session)))
    env = net.subprocess_env(session)
    check("subprocess_env", env.get("HTTPS_PROXY") == "http://127.0.0.1:17277"
          and "https_proxy" not in env)

    # --- show ---
    sh = net.show(session)
    check("show", sh["proxy"] == "http://127.0.0.1:17277" and sh["source"] == "session"
          and sh["no_proxy"] == "localhost,.local")

    # --- env как источник; пустые env игнорируются ---
    net.clear(session, scope="session")
    net.clear(session, scope="global")
    saved = {k: os.environ.get(k) for k in
             ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        os.environ["https_proxy"] = ""          # пустое — не источник
        os.environ["HTTPS_PROXY"] = "http://env.proxy:8080"
        check("env_ignored_when_empty", net.get(session) == ("http://env.proxy:8080", "env"),
              str(net.get(session)))
    finally:
        for k in saved:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]

    # --- clear ---
    net.set_proxy("17277", session, scope="session")
    net.clear(session, scope="session")
    check("clear_session", net.get(session)[0] is None)
    net.set_proxy("17277", session, scope="global")
    net.clear(session, scope="global")
    check("clear_global", net.get(session)[0] is None)

    # --- test(): без прокси и с реальным мини-прокси ---
    check("test_no_proxy", net.test(session)["configured"] is False)

    httpd, proxy_url = start_proxy()
    try:
        res = net.test(session, override=proxy_url, url="http://example.test/img.jpg",
                       timeout_sec=10)
        check("test_tcp", (res.get("tcp") or {}).get("ok") is True, str(res)[:200])
        check("test_http_ok", (res.get("http") or {}).get("ok") is True, str(res)[:200])
        check("test_confirms", res.get("ok") is True, str(res)[:200])
        check("test_used_proxy", any(p.startswith("http://example.test/") for p in ProxyHandler.seen),
              str(ProxyHandler.seen[:3]))
    finally:
        httpd.shutdown()
        httpd.server_close()

    res = net.test(session, override="http://127.0.0.1:1", url="http://example.test/x")
    check("test_bad_proxy", res.get("ok") is False)

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ NET_CONFIG SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


if __name__ == "__main__":
    sys.exit(main())
