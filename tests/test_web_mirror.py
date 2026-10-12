#!/usr/bin/env python3
"""
Тесты core/web_mirror: токен-доступ, SSE-воспроизведение буфера, живые
события, остановка. Без внешних зависимостей, чистый asyncio.

Запуск: venv/bin/python -u tests/test_web_mirror.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.web_mirror import WebMirror  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILURES.append(name)


async def http_get(reader, writer):
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = await reader.read(4096)
        if not chunk:
            break
        head += chunk
    header_blob, _, rest = head.partition(b"\r\n\r\n")
    status_line = header_blob.split(b"\r\n")[0].decode()
    headers = {}
    for ln in header_blob.split(b"\r\n")[1:]:
        k, _, v = ln.decode("latin-1").partition(":")
        headers[k.strip().lower()] = v.strip()
    body = rest
    if "content-length" in headers:
        need = int(headers["content-length"])
        while len(body) < need:
            chunk = await reader.read(need - len(body))
            if not chunk:
                break
            body += chunk
    return status_line, headers, body


async def read_sse_events(reader, n, buf=b"", timeout=3.0):
    events = []
    while len(events) < n:
        while b"\n\n" in buf:
            block, _, buf = buf.partition(b"\n\n")
            for ln in block.split(b"\n"):
                if ln.startswith(b"data: "):
                    events.append(json.loads(ln[6:].decode()))
        if len(events) >= n:
            break
        chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        if not chunk:
            break
        buf += chunk
    return events, buf


async def main() -> int:
    m = WebMirror()
    await m.start()
    host, port = m.host, m._server.sockets[0].getsockname()[1]
    tok = m.token
    check("url содержит токен", tok in m.url)

    m.seed([{"t": "user", "text": "привет"},
            {"t": "thinking", "text": "думаю…"},
            {"t": "content", "text": "ответ"},
            {"t": "turn_end", "tools": []}])

    # 403 без токена
    r, w = await asyncio.open_connection(host, port)
    w.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    status, _, body = await http_get(r, w)
    w.close()
    check("без токена — 403", "403" in status, status)

    # 200 страница с токеном
    r, w = await asyncio.open_connection(host, port)
    w.write(f"GET /?tok={tok} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    status, headers, body = await http_get(r, w)
    w.close()
    check("со ссылкой — 200", "200" in status, status)
    check("страница — HTML с EventSource", b"text/html" in headers.get("content-type", "").encode()
          and b"EventSource" in body)
    check("ставится cookie", "btok=" in headers.get("set-cookie", ""))

    # доступ по cookie (повторный заход без tok)
    r, w = await asyncio.open_connection(host, port)
    w.write(f"GET / HTTP/1.1\r\nHost: x\r\nCookie: btok={tok}\r\n\r\n".encode())
    status, _, _ = await http_get(r, w)
    w.close()
    check("по cookie — 200", "200" in status, status)

    # SSE: воспроизведение буфера + живое событие
    r, w = await asyncio.open_connection(host, port)
    w.write(f"GET /events?tok={tok} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += await r.read(4096)
    check("SSE — text/event-stream", b"text/event-stream" in head.split(b"\r\n\r\n")[0])
    sse_buf = head.split(b"\r\n\r\n", 1)[1]
    replayed, sse_buf = await read_sse_events(r, 4, sse_buf)
    check("буфер воспроизведён", [e["t"] for e in replayed] ==
          ["user", "thinking", "content", "turn_end"],
          str([e.get("t") for e in replayed]))
    check("id монотонные", [e["id"] for e in replayed] == [1, 2, 3, 4])

    async def later():
        await asyncio.sleep(0.1)
        m.publish({"t": "log", "text": "живое"})
    asyncio.ensure_future(later())
    live, _ = await read_sse_events(r, 1, sse_buf)
    check("живое событие доставлено", live and live[0]["t"] == "log" and live[0]["text"] == "живое")

    # остановка закрывает поток
    m.close_sync()
    tail = await asyncio.wait_for(r.read(65536), timeout=3.0)
    check("поток закрыт после остановки", tail == b"", repr(tail[:40]))
    w.close()

    # буферtrimmed по количеству
    m2 = WebMirror()
    import core.web_mirror as wm
    old = wm.MAX_EVENTS
    wm.MAX_EVENTS = 10
    for i in range(25):
        m2.publish({"t": "log", "text": str(i)})
    wm.MAX_EVENTS = old
    check("кольцевой буфер обрезан", len(m2._buffer) == 10 and "24" in m2._buffer[-1])

    # счётчик клиентов: подключение/мгновенное снятие по EOF
    changes = []
    m3 = WebMirror(on_change=lambda n: changes.append(n))
    await m3.start()
    host3, port3 = m3.host, m3._server.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection(host3, port3)
    w.write(f"GET /events?tok={m3.token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await r.readuntil(b"\r\n\r\n")
    await asyncio.sleep(0.2)
    check("клиент посчитан", m3.clients == 1)
    w.close()
    await asyncio.sleep(0.4)
    check("клиент снят по EOF", m3.clients == 0, f"clients={m3.clients}")
    check("on_change вызывался", changes and changes[0] == 1 and changes[-1] == 0, str(changes))
    m3.close_sync()

    # раздача картинок сессии
    m4 = WebMirror(resolve_image=lambda i: (b"PNGDATA", "image/png") if i == "abc" else None)
    await m4.start()
    host4, port4 = m4.host, m4._server.sockets[0].getsockname()[1]

    async def get4(path):
        r, w = await asyncio.open_connection(host4, port4)
        w.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        st, hd, bd = await http_get(r, w)
        w.close()
        return st, hd, bd

    st, hd, bd = await get4(f"/img/abc?tok={m4.token}")
    check("картинка отдаётся", "200" in st and bd == b"PNGDATA"
          and "image/png" in hd.get("content-type", ""), st)
    st, _, _ = await get4(f"/img/nope?tok={m4.token}")
    check("нет картинки — 404", "404" in st, st)
    st, _, _ = await get4("/img/..%2F..%2Fx?tok=" + m4.token)
    check("нечистый id — 404", "404" in st, st)
    st, _, _ = await get4("/img/abc")
    check("картинка без токена — 403", "403" in st, st)
    m4.close_sync()

    # приветственный логотип
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(b"LOGOBYTES")
        lp = tf.name
    m5 = WebMirror(logo_path=lp)
    await m5.start()
    r, w = await asyncio.open_connection(m5.host, m5._server.sockets[0].getsockname()[1])
    w.write(f"GET /logo?tok={m5.token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    st, hd, bd = await http_get(r, w)
    w.close()
    check("логотип отдаётся", "200" in st and bd == b"LOGOBYTES"
          and "image/png" in hd.get("content-type", ""), st)
    m5.close_sync()
    os.unlink(lp)

    print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if not FAILURES else 'ПРОВАЛЫ: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
