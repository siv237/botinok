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

    # тема страницы и версия
    m6 = WebMirror(theme="day")
    await m6.start()
    r, w = await asyncio.open_connection(m6.host, m6._server.sockets[0].getsockname()[1])
    w.write(f"GET /?tok={m6.token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    _, _, body = await http_get(r, w)
    w.close()
    check('страница в теме day', b'<body class="day">' in body)
    check("__THEME__ подставлен", b"__THEME__" not in body)
    m7 = WebMirror(theme="зловред")
    check("неизвестная тема → night", m7.theme == "night")
    m7.publish({"t": "hello", "version": "0.5"})
    m6.publish({"t": "hello", "version": "0.5"})
    r, w = await asyncio.open_connection(m6.host, m6._server.sockets[0].getsockname()[1])
    w.write(f"GET /events?tok={m6.token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += await r.read(4096)
    evs, _ = await read_sse_events(r, 1, head.split(b"\r\n\r\n", 1)[1])
    w.close()
    check("hello с версией", evs and evs[0].get("version") == "0.5")
    m6.close_sync()

    # ленивая история: страницы и курсор
    groups = [[{"t": "user", "text": "m1"}, {"t": "turn_end", "tools": []}],
              [{"t": "user", "text": "m2"}],
              [{"t": "user", "text": "m3"}]]

    def prov(before, limit):
        total = len(groups)
        end = total if before < 0 else max(0, min(before, total))
        start = max(0, end - limit)
        return [ev for g in groups[start:end] for ev in g], start

    m8 = WebMirror(history_provider=prov)
    await m8.start()
    host8, port8 = m8.host, m8._server.sockets[0].getsockname()[1]

    async def get8(path):
        r, w = await asyncio.open_connection(host8, port8)
        w.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        st, _, bd = await http_get(r, w)
        w.close()
        return st, json.loads(bd.decode())

    st, d = await get8(f"/history?limit=1&tok={m8.token}")
    check("последняя страница истории", "200" in st and d["cursor"] == 2
          and [e.get("text") for e in d["events"]] == ["m3"], str(d))
    st, d = await get8(f"/history?before=2&limit=2&tok={m8.token}")
    check("страница старше, курсор 0", d["cursor"] == 0
          and [e.get("text") for e in d["events"] if e["t"] == "user"] == ["m1", "m2"], str(d))
    r, w = await asyncio.open_connection(host8, port8)
    w.write(b"GET /history HTTP/1.1\r\nHost: x\r\n\r\n")
    st, _, _ = await http_get(r, w)
    w.close()
    check("history без токена — 403", "403" in st, st)
    m8.close_sync()

    #paging по всем страницам: последовательно и без повторов
    many = [[{"t": "user", "text": f"x{i}"}] for i in range(1, 8)]

    def prov9(before, limit):
        total = len(many)
        end = total if before < 0 else max(0, min(before, total))
        start = max(0, end - limit)
        return [ev for g in many[start:end] for ev in g], start

    m9 = WebMirror(history_provider=prov9)
    await m9.start()
    host9, port9 = m9.host, m9._server.sockets[0].getsockname()[1]

    async def get9(path):
        r, w = await asyncio.open_connection(host9, port9)
        w.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        st, _, bd = await http_get(r, w)
        w.close()
        return json.loads(bd.decode())

    pages, cursor, guard = [], -1, 0
    while guard < 20:
        guard += 1
        d = await get9(f"/history?before={cursor}&limit=3&tok={m9.token}")
        pages.append([e["text"] for e in d["events"]])
        cursor = d["cursor"]
        if cursor == 0:
            break
    flat = [t for pg in pages for t in pg]
    check("страницы истории покрывают всё без пропусков",
          sorted(flat) == sorted(f"x{i}" for i in range(1, 8)), str(pages))
    check("страницы истории без повторов", len(flat) == len(set(flat)), str(flat))
    check("каждая страница истории внутри возрастающая",
          all(pg == sorted(pg, key=lambda t: int(t[1:])) for pg in pages), str(pages))
    check("страницы идут от новых к старым", pages[0][-1] == "x7" and pages[-1][0] == "x1",
          str(pages))
    m9.close_sync()

    # SSE: кадры с id и досылка по Last-Event-ID (без дублей при реконнекте)
    m10 = WebMirror()
    await m10.start()
    host10, port10 = m10.host, m10._server.sockets[0].getsockname()[1]
    for i in range(5):
        m10.publish({"t": "log", "text": f"e{i}"})
    r, w = await asyncio.open_connection(host10, port10)
    w.write(f"GET /events?tok={m10.token} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += await r.read(4096)
    raw = head.split(b"\r\n\r\n", 1)[1]
    evs, raw = await read_sse_events(r, 5, raw)
    check("SSE-кадры содержат строку id", b"id: " in head + raw)
    w.close()
    r, w = await asyncio.open_connection(host10, port10)
    w.write(f"GET /events?tok={m10.token} HTTP/1.1\r\nHost: x\r\n"
            f"Last-Event-ID: 3\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += await r.read(4096)
    rest, _ = await read_sse_events(r, 2, head.split(b"\r\n\r\n", 1)[1])
    w.close()
    check("Last-Event-ID: досылка только новых событий без дублей",
          [e["id"] for e in rest] == [4, 5], str([e.get("id") for e in rest]))
    m10.close_sync()

    print(f"\n{'ВСЕ ТЕСТЫ ПРОЙДЕНЫ' if not FAILURES else 'ПРОВАЛЫ: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
