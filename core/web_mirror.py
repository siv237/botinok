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

MAX_EVENTS = 20_000
MAX_BYTES = 16_000_000
HEARTBEAT_S = 20.0
_COOKIE_NAME = "btok"
_IMG_ID_RE = re.compile(r"[A-Za-z0-9_.\-]{1,64}")

_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ботинок — зеркало</title>
<style>
body{--bg:#0e1116;--panel:#161b22;--text:#d8dee4;--muted:#8b949e;--accent:#58a6ff;
     --ok:#3fb950;--warn:#d29922;--err:#e5534b;--border:#30363d;--code:#0d1117;
     --user:#132133;--think:#14181d;color-scheme:dark;
     margin:0;background:var(--bg);color:var(--text);
     font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
body.day{--bg:#ffffff;--panel:#f6f8fa;--text:#1f2328;--muted:#59636e;--accent:#0969da;
     --ok:#177a3d;--warn:#936000;--err:#c02d2d;--border:#d0d7de;--code:#eff1f3;
     --user:#ddf4ff;--think:#f6f8fa;color-scheme:light}
body.evening{--bg:#0a2236;--panel:#0d2b45;--text:#d6ecff;--muted:#7fa8c4;--accent:#7ec8ff;
     --ok:#5fd68f;--warn:#ffd75f;--err:#ff7b7b;--border:#1d4e75;--code:#08192a;
     --user:#0d3355;--think:#0c2a44;color-scheme:dark}
#top{position:sticky;top:0;display:flex;gap:10px;align-items:center;
     padding:8px 14px;background:var(--panel);border-bottom:1px solid var(--border);z-index:5}
#dot{width:9px;height:9px;border-radius:50%;background:var(--err);flex:none}
#dot.ok{background:var(--ok)}
#who{font-weight:bold}
#sub{color:var(--muted);font-size:12px}
#out{padding:10px 14px 40vh;max-width:1100px}
#logo{max-width:420px;width:100%;display:block;margin:12px 0 2px;border-radius:8px}
#ver{color:var(--muted);font-size:12px;margin:0 0 12px}
.blk{margin:10px 0;padding:8px 10px;border-radius:6px;background:var(--panel);
     border-left:3px solid var(--border);word-break:break-word}
.blk p{white-space:pre-wrap;margin:6px 0}
.blk h1,.blk h2,.blk h3,.blk h4{margin:8px 0 4px;color:var(--accent)}
.blk h1{font-size:1.3em}.blk h2{font-size:1.2em}.blk h3{font-size:1.1em}.blk h4{font-size:1em}
.user{border-left-color:var(--accent);background:var(--user);white-space:pre-wrap}
.user .h{color:var(--accent);font-weight:bold}
.thought{border-left-color:#bc8cff;white-space:pre-wrap}
.thought .h{color:#bc8cff}
.log{color:var(--muted);font-size:12px;border:none;background:none;padding:2px 10px;margin:0}
.tm{float:right;color:var(--muted);font-size:11px;font-weight:normal}
.datesep{color:var(--muted);font-size:12px;margin:14px 0 4px;text-align:center}
.turnblk{margin:10px 0}
details.think{background:var(--think);border-left:3px solid var(--border);border-radius:6px;
              padding:4px 10px;margin:6px 0}
details.think summary{color:var(--muted);cursor:pointer}
details.think pre{white-space:pre-wrap;word-break:break-word;color:var(--muted);margin:6px 0;font:inherit}
.ans{border-left-color:var(--ok)}
.ans img{max-width:100%;height:auto;border-radius:6px;margin:6px 0;display:block;background:var(--code)}
.tool{font-size:12px;color:var(--warn);white-space:pre-wrap;word-break:break-word}
.tool.done{color:var(--ok)}
.tool .q{color:var(--muted)}
pre.code{background:var(--code);border:1px solid var(--border);border-radius:6px;
         padding:8px;overflow-x:auto;white-space:pre}
code.inl{background:var(--code);border:1px solid var(--border);border-radius:3px;padding:0 3px}
a{color:var(--accent)}
table{border-collapse:collapse;margin:6px 0}
th,td{border:1px solid var(--border);padding:3px 8px;text-align:left}
th{background:var(--code)}
blockquote{margin:6px 0;padding:2px 10px;border-left:3px solid var(--muted);color:var(--muted)}
hr{border:none;border-top:1px solid var(--border);margin:10px 0}
ul,ol{margin:6px 0;padding-left:22px}
</style></head><body class="__THEME__">
<div id="top"><div id="dot"></div><span id="who">&#129302; Ботинок — зеркало</span><span id="sub"></span></div>
<div id="out"><img id="logo" alt=""><div id="ver"></div><div id="histAnchor"></div></div>
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
function inline(s){
  return s.replace(/`([^`\\n]+)`/g,function(m,c){return '<code class="inl">'+c+'</code>'})
    .replace(/\\*\\*([^*\\n]+)\\*\\*/g,'<b>$1</b>')
    .replace(/(^|[^*\\w])\\*([^*\\n]+)\\*/g,'$1<i>$2</i>')
    .replace(/\\[([^\\]]+)\\]\\((https?:[^)\\s]+)\\)/g,'<a href="$2">$1</a>')
    .replace(/(^|[^"'>=(])(https?:\\/\\/[^\\s<)]+)/g,'$1<a href="$2">$2</a>');
}
function isSep(cells){return cells.length>0&&cells.every(function(c){return /^:?-{2,}:?$/.test(c)})}
function blocks(b){
  var lines=b.split('\\n'),out2=[],para=[],list=null,table=null;
  function flushP(){if(para.length){out2.push('<p>'+inline(para.join('\\n'))+'</p>');para=[]}}
  function flushL(){if(list){out2.push('<'+list.t+'>'+list.items.map(function(x){return '<li>'+inline(x)+'</li>'}).join('')+'</'+list.t+'>');list=null}}
  function flushT(){if(table){
    if(table.length>1&&isSep(table[1])){
      out2.push('<table><tr>'+table[0].map(function(c){return '<th>'+inline(c)+'</th>'}).join('')+'</tr>'+
        table.slice(2).map(function(r){return '<tr>'+r.map(function(c){return '<td>'+inline(c)+'</td>'}).join('')+'</tr>'}).join('')+'</table>');
    }else{table.forEach(function(r){para.push(r.join(' | '))});flushP();}
    table=null;}}
  function flushAll(){flushP();flushL();flushT()}
  for(var i=0;i<lines.length;i++){
    var ln=lines[i],m;
    if(m=ln.match(/^(#{1,6}) +(.*)$/)){flushAll();var lv=Math.min(4,m[1].length);out2.push('<h'+lv+'>'+inline(m[2])+'</h'+lv+'>');}
    else if(/^\\s*(-{3,}|\\*{3,})\\s*$/.test(ln)){flushAll();out2.push('<hr>')}
    else if((m=ln.match(/^\\s*\\|(.+)\\|\\s*$/))&&(table!==null||/\\|\\s*:?-/.test(lines[i+1]||''))){flushP();flushL();if(!table)table=[];table.push(m[1].split('|').map(function(c){return c.trim()}));}
    else if(m=ln.match(/^\\s*[-*\\u2022] +(.*)$/)){flushP();flushT();if(!list||list.t!=='ul'){flushL();list={t:'ul',items:[]}}list.items.push(m[1]);}
    else if(m=ln.match(/^\\s*\\d+[.)] +(.*)$/)){flushP();flushT();if(!list||list.t!=='ol'){flushL();list={t:'ol',items:[]}}list.items.push(m[1]);}
    else if(m=ln.match(/^&gt; ?(.*)$/)){flushAll();out2.push('<blockquote>'+inline(m[1])+'</blockquote>')}
    else if(!ln.trim()){flushAll()}
    else{flushL();flushT();para.push(ln)}
  }
  flushAll();
  return out2.join('');
}
function md(s){
  var parts=esc(s).split('```'),h='';
  parts.forEach(function(b,i){
    if(i%2===1){h+='<pre class="code">'+b.replace(/^\\w*\\n/,'')+'</pre>';}
    else{h+=blocks(b);}
  });
  return h;
}
function rich(s){return md(s).replace(TOK_RE,function(m,id,alt){
  return '<img src="/img/'+encodeURIComponent(id)+'?tok='+encodeURIComponent(TOK)+'" alt="'+esc(alt||'image')+'" loading="lazy">';});}
function el(tag,cls,parent){var e=document.createElement(tag);if(cls)e.className=cls;(parent||out).appendChild(e);return e}
function fmtT(ts){var d=new Date(ts*1000);return d.toLocaleDateString('ru-RU')+' '+d.toTimeString().slice(0,5)}
var lastDate=null;
function dateSep(ts){var d=new Date(ts*1000).toDateString();
  if(d!==lastDate){lastDate=d;var s=el('div','datesep');s.textContent=new Date(ts*1000).toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'})}}
function turn(){if(!cur){cur={box:el('div','turnblk'),det:null,think:null,ans:null,raw:'',last:0,tools:{}};}return cur}
function render(ev){
  if(ev.t==='hello'){sub.textContent=(ev.model?('модель: '+ev.model+' \\u00b7 '):'')+'сессия: '+(ev.session||'');
    if(ev.version)document.getElementById('ver').textContent='Ботинок — версия '+ev.version;}
  else if(ev.t==='user'||ev.t==='thought'){cur=null;if(ev.ts)dateSep(ev.ts);
    var u=el('div','blk '+(ev.t==='user'?'user':'thought'));
    u.innerHTML='<span class="h">'+(ev.t==='user'?'\\ud83d\\udc64 User':'\\ud83d\\udcad мысль')+'</span>'+
      (ev.ts?' <span class="tm">'+fmtT(ev.ts)+'</span>':'')+'\\n'+rich(ev.text);}
  else if(ev.t==='thinking'){var c=turn();if(!c.det){c.det=el('details','think',c.box);c.det.open=true;var sm=document.createElement('summary');sm.textContent='\\ud83d\\udcad Размышление\\u2026';c.det.appendChild(sm);c.think=el('pre','',c.det);}c.think.textContent+=ev.text;}
  else if(ev.t==='content'){var c2=turn();if(!c2.ans){c2.ans=el('div','blk ans',c2.box);}
    c2.raw+=ev.text;var now=Date.now();
    if(now-c2.last>100){c2.last=now;c2.ans.innerHTML=rich(c2.raw);if(stick)scrollTo(0,document.body.scrollHeight);}}
  else if(ev.t==='tool'){var c3=turn();var l=c3.tools[ev.name];if(!l){l=el('div','tool',c3.box);c3.tools[ev.name]=l;}
    l.innerHTML='\\ud83d\\udd27 '+esc(ev.name)+(ev.status&&ev.status!=='running'?' \\u2713':'')+(ev.query?' <span class="q">'+esc(String(ev.query).slice(0,140)).replace(/\\n/g,' ')+'</span>':'');
    if(ev.status&&ev.status!=='running')l.classList.add('done');}
  else if(ev.t==='log'){var lg=el('div','log');lg.textContent=ev.text;}
  else if(ev.t==='theme'){document.body.className=ev.name||'night';}
  else if(ev.t==='turn_end'){var c5=turn();
    if(c5.ans&&c5.raw){c5.ans.innerHTML=rich(c5.raw);c5.raw+='\\n\\n';}
    if(c5.det)c5.det.remove();
    if(!c5.ans&&!Object.keys(c5.tools).length&&!(c5.det&&c5.det.parentNode)){c5.box.remove();cur=null;}}
  if(stick)scrollTo(0,document.body.scrollHeight);
}
function connect(){
  var es=new EventSource('events'+(TOK?'?tok='+encodeURIComponent(TOK):''));
  es.onopen=function(){dot.classList.add('ok')};
  var seen={};
  es.onmessage=function(e){try{var ev=JSON.parse(e.data);
    if(ev.id!=null){if(seen[ev.id])return;seen[ev.id]=1;}
    render(ev);}catch(_){}};
  es.onerror=function(){dot.classList.remove('ok')};
}
// Ленивая история: страницы до histAnchor, живые события — после него.
// Кнопки нет: подход к верху сам догружает следующую порцию.
// Старые страницы вставляются ВЫШЕ уже вставленных (histTop), иначе порядок
// ходов переворачивается между страницами.
var anchor=document.getElementById('histAnchor');
var histCursor=-1,histLoading=false,histTop=null,HIST_PAGE=300;
function loadOlder(){
  if(histLoading||histCursor===0)return;
  histLoading=true;
  fetch('/history?before='+histCursor+'&limit='+HIST_PAGE+'&tok='+encodeURIComponent(TOK))
   .then(function(r){return r.json()})
   .then(function(d){
     histLoading=false;histCursor=d.cursor;
     var frag=document.createElement('div'),pv=out;out=frag;cur=null;
     d.events.forEach(function(e){try{render(e)}catch(_){}});
     cur=null;out=pv;
      var top0=document.documentElement.scrollHeight;
      out.insertBefore(frag,histTop||anchor);histTop=frag;
     var dh=document.documentElement.scrollHeight-top0;
     scrollBy(0,dh);
     if(d.cursor>0&&dh<1000)loadOlder();
   })
   .catch(function(){histLoading=false});
}
addEventListener('scroll',function(){if(scrollY<800)loadOlder()});
loadOlder();
connect();
</script></body></html>
"""


class WebMirror:
    """HTTP+SSE сервер зеркала. Запуск/остановка — из event loop приложения."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, on_change=None,
                 resolve_image=None, logo_path: str = "", theme: str = "night",
                 history_provider=None):
        self.host = host
        self.port = port
        self.token = secrets.token_urlsafe(6)
        self.url = ""
        # Тема страницы — та же, что выбрана в TUI (night/day/evening);
        # смена темы в TUI доходит до клиентов событием {t:"theme"}.
        self.theme = theme if theme in ("night", "day", "evening") else "night"
        # Вызывается из event loop при подключении/отключении браузера:
        # on_change(len(self._queues)) — для индикатора клиентов в шапке.
        self._on_change = on_change
        # resolve_image(image_id) -> (bytes, mime) | None — раздача картинок
        # сессии по маркерам [[image:<id>]].
        self._resolve_image = resolve_image
        # Приветственный логотип на странице (assets/logo.png).
        self._logo_path = logo_path
        # history_provider(before, limit) -> (events, cursor) — ленивые
        # страницы истории сессии; cursor 0 означает «старше ничего нет».
        self._history_provider = history_provider
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
        last_event_id = 0
        for ln in lines[1:]:
            low = ln.lower()
            if low.startswith("cookie:"):
                cookie = ln.split(":", 1)[1].strip()
            elif low.startswith("last-event-id:"):
                try:
                    last_event_id = int(ln.split(":", 1)[1].strip())
                except ValueError:
                    last_event_id = 0
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
                             _PAGE.replace("__THEME__", self.theme).encode(),
                             extra=f"Set-Cookie: {_COOKIE_NAME}={self.token}; Path=/; "
                                   f"HttpOnly; SameSite=Lax\r\nCache-Control: no-store\r\n")
            return
        if route == "/events":
            await self._sse(reader, writer, last_event_id)
            return
        if route == "/history":
            await self._history(writer, urlsplit(path).query)
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

    async def _history(self, writer, query: str) -> None:
        if self._history_provider is None:
            await self._send(writer, "200 OK", "application/json; charset=utf-8",
                             b'{"events": [], "cursor": 0}',
                             extra="Cache-Control: no-store\r\n")
            return
        qs = parse_qs(query)
        try:
            before = int((qs.get("before") or ["-1"])[0])
            limit = min(max(int((qs.get("limit") or ["30"])[0]), 1), 300)
        except ValueError:
            before, limit = -1, 30
        try:
            events, cursor = self._history_provider(before, limit)
        except Exception:
            events, cursor = [], 0
        body = json.dumps({"events": list(events), "cursor": cursor},
                          ensure_ascii=False).encode()
        await self._send(writer, "200 OK", "application/json; charset=utf-8", body,
                         extra="Cache-Control: no-store\r\n")

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

    @staticmethod
    def _event_id(s: str) -> int:
        try:
            return int(json.loads(s).get("id") or 0)
        except Exception:
            return 0

    @staticmethod
    def _frame(eid: int, s: str) -> bytes:
        # Строка id нужна, чтобы браузер при переподключении прислал
        # Last-Event-ID — сервер досылает только новые события, без дублей.
        head = f"id: {eid}\n".encode() if eid else b""
        return head + b"data: " + s.encode() + b"\n\n"

    async def _sse(self, reader, writer, last_id: int = 0) -> None:
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
                eid = self._event_id(s)
                if eid <= last_id:
                    continue
                writer.write(self._frame(eid, s))
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
                    writer.write(self._frame(self._event_id(s), s))
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
