"""Веб-зеркало сессии (v1, только чтение).

Консоль остаётся единственным владельцем процесса; зеркало — вид:
крошечный HTTP+SSE сервер на stdlib asyncio, только localhost, одноразовый
токен в ссылке. События подаёт BotinokTextualApp через publish() из своего
event loop (Textual тоже asyncio — отдельного процесса и потоков нет).
Поздние клиенты получают кольцевой буфер событий, дальше — живой поток.
"""

import asyncio
import json
import re
import secrets
import time
from collections import deque
from urllib.parse import urlsplit, parse_qs, unquote

MAX_EVENTS = 5000
MAX_BYTES = 4_000_000
HEARTBEAT_S = 20.0
_COOKIE_NAME = "btok"
_IMG_ID_RE = re.compile(r"[A-Za-z0-9_.\-]{1,64}")

_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ботинок — зеркало</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#101418;color:#d8dee4;
     font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
#top{position:sticky;top:0;display:flex;gap:10px;align-items:center;
     padding:8px 14px;background:#161b22;border-bottom:1px solid #2d333b;z-index:5}
#dot{width:9px;height:9px;border-radius:50%;background:#e5534b;flex:none}
#dot.ok{background:#3fb950}
#who{font-weight:bold}
#sub{color:#8b949e;font-size:12px}
#out{padding:10px 14px 40vh;max-width:1100px}
#logo{max-width:420px;width:100%;display:block;margin:12px 0;border-radius:8px}
.blk{margin:10px 0;padding:8px 10px;border-radius:6px;background:#161b22;
     border-left:3px solid #30363d;white-space:pre-wrap;word-break:break-word}
.user{border-left-color:#58a6ff;background:#132133}
.user .h{color:#58a6ff;font-weight:bold}
.thought{border-left-color:#bc8cff}
.thought .h{color:#bc8cff}
.log{color:#8b949e;font-size:12px;border:none;background:none;padding:2px 10px;margin:0}
.turnblk{margin:10px 0}
details.think{background:#14181d;border-left:3px solid #484f58;border-radius:6px;
              padding:4px 10px;margin:6px 0}
details.think summary{color:#8b949e;cursor:pointer}
details.think pre{white-space:pre-wrap;word-break:break-word;color:#9aa4af;margin:6px 0;font:inherit}
.ans{border-left-color:#3fb950}
.ans pre{margin:0;white-space:pre-wrap;word-break:break-word;font:inherit}
.ans img{max-width:100%;height:auto;border-radius:6px;margin:6px 0;display:block;background:#0d1117}
.tool{font-size:12px;color:#d29922;white-space:pre-wrap;word-break:break-word}
.tool.done{color:#3fb950}
.tool .q{color:#8b949e}
pre.code{background:#0d1117;border:1px solid #30363d;border-radius:6px;
         padding:8px;overflow-x:auto;white-space:pre}
code.inl{background:#22272e;border-radius:3px;padding:0 3px}
a{color:#58a6ff}
</style></head><body>
<div id="top"><div id="dot"></div><span id="who">&#129302; Ботинок — зеркало</span><span id="sub"></span></div>
<div id="out"><img id="logo" alt=""></div>
<script>
"use strict";
var out=document.getElementById('out'),dot=document.getElementById('dot'),sub=document.getElementById('sub');
var cur=null,stick=true;
var TOK=(new URLSearchParams(location.search)).get('tok')||'';
var logo=document.getElementById('logo');
logo.src='/logo?tok='+encodeURIComponent(TOK);
logo.onerror=function(){logo.remove()};
var TOK_RE=/\\[\\[image:([^\\|\\]]+)(?:\\|([^\\]]*))?\\]\\]/g;
addEventListener('scroll',function(){stick=(innerHeight+scrollY)>=document.body.offsetHeight-140});
function esc(s){return String(s).replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c]})}
function md(s){
  var parts=esc(s).split('```'),h='';
  parts.forEach(function(b,i){
    if(i%2===1){h+='<pre class="code">'+b.replace(/^\\w*\\n/,'')+'</pre>';}
    else{h+=b.replace(/`([^`\\n]+)`/g,function(m,c){return '<code class="inl">'+c+'</code>'})
           .replace(/\\*\\*([^*\\n]+)\\*\\*/g,'<b>$1</b>')
           .replace(/^#{1,6} +(.*)$/gm,'<b style="color:#58a6ff">$1</b>')
           .replace(/(https?:\\/\\/[^\\s<]+)/g,'<a href="$1">$1</a>');}
  });
  return h;
}
function rich(s){return md(s).replace(TOK_RE,function(m,id,alt){
  return '\\n<img src="/img/'+encodeURIComponent(id)+'?tok='+encodeURIComponent(TOK)+'" alt="'+esc(alt||'image')+'" loading="lazy">\\n';});}
function el(tag,cls,parent){var e=document.createElement(tag);if(cls)e.className=cls;(parent||out).appendChild(e);return e}
function turn(){if(!cur){cur={box:el('div','turnblk'),det:null,think:null,ans:null,pre:null,tools:{}};}return cur}
function render(ev){
  if(ev.t==='hello'){sub.textContent=(ev.model?('модель: '+ev.model+' \\u00b7 '):'')+'сессия: '+(ev.session||'');}
  else if(ev.t==='user'){cur=null;var u=el('div','blk user');u.innerHTML='<span class="h">\\ud83d\\udc64 User<\\/span>\\n'+rich(ev.text);}
  else if(ev.t==='thought'){cur=null;var t=el('div','blk thought');t.innerHTML='<span class="h">\\ud83d\\udcad мысль</span>\\n'+rich(ev.text);}
  else if(ev.t==='thinking'){var c=turn();if(!c.det){c.det=el('details','think',c.box);c.det.open=true;var sm=document.createElement('summary');sm.textContent='\\ud83d\\udcad Размышление\\u2026';c.det.appendChild(sm);c.think=el('pre','',c.det);}c.think.textContent+=ev.text;}
  else if(ev.t==='content'){var c2=turn();if(!c2.ans){c2.ans=el('div','blk ans',c2.box);c2.pre=el('pre','',c2.ans);c2.raw='';c2.last=0;}
    c2.raw+=ev.text;var now=Date.now();
    if(now-c2.last>100){c2.last=now;c2.pre.innerHTML=rich(c2.raw);if(stick)scrollTo(0,document.body.scrollHeight);}}
  else if(ev.t==='tool'){var c3=turn();var l=c3.tools[ev.name];if(!l){l=el('div','tool',c3.box);c3.tools[ev.name]=l;}
    l.innerHTML='\\ud83d\\udd27 '+esc(ev.name)+(ev.status&&ev.status!=='running'?' \\u2713':'')+(ev.query?' <span class="q">'+esc(String(ev.query).slice(0,140)).replace(/\\n/g,' ')+'</span>':'');
    if(ev.status&&ev.status!=='running')l.classList.add('done');}
  else if(ev.t==='log'){var lg=el('div','log');lg.textContent=ev.text;}
  else if(ev.t==='turn_end'){var c5=turn();if(c5.pre&&c5.raw)c5.pre.innerHTML=rich(c5.raw);
    if(c5.det)c5.det.remove();
    if(!c5.ans&&!Object.keys(c5.tools).length&&!(c5.det&&c5.det.parentNode))c5.box.remove();cur=null;}
  if(stick)scrollTo(0,document.body.scrollHeight);
}
function connect(){
  var tok=(new URLSearchParams(location.search)).get('tok')||'';
  var es=new EventSource('events'+(tok?'?tok='+encodeURIComponent(tok):''));
  es.onopen=function(){dot.classList.add('ok')};
  es.onmessage=function(e){try{render(JSON.parse(e.data))}catch(_){}};
  es.onerror=function(){dot.classList.remove('ok')};
}
connect();
</script></body></html>
"""


class WebMirror:
    """HTTP+SSE сервер зеркала. Запуск/остановка — из event loop приложения."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, on_change=None,
                 resolve_image=None, logo_path: str = ""):
        self.host = host
        self.port = port
        self.token = secrets.token_urlsafe(6)
        self.url = ""
        # Вызывается из event loop при подключении/отключении браузера:
        # on_change(len(self._queues)) — для индикатора клиентов в шапке.
        self._on_change = on_change
        # resolve_image(image_id) -> (bytes, mime) | None — раздача картинок
        # сессии по маркерам [[image:<id>]].
        self._resolve_image = resolve_image
        # Приветственный логотип на странице (assets/logo.png).
        self._logo_path = logo_path
        self._server = None
        self._writers = set()
        self._queues = set()
        self._buffer = deque()
        self._buf_bytes = 0
        self._seq = 0

    # ── публикация событий (только из event loop) ─────────────────────────

    def seed(self, events) -> None:
        """Заполнить буфер историей сессии до подключения клиентов."""
        for ev in events:
            self.publish(ev)

    def publish(self, ev: dict) -> None:
        self._seq += 1
        ev = dict(ev)
        ev["id"] = self._seq
        ev.setdefault("ts", round(time.time(), 3))
        s = json.dumps(ev, ensure_ascii=False)
        self._buffer.append(s)
        self._buf_bytes += len(s)
        while self._buffer and (len(self._buffer) > MAX_EVENTS or self._buf_bytes > MAX_BYTES):
            self._buf_bytes -= len(self._buffer.popleft())
        for q in list(self._queues):
            try:
                q.put_nowait(s)
            except asyncio.QueueFull:
                pass

    # ── жизненный цикл ─────────────────────────────────────────────────────

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"http://{self.host}:{port}/?tok={self.token}"
        return self.url

    def close_sync(self) -> None:
        srv, self._server = self._server, None
        if srv is not None:
            try:
                srv.close()
            except Exception:
                pass
        for q in list(self._queues):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        for w in list(self._writers):
            try:
                w.close()
            except Exception:
                pass

    async def stop(self) -> None:
        self.close_sync()
        if self._server is not None:
            try:
                await self._server.wait_closed()
            except Exception:
                pass

    @property
    def clients(self) -> int:
        return len(self._queues)

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change(self.clients)
            except Exception:
                pass

    # ── HTTP ────────────────────────────────────────────────────────────────

    def _authorized(self, path: str, cookie: str) -> bool:
        qs = parse_qs(urlsplit(path).query)
        tok = (qs.get("tok") or [""])[0]
        if not tok and cookie:
            for part in cookie.split(";"):
                k, _, v = part.strip().partition("=")
                if k == _COOKIE_NAME:
                    tok = v
        return secrets.compare_digest(tok or "", self.token)

    async def _send(self, writer, status: str, ctype: str, body: bytes, extra: str = "") -> None:
        head = (f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n{extra}\r\n").encode()
        writer.write(head + body)
        try:
            await writer.drain()
        except (ConnectionError, Exception):
            pass

    async def _handle(self, reader, writer) -> None:
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
        except Exception:
            try:
                writer.close()
            except Exception:
                pass
            return
        text = raw.decode("latin-1", "replace")
        lines = text.split("\r\n")
        parts = lines[0].split(" ")
        method = parts[0] if parts else ""
        path = parts[1] if len(parts) > 1 else "/"
        cookie = ""
        for ln in lines[1:]:
            if ln.lower().startswith("cookie:"):
                cookie = ln.split(":", 1)[1].strip()
        if method != "GET":
            await self._send(writer, "405 Method Not Allowed",
                             "text/plain; charset=utf-8", "только GET".encode())
            return
        if not self._authorized(path, cookie):
            await self._send(writer, "403 Forbidden", "text/html; charset=utf-8",
                             "<h3>Доступ запрещён</h3><p>Откройте ссылку из консоли — "
                             "в ней одноразовый ключ.</p>".encode())
            return
        route = urlsplit(path).path
        if route in ("/", "/index.html"):
            await self._send(writer, "200 OK", "text/html; charset=utf-8",
                             _PAGE.encode(),
                             extra=f"Set-Cookie: {_COOKIE_NAME}={self.token}; Path=/; "
                                   f"HttpOnly; SameSite=Lax\r\nCache-Control: no-store\r\n")
            return
        if route == "/events":
            await self._sse(reader, writer)
            return
        if route.startswith("/img/"):
            await self._image(writer, unquote(route[len("/img/"):]))
            return
        if route == "/logo":
            data = None
            try:
                if self._logo_path:
                    with open(self._logo_path, "rb") as f:
                        data = f.read()
            except Exception:
                data = None
            if data:
                await self._send(writer, "200 OK", "image/png", data,
                                 extra="Cache-Control: private, max-age=86400\r\n")
            else:
                await self._send(writer, "404 Not Found", "text/plain; charset=utf-8", b"")
            return
        await self._send(writer, "404 Not Found", "text/plain; charset=utf-8", b"")

    async def _image(self, writer, image_id: str) -> None:
        if not _IMG_ID_RE.fullmatch(image_id) or self._resolve_image is None:
            await self._send(writer, "404 Not Found", "text/plain; charset=utf-8", b"")
            return
        try:
            got = self._resolve_image(image_id)
        except Exception:
            got = None
        if not got:
            await self._send(writer, "404 Not Found", "text/plain; charset=utf-8", b"")
            return
        data, mime = got
        await self._send(writer, "200 OK", mime, data,
                         extra="Cache-Control: private, max-age=86400\r\n")

    async def _sse(self, reader, writer) -> None:
        q = asyncio.Queue(maxsize=2000)
        self._queues.add(q)
        self._writers.add(writer)
        self._notify()
        get_task = None
        # Читатель «в пустоту»: read(1) вернёт EOF, как только браузер
        # закроет соединение, — снимаем клиента сразу, не дожидаясь heartbeat.
        eof_task = asyncio.ensure_future(reader.read(1))
        try:
            writer.write(b"HTTP/1.1 200 OK\r\n"
                         b"Content-Type: text/event-stream; charset=utf-8\r\n"
                         b"Cache-Control: no-store\r\n"
                         b"X-Accel-Buffering: no\r\n\r\n")
            await writer.drain()
            for s in list(self._buffer):
                writer.write(b"data: " + s.encode() + b"\n\n")
            await writer.drain()
            while True:
                get_task = asyncio.ensure_future(q.get())
                done, _ = await asyncio.wait(
                    {get_task, eof_task}, timeout=HEARTBEAT_S,
                    return_when=asyncio.FIRST_COMPLETED)
                if eof_task in done:
                    break
                if get_task in done:
                    s = get_task.result()
                    get_task = None
                    if s is None:
                        break
                    writer.write(b"data: " + s.encode() + b"\n\n")
                    await writer.drain()
                else:
                    writer.write(b": ping\n\n")
                    await writer.drain()
        except Exception:
            pass
        finally:
            if get_task is not None and not get_task.done():
                get_task.cancel()
            if not eof_task.done():
                eof_task.cancel()
            self._queues.discard(q)
            self._writers.discard(writer)
            self._notify()
            try:
                writer.close()
            except Exception:
                pass
