#!/usr/bin/env python3
"""
web — единый добыватель данных из сети.

Один инструмент вместо четырёх (web_search, open_url, web_extract, curl).
Сам выбирает стратегию по типу данных и всегда подсказывает следующий шаг.

Действия (action):
  auto      — получить URL и выбрать стратегию по content-type (по умолчанию)
  open      — читаемый основной текст страницы (markdown)
  extract   — структура: links / images / headings / meta / tables / css
  json      — JSON: jq-фильтр или сводка по структуре
  download  — скачать файл (output_path или downloads/ сессии)
  search    — поиск в интернете (DuckDuckGo HTML, fallback lynx)
  help      — справка

Каждый ответ сопровождается харнесом: _meta (content-type, размер, время,
сохранённый путь), provenance, «Совет» и «Следующие шаги».

Старые инструменты (curl, web_extract, open_url, web_search) — тонкие обёртки
поверх этого ядра и продолжают работать.
"""

import hashlib
import json
import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

import httpx

try:
    from selectolax.parser import HTMLParser
except ImportError:  # pragma: no cover
    HTMLParser = None

try:
    from tools import download_manager as _dlm
except Exception:  # pragma: no cover
    _dlm = None


DEFAULT_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_PREVIEW_CHARS = 8_000
# Загрузка файлов не обрезается: лимит большой, при превышении — явная ошибка.
DOWNLOAD_MAX_BYTES = 200_000_000
SEARCH_URLS = (
    "https://html.duckduckgo.com/html/?q={q}",
    "https://duckduckgo.com/html/?q={q}",
)
SAFE_EXTRACT = ("links", "images", "headings", "meta", "tables", "all")

_JQ_DANGEROUS = (
    r'@\s*\w+\s*"',   # @base64 "file", @uri "file" и т.п.
    r'\$\w+\s*>',     # перенаправление в файл
    r'\|\s*tee',      # tee
)


# --------------------------------------------------------------------------
# Конфиг и утилиты
# --------------------------------------------------------------------------

def _config():
    import configparser
    cfg = {"user_agent": DEFAULT_UA, "max_chars": DEFAULT_PREVIEW_CHARS,
           "connect_timeout": 6, "read_timeout": 10}
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.cfg")
    try:
        parser = configparser.ConfigParser()
        if os.path.exists(path):
            parser.read(path, encoding="utf-8")
        cfg["user_agent"] = parser.get("Tools", "LynxUserAgent", fallback=DEFAULT_UA)
        cfg["max_chars"] = parser.getint("Tools", "LynxMaxChars", fallback=DEFAULT_PREVIEW_CHARS)
        cfg["connect_timeout"] = parser.getint("Tools", "LynxConnectTimeout", fallback=6)
        cfg["read_timeout"] = parser.getint("Tools", "LynxReadTimeout", fallback=10)
    except Exception:
        pass
    return cfg


def _human_size(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def _escape(text: str, limit: int = 300) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit] + "…" if len(text) > limit else text


def _build_headers(headers) -> Dict[str, str]:
    h = {"User-Agent": _config()["user_agent"],
         "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
         "Accept-Language": "en-US,en;q=0.5"}
    if isinstance(headers, dict):
        h.update({str(k): str(v) for k, v in headers.items()})
    elif isinstance(headers, (list, tuple)):
        for item in headers:
            if isinstance(item, dict):
                h.update({str(k): str(v) for k, v in item.items()})
            elif isinstance(item, str) and ":" in item:
                k, v = item.split(":", 1)
                h[k.strip()] = v.strip()
    return h


def _image_rank(url: str) -> int:
    """Чем меньше — тем больше похоже на настоящую фотографию.

    Иконки/логотипы/статические ресурсы получают больший вес и уезжают в конец
    списка, чтобы модель первой видела фотографии, а не SVG-логотипы.
    """
    try:
        ext = os.path.splitext(urlparse(url).path)[1].lower()
    except Exception:
        ext = ""
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        rank = 0
    elif ext == ".svg":
        rank = 3
    else:
        rank = 1
    low = url.lower()
    for marker in ("/static/", "logo", "icon", "wordmark", "sprite",
                   "favicon", "badge", "avatar"):
        if marker in low:
            rank += 5
    return rank


# --------------------------------------------------------------------------
# Харнес (по образцу архивариуса session_memory)
# --------------------------------------------------------------------------

def _harness(meta: Dict, provenance: str, advice: str,
             next_actions: List[str]) -> str:
    line = " | ".join(f"{k}={v}" for k, v in meta.items() if v not in (None, "", []))
    out = [f"🧭 web · {line}", f"provenance={provenance}"]
    if advice:
        out.append(f"💡 Совет: {advice}")
    if next_actions:
        out.append("➡ Следующие шаги (web):")
        out.extend(f"   • {a}" for a in next_actions)
    return "\n".join(out)


def _finish(body: str, meta: Dict, provenance: str, advice: str,
            next_actions: List[str]) -> str:
    parts = [body.rstrip()] if body else []
    parts.append("")
    parts.append("────────────────────────────")
    parts.append(_harness(meta, provenance, advice, next_actions))
    return "\n".join(parts)


def _help() -> str:
    return (
        "🧭 web — единый добыватель данных из сети.\n"
        "\n"
        "Действия:\n"
        "  web action=auto url=…                     — сам выберет стратегию\n"
        "  web action=open url=…                     — читаемый текст страницы\n"
        "  web action=extract url=… extract=[links,tables] — структура\n"
        "  web action=json url=… jq=\".daily\"        — JSON + фильтр\n"
        "    jq применяется к входу '.': '.items[] | .name',\n"
        "    условие: '.items[] | select(.time | startswith(\"2026\"))'\n"
        "  web action=download url=… [output_path=…] — скачать файл (aria2c, докачка)\n"
        "    большие файлы (ISO) и торренты: url=https://….torrent или url=magnet:?…\n"
        "    resume=true — докачать/перекачать; если файл уже цел — вернётся из памяти\n"
        "    expected_sha256=… — проверка хеша (при несовпадении файл удаляется)\n"
        "  web action=downloads                      — память загрузок: что/куда/целое\n"
        "  web action=search query=\"…\"               — поиск в интернете\n"
        "  web action=help                           — эта справка\n"
        "\n"
        "Общее: headers, timeout_sec, max_bytes, follow_redirects, session_path.\n"
        "Запись вне папки сессии требует dangerous mode.\n"
        "Память загрузок глобальна (~/.botinok/downloads/history.json) и не зависит от сессии.\n"
        "Старые имена (web_search, open_url, web_extract, curl) работают как алиасы.\n"
    )


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _fetch(url: str, headers, timeout_sec: int, max_bytes: int,
           follow_redirects: bool) -> Tuple[bytes, str, str, int, bool]:
    """GET с ограничением размера. -> raw, final_url, content_type, status, truncated."""
    hdrs = _build_headers(headers)
    timeout = httpx.Timeout(connect=min(timeout_sec, 60) or 10,
                            read=max(timeout_sec or 10, 10),
                            write=10, pool=10)
    with httpx.Client(follow_redirects=follow_redirects, timeout=timeout) as client:
        with client.stream("GET", url, headers=hdrs) as resp:
            chunks: List[bytes] = []
            total = 0
            truncated = False
            for chunk in resp.iter_bytes():
                if total + len(chunk) > max_bytes:
                    chunks.append(chunk[:max_bytes - total])
                    truncated = True
                    break
                chunks.append(chunk)
                total += len(chunk)
            raw = b"".join(chunks)
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            return raw, str(resp.url), ctype, resp.status_code, truncated


def _kind(content_type: str, raw: bytes) -> str:
    ct = content_type.lower()
    if "json" in ct:
        return "json"
    if "html" in ct or "xhtml" in ct:
        return "html"
    if "xml" in ct:
        return "text"
    if ct.startswith("text/"):
        return "text"
    head = raw[:256].lstrip()
    if head[:1] in (b"{", b"["):
        try:
            json.loads(raw.decode("utf-8", errors="replace"))
            return "json"
        except Exception:
            pass
    if head[:1] == b"<":
        return "html"
    try:
        sample = raw[:256].decode("utf-8")
        if all(ord(c) < 128 or c in "\t\n\r" for c in sample[:200]):
            return "text"
    except Exception:
        pass
    return "binary"


def _server_reason(raw: bytes) -> str:
    """Достать человекочитаемую причину из тела ошибки."""
    if not raw:
        return ""
    body = raw.decode("utf-8", errors="replace").strip()[:600]
    if not body:
        return ""
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            for key in ("reason", "error", "message", "detail", "error_description"):
                val = data.get(key)
                if val:
                    if isinstance(val, (dict, list)):
                        return _escape(json.dumps(val, ensure_ascii=False), 300)
                    return _escape(val, 300)
        return _escape(body, 300)
    except Exception:
        return _escape(body, 300)


def _query_params(url: str) -> Dict[str, str]:
    """Разобрать query-параметры URL в {имя: значение}."""
    try:
        query = urlparse(url).query
        return {k: (v[0] if v else "") for k, v in parse_qs(query, keep_blank_values=True).items()}
    except Exception:
        return {}


def _params_named_in_reason(url: str, reason: str) -> List[str]:
    """Параметры URL, чьи имена упомянуты в тексте ошибки сервера."""
    if not reason:
        return []
    low = reason.lower()
    return [name for name in _query_params(url) if name and name.lower() in low]


# Процент-экранирования, декодирование которых не меняет структуру query
# (не трогаем &, =, #, ? и т.п.). Это беззнаковая, безопасная правка.
_SAFE_DECODE = {"%2f": "/", "%3a": ":", "%2c": ",", "%40": "@"}


def _decode_safe_escapes(url: str) -> Optional[str]:
    low = url.lower()
    if not any(code in low for code in _SAFE_DECODE):
        return None
    out = url
    for code, ch in _SAFE_DECODE.items():
        out = re.sub(code, ch, out, flags=re.IGNORECASE)
    return out if out != url else None


def _strip_params(url: str, names: List[str]) -> Optional[str]:
    """Вернуть URL без указанных query-параметров (по имени)."""
    if not names:
        return None
    try:
        parts = urlparse(url)
        kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k not in names]
        if len(kept) == len(parse_qsl(parts.query, keep_blank_values=True)):
            return None
        new_query = urlencode(kept, doseq=True)
        return urlunparse(parts._replace(query=new_query))
    except Exception:
        return None


def _http_error(status: int, url: str, raw: bytes = b"") -> str:
    hints = {
        400: "сервер назвал причину в 'Ответ сервера' — поправь значение или параметр",
        401: "нужна авторизация (headers=[\"Authorization: Bearer …\"])",
        403: "добавь headers=[\"User-Agent: …\"] или проверь доступ",
        404: "проверь URL (возможно, ресурс переехал)",
        429: "слишком много запросов — подожди или смени источник",
        500: "ошибка на стороне сервера — попробуй позже",
    }
    parts = [f"❌ HTTP {status}: {url}"]
    reason = _server_reason(raw)
    if reason:
        parts.append(f"Ответ сервера: {reason}")
    parts.append(f"💡 Совет: {hints.get(status, 'проверь URL и headers')}")
    if status == 400 and any(code in url.lower() for code in _SAFE_DECODE):
        parts.append("В URL есть процент-экранирование — можно попробовать "
                     "декодировать такие символы (беззнаковая правка).")
    offenders = _params_named_in_reason(url, reason)
    if offenders:
        parts.append("Сервер называет параметр(ы): " + ", ".join(offenders) +
                     " — проверь их значения (допустимый формат/значения из "
                     "документации API).")
    return "\n".join(parts)


def _repair_url(url: str) -> Tuple[Optional[str], str]:
    """Беззнаковый ремонт URL: декодировать безопасные процент-экранирования.

    Семантические замены (какие значения принимает конкретный API) НЕ
    зашиваются в код — инструмент лишь показывает названный сервером параметр
    и предлагает варианты в «Следующих шагах».
    """
    fixed = _decode_safe_escapes(url)
    if fixed:
        return fixed, "decoded escapes"
    return None, ""


def _save_bytes(raw: bytes, output_path: Optional[str], session_path: Optional[str],
                url: str) -> Tuple[Optional[str], str]:
    """Сохранить bytes; вернуть (path, type). Для binary без пути — в downloads/."""
    path = output_path
    if not path and session_path:
        parsed = urlparse(url)
        fname = os.path.basename(parsed.path) or "download"
        fname = re.sub(r"[^\w.-]", "_", fname)[:100] or "download"
        for magic, ext in ((b"\x89PNG", ".png"), (b"\xff\xd8", ".jpg"),
                           (b"%PDF", ".pdf"), (b"PK\x03\x04", ".zip"),
                           (b"GIF8", ".gif"), (b"\x1f\x8b", ".gz")):
            if raw[:len(magic)] == magic and not fname.endswith(ext):
                fname += ext
                break
        path = os.path.join(session_path, "downloads", fname)
    if not path:
        return None, "unknown"
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw)
    ftype = "file"
    try:
        r = subprocess.run(["file", "-b", path], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            ftype = r.stdout.strip()
    except Exception:
        pass
    return path, ftype


# --------------------------------------------------------------------------
# Загрузка файлов: aria2c + история/докачка
# --------------------------------------------------------------------------

def _file_type(path: str) -> str:
    """Определить тип файла утилитой file (как делал старый curl)."""
    if not path or not os.path.exists(path):
        return "отсутствует"
    try:
        r = subprocess.run(["file", "-b", path], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _looks_like_html_doc(raw: bytes) -> bool:
    head = (raw[:1024] or b"").lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _aria2c_available() -> bool:
    try:
        return subprocess.run(["aria2c", "--version"], capture_output=True,
                              timeout=5).returncode == 0
    except Exception:
        return False


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def _is_torrent(url: str) -> bool:
    low = url.lower()
    return low.startswith("magnet:") or urlparse(low).path.endswith(".torrent")


def _destination(url: str, output_path: Optional[str], session_path: Optional[str]) -> Optional[str]:
    if output_path:
        return output_path
    if not session_path:
        return None
    parsed = urlparse(url)
    if url.lower().startswith("magnet:"):
        # Имя из magnet-ссылки (dn) или запасное.
        qs = parse_qs(parsed.query)
        fname = (qs.get("dn") or ["torrent"])[0]
    elif urlparse(url).path.lower().endswith(".torrent"):
        fname = os.path.basename(parsed.path) or "torrent"
    else:
        fname = os.path.basename(parsed.path) or "download"
    fname = re.sub(r"[^\w.-]", "_", fname)[:100] or "download"
    return os.path.join(session_path, "downloads", fname)


def _aria2c_download(url: str, dest: str, headers, timeout_sec: int) -> Tuple[bool, str]:
    """Скачать/докачать файл (или торрент) aria2c. -> (ok, error)."""
    torrent = _is_torrent(url)
    if torrent:
        work_dir = dest if os.path.isdir(dest) else (os.path.dirname(dest) or ".")
    else:
        work_dir = os.path.dirname(dest) or "."
    os.makedirs(work_dir, exist_ok=True)
    cmd = [
        "aria2c", "--continue=true", "--allow-overwrite=true",
        "--auto-file-renaming=false", "--file-allocation=none",
        "--max-connection-per-server=4", "-s", "4", "-k", "1M",
        "--min-split-size=4M",  # мелкие файлы качаем одним соединением (меньше 429)
        "--max-tries=5", "--retry-wait=2", "--summary-interval=0",
        "--console-log-level=warn", "--show-console-readout=false",
        f"--connect-timeout={min(max(timeout_sec, 5), 60)}",
        f"--timeout={min(max(timeout_sec, 5), 120)}",
        "-d", work_dir,
    ]
    if torrent:
        cmd.append("--seed-time=0")  # не раздаём после завершения
    else:
        cmd.extend(["-o", os.path.basename(dest)])
    for k, v in _build_headers(headers).items():
        cmd.append(f"--header={k}: {v}")
    cmd.append(url)
    # Большие файлы/раздачи: жёсткий лимит до 6 часов.
    hard_timeout = min(max(timeout_sec, 30) * 720, 21600)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=hard_timeout)
    except subprocess.TimeoutExpired:
        return False, "aria2c timeout"
    if r.returncode != 0:
        msg = _strip_ansi(r.stderr or r.stdout or "aria2c error").strip()
        lines = [ln for ln in msg.splitlines() if ln.strip() and "CUID#" not in ln]
        return False, " | ".join(lines[-3:])[:400]
    if torrent:
        if not os.path.isdir(work_dir) or not any(os.scandir(work_dir)):
            return False, "торрент не создал файлов"
    elif not os.path.exists(dest):
        return False, "aria2c не создал файл"
    return True, ""


def _download_file(url: str, dest: str, headers, timeout_sec: int,
                   resume: bool = False) -> Tuple[bool, str, str]:
    """Скачать файл надёжно. -> (ok, error, engine).

    aria2c, если доступен (умеет докачку), иначе httpx без обрезки.
    """
    if _aria2c_available():
        ok, err = _aria2c_download(url, dest, headers, timeout_sec)
        return ok, err, "aria2c"
    try:
        with httpx.Client(follow_redirects=True,
                          timeout=httpx.Timeout(connect=15, read=max(timeout_sec, 30),
                                                write=30, pool=15)) as client:
            with client.stream("GET", url, headers=_build_headers(headers)) as resp:
                if resp.status_code >= 400:
                    body = b"".join(resp.iter_bytes())[:600]
                    return False, f"HTTP {resp.status_code}: {_server_reason(body)}", "httpx"
                with open(dest, "wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
        return True, "", "httpx"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", "httpx"


def _torrent_files(dest: str, limit: int = 20) -> List[str]:
    out = []
    try:
        for root, _dirs, names in os.walk(dest):
            for n in names:
                out.append(os.path.join(root, n))
                if len(out) >= limit:
                    return out
    except Exception:
        pass
    return out


def _do_download(url: str, output_path: Optional[str], headers, timeout_sec: int,
                 session_path: Optional[str], resume: bool = False,
                 expected_sha256: Optional[str] = None) -> str:
    """Скачать файл (или торрент), проверить тип/хеш/целостность, записать в историю."""
    torrent = _is_torrent(url)
    dest = _destination(url, output_path, session_path)
    if not dest:
        return _finish("❌ Не указан output_path и нет session_path для автосохранения.",
                       {"action": "download"}, "error",
                       "укажи output_path (внутри сессии)", [])
    if torrent:
        # Для торрентов/многофайловых раздач dest — каталог.
        if output_path and os.path.isdir(output_path):
            dest = output_path
        elif not os.path.isdir(dest):
            dest = os.path.dirname(dest) or dest
    started = time.time()

    # Уже скачано и целое — не качаем повторно (если не просят resume).
    prev = _dlm.find(session_path, url, dest) if _dlm else None
    if prev and prev.get("status") == "completed" and not resume:
        ok, _reason = _dlm.verify(prev)
        if ok:
            if torrent:
                files = _torrent_files(dest)
                listing = "\n".join(f"• {os.path.relpath(f, dest)}" for f in files[:10])
                return _finish(f"✅ Уже скачано ранее (торрент): {dest}\n{listing}",
                               {"action": "download", "saved": dest, "cached": "yes"},
                               "saved", "раздача уже на диске", [])
            return _finish(
                f"✅ Уже скачано ранее: {dest}\n📝 {_file_type(dest)}\n"
                f"📊 {_human_size(os.path.getsize(dest))}",
                {"action": "download", "saved": dest, "cached": "yes"}, "saved",
                "файл целый; при необходимости перекачай (resume=true)",
                [f'web action=download url="{url}" output_path="{dest}" resume=true'])

    if _dlm:
        _dlm.record(session_path, url, dest, "in_progress",
                    engine="aria2c" if _aria2c_available() else "httpx")

    ok, err, engine = _download_file(url, dest, headers, timeout_sec, resume)
    elapsed = f"{time.time() - started:.2f}s"

    if not ok:
        # Если осталась частичная загрузка — фиксируем «недокачано» для resume.
        partial = (not torrent and os.path.exists(dest)
                   and os.path.isfile(dest) and os.path.getsize(dest) > 0)
        status = "incomplete" if partial else "error"
        got = f"\n📊 Уже получено: {_human_size(os.path.getsize(dest))}" if partial else ""
        if _dlm:
            _dlm.record(session_path, url, dest, status, error=err, engine=engine)
        return _finish(f"❌ Не скачано: {dest}\n{err}{got}",
                       {"action": "download", "status": status}, "error",
                       "повтори с resume=true — докачает с места обрыва",
                       [f'web action=download url="{url}" output_path="{dest}" resume=true'])

    # Торрент: отчитываемся содержимым каталога, sha не считаем.
    if torrent:
        files = _torrent_files(dest)
        if not files:
            if _dlm:
                _dlm.record(session_path, url, dest, "error",
                            error="раздача пуста", engine=engine)
            return _finish(f"❌ Раздача не создала файлов в {dest}",
                           {"action": "download", "status": "error"}, "error",
                           "повтори позже/проверь magnet", [])
        total = sum(os.path.getsize(f) for f in files if os.path.isfile(f))
        listing = "\n".join(f"• {os.path.relpath(f, dest)}" for f in files[:15])
        if _dlm:
            _dlm.record(session_path, url, dest, "completed", total=None,
                        file_type="BitTorrent", engine=engine)
        return _finish(
            f"✅ Раздача скачана: {url}\n📁 Каталог: {dest}\n"
            f"📦 Файлов: {len(files)} ({_human_size(total)})\n{listing}",
            {"action": "download", "saved": dest, "files": len(files),
             "size": _human_size(total), "elapsed": elapsed, "engine": engine},
            "saved", "торрент раздан; файлы в каталоге сессии", [])

    # Проверка: не HTML-заглушка ли вместо файла (rate-limit/капча/редирект).
    with open(dest, "rb") as f:
        head = f.read(1024)
    if _looks_like_html_doc(head):
        try:
            os.remove(dest)
        except Exception:
            pass
        if _dlm:
            _dlm.record(session_path, url, dest, "error",
                        error="вместо файла HTML", engine=engine)
        snippet = head.decode("utf-8", errors="replace").strip()[:200]
        return _finish(
            f"❌ Вместо файла пришёл HTML (похоже на ошибку/капчу/редирект):\n{snippet}",
            {"action": "download", "status": "error"}, "error",
            "подожди/смени источник; файл не сохранён",
            [f'web action=download url="{url}" output_path="{dest}" resume=true'])

    size = os.path.getsize(dest)
    sha = ""
    try:
        with open(dest, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        pass
    if expected_sha256:
        want = expected_sha256.strip().lower()
        if sha.lower() != want:
            try:
                os.remove(dest)
            except Exception:
                pass
            if _dlm:
                _dlm.record(session_path, url, dest, "error",
                            sha256=sha, error="sha256 не совпадает", engine=engine)
            return _finish(
                f"❌ sha256 не совпадает — файл удалён.\nОжидалось: {want}\nПолучено: {sha}",
                {"action": "download", "status": "error"}, "error",
                "проверь URL/источник; файл не сохранён",
                [f'web action=download url="{url}" output_path="{dest}" resume=true'])
    ftype = _file_type(dest)
    if _dlm:
        _dlm.record(session_path, url, dest, "completed", total=size,
                    sha256=sha, file_type=ftype, engine=engine)
    return _finish(
        f"✅ Скачано: {url}\n📁 Файл: {dest}\n📊 {_human_size(size)}\n"
        f"📝 {ftype}\n🔐 {sha}",
        {"action": "download", "saved": dest, "size": _human_size(size),
         "elapsed": elapsed, "engine": engine},
        "saved", "файл в папке сессии", [])


def _action_downloads(session_path: Optional[str], limit: int = 50) -> str:
    """История загрузок web (глобальная) + проверка наличия и типа файлов."""
    if not _dlm:
        return _finish("❌ Менеджер загрузок недоступен.", {}, "error", "", [])
    entries = _dlm.list_entries(session_path)
    if not entries:
        return _finish("📥 История загрузок пуста.", {"action": "downloads"}, "extracted",
                       "скачай что-нибудь через web action=download",
                       ['web action=download url="…"'])
    entries.sort(key=lambda e: e.get("updated", ""), reverse=True)
    lines = [f"📥 История загрузок web ({len(entries)}):", ""]
    pending = []
    for e in entries[:limit]:
        ok, reason = _dlm.verify(e)
        exists = os.path.exists(e.get("dest") or "")
        ftype = _file_type(e["dest"]) if exists else "отсутствует"
        mark = "✅" if ok else ("⏳" if exists else "❌")
        sha = (e.get("sha256") or "")[:12]
        lines.append(f"{mark} {e.get('status', '?')} | {e.get('updated', '')} | "
                     f"{_human_size(e.get('total') or 0)} | sha256:{sha or '—'}")
        lines.append(f"   {ftype}")
        lines.append(f"   {e.get('dest')}")
        lines.append(f"   {e.get('url')}")
        if not ok:
            lines.append(f"   ⚠️ {reason}")
            pending.append(e)
    nxt = []
    for e in pending[:5]:
        nxt.append(f'web action=download url="{e.get("url")}" '
                   f'output_path="{e.get("dest")}" resume=true')
    if not pending:
        nxt.append("web action=help")
    return _finish("\n".join(lines), {"action": "downloads", "count": len(entries)},
                   "extracted",
                   f"незавершённых: {len(pending)} — докачай через resume=true", nxt)


# --------------------------------------------------------------------------
# HTML: читаемый текст и структура
# --------------------------------------------------------------------------

def _html_to_markdown(html_text: str) -> str:
    if HTMLParser is None:
        return re.sub(r"<[^>]+>", " ", html_text)
    tree = HTMLParser(html_text)
    for sel in ("script", "style", "noscript", "nav", "header", "footer",
                "aside", "form", "svg", "iframe"):
        for node in tree.css(sel):
            try:
                node.decompose()
            except Exception:
                pass
    root = tree.css_first("article") or tree.css_first("main") or tree.body or tree.root
    if root is None:
        return ""
    parts: List[str] = []
    for node in root.css("h1,h2,h3,h4,h5,h6,p,li,pre,blockquote"):
        text = node.text(separator=" ", strip=True)
        if not text:
            continue
        tag = (node.tag or "").lower()
        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            parts.append("#" * int(tag[1]) + " " + text)
        elif tag == "li":
            parts.append("- " + text)
        elif tag == "pre":
            parts.append("```\n" + text + "\n```")
        elif tag == "blockquote":
            parts.append("> " + text)
        else:
            parts.append(text)
    text = "\n\n".join(parts)
    if not text:
        text = (root.text(separator="\n", strip=True) or "").strip()
    return text


def _extract_structure(html_text: str, base_url: str, want: List[str],
                       max_items: int, css: Optional[List[str]] = None) -> Tuple[str, int]:
    if HTMLParser is None:
        return "❌ selectolax не установлен", 0
    tree = HTMLParser(html_text)
    want_all = "all" in want
    out: List[str] = []
    total = 0

    if css:
        out.append("## 🎯 CSS")
        out.append("")
        for sel in css:
            try:
                nodes = tree.css(sel)
            except Exception as e:
                out.append(f"- `{sel}` — ошибка селектора: {e}")
                continue
            out.append(f"### `{sel}` — {len(nodes)}")
            for node in nodes[:max_items]:
                txt = _escape(node.text(separator=" ", strip=True), 200)
                if txt:
                    out.append(f"- {txt}")
            total += len(nodes[:max_items])
        out.append("")

    if want_all or "meta" in want:
        meta = []
        title = tree.css_first("title")
        if title and title.text(strip=True):
            meta.append(("title", title.text(strip=True)))
        for node in tree.css("meta[name], meta[property]"):
            name = (node.attributes.get("name") or node.attributes.get("property") or "").strip()
            content = (node.attributes.get("content") or "").strip()
            if name and content:
                meta.append((name, content))
        if meta:
            out.append("## 📋 Meta")
            out.append("")
            for name, content in meta[:max_items]:
                out.append(f"- **{name}:** {_escape(content)}")
            out.append("")
            total += len(meta[:max_items])

    if want_all or "headings" in want:
        heads = []
        for level in range(1, 7):
            for node in tree.css(f"h{level}"):
                txt = node.text(strip=True)
                if txt:
                    heads.append((level, txt))
        if heads:
            out.append("## 📑 Headings")
            out.append("")
            for level, txt in heads[:max_items]:
                out.append("  " * (level - 1) + f"- **H{level}:** {_escape(txt, 200)}")
            out.append("")
            total += len(heads[:max_items])

    if want_all or "links" in want:
        seen = set()
        links = []
        for node in tree.css("a[href]"):
            href = (node.attributes.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full = urljoin(base_url, href)
            if full in seen:
                continue
            seen.add(full)
            links.append((_escape(node.text(strip=True) or "[no text]", 80), full))
        if links:
            out.append("## 🔗 Links")
            out.append("")
            for text, full in links[:max_items]:
                out.append(f"- [{text}]({full})")
            out.append("")
            total += len(links[:max_items])

    if want_all or "images" in want:
        seen = set()
        images = []
        seen_img = set()

        def _add_image(raw_ref: str, caption: str = "") -> None:
            ref = (raw_ref or "").strip()
            if not ref or ref.startswith("data:"):
                return
            # srcset: берём первый URL (обычно самый крупный/подходящий вариант).
            if "," in ref and " " in ref:
                ref = ref.split(",")[0].strip().split(" ")[0]
            full = urljoin(base_url, ref)
            if full in seen_img or full.startswith(("#", "javascript:")):
                return
            seen_img.add(full)
            images.append((_escape(caption or "[no caption]", 100), full))

        # Обычные <img>: src + ленивые атрибуты + srcset.
        for node in tree.css("img"):
            attrs = node.attributes
            cap = (attrs.get("alt") or attrs.get("title") or "").strip()
            for key in ("src", "data-src", "data-original", "data-lazy-src",
                        "data-srcset", "srcset"):
                if attrs.get(key):
                    _add_image(attrs.get(key), cap)
        # <source srcset> (picture)
        for node in tree.css("source[srcset], source[data-srcset]"):
            _add_image(node.attributes.get("srcset") or node.attributes.get("data-srcset"), "")
        # og:image / twitter:image
        for node in tree.css("meta[property], meta[name]"):
            key = (node.attributes.get("property") or node.attributes.get("name") or "").lower()
            if key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
                _add_image(node.attributes.get("content") or "", "")

        if images:
            # Сначала вероятные фотографии, иконки/логотипы — в конец.
            images.sort(key=lambda item: _image_rank(item[1]))
            out.append("## 🖼️ Images")
            out.append("")
            for cap, full in images[:max_items]:
                out.append(f"- {cap}: `{full}`")
            out.append("")
            total += len(images[:max_items])

    if want_all or "tables" in want:
        tables = []
        for table in tree.css("table"):
            headers, rows = [], []
            thead = table.css_first("thead")
            if thead:
                headers = [th.text(strip=True) for th in thead.css("th") if th.text(strip=True)]
            if not headers:
                first = table.css_first("tr")
                if first:
                    headers = [c.text(strip=True) for c in first.css("th, td") if c.text(strip=True)]
            tbody = table.css_first("tbody") or table
            start = 0 if thead else 1
            for i, row in enumerate(tbody.css("tr")):
                if i < start:
                    continue
                cells = [_escape(c.text(strip=True), 100) for c in row.css("td, th")]
                if any(cells):
                    rows.append(cells)
            if headers or rows:
                tables.append((headers, rows))
        if tables:
            out.append("## 📊 Tables")
            out.append("")
            for idx, (headers, rows) in enumerate(tables[:max_items], 1):
                out.append(f"### Table {idx}")
                if headers:
                    out.append("| " + " | ".join(headers) + " |")
                    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for row in rows[:20]:
                    if headers and len(row) < len(headers):
                        row = row + [""] * (len(headers) - len(row))
                    out.append("| " + " | ".join(row) + " |")
                if len(rows) > 20:
                    out.append(f"*… ещё {len(rows) - 20} строк*")
                out.append("")
            total += len(tables[:max_items])

    return "\n".join(out).strip(), total


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------

def _run_jq(text: str, jq_filter: str) -> Tuple[Optional[str], Optional[str]]:
    jq_filter = (jq_filter or "").strip()
    if not jq_filter:
        return None, None
    for pat in _JQ_DANGEROUS:
        if re.search(pat, jq_filter):
            return None, "jq-фильтр содержит небезопасную операцию записи"
    if not jq_filter.startswith((".", "[", "{")):
        keywords = ("def ", "import ", "include ", "module ", "as ",
                    "if ", "reduce ", "foreach ")
        if not any(jq_filter.startswith(k) for k in keywords):
            jq_filter = "." + jq_filter
    try:
        res = subprocess.run(["jq", "-r", jq_filter], input=text, capture_output=True,
                             text=True, timeout=15)
    except FileNotFoundError:
        return None, "jq не установлен — верну сводку без фильтра"
    except subprocess.TimeoutExpired:
        return None, "jq timeout"
    if res.returncode != 0:
        err = (res.stderr or "").strip()[:200]
        hint = ("Проверь синтаксис jq: фильтр применяется к входу '.'; "
                "для условия — '.items[] | select(.time | startswith(\"x\"))'; "
                "после 'as $x |' вход не меняется. Упрости фильтр ('.daily') "
                "или запроси данные без jq.")
        return None, f"jq error: {err}\n💡 {hint}"
    return res.stdout, None


def _json_summary(text: str, max_items: int = 5) -> str:
    try:
        data = json.loads(text)
    except Exception as e:
        return f"не удалось разобрать JSON: {e}"
    lines = []
    if isinstance(data, dict):
        lines.append(f"Объект, ключей: {len(data)}")
        for k, v in list(data.items())[:max_items * 3]:
            if isinstance(v, list):
                lines.append(f"  • {k}: list[{len(v)}]" + (f" — пример: {_escape(json.dumps(v[0], ensure_ascii=False), 120)}" if v else ""))
            elif isinstance(v, dict):
                lines.append(f"  • {k}: object, ключей {len(v)}")
            else:
                lines.append(f"  • {k}: {_escape(v, 80)}")
    elif isinstance(data, list):
        lines.append(f"Массив, элементов: {len(data)}")
        for item in data[:max_items]:
            lines.append(f"  • {_escape(json.dumps(item, ensure_ascii=False), 160)}")
    else:
        lines.append(_escape(json.dumps(data, ensure_ascii=False), 200))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Поиск
# --------------------------------------------------------------------------

def _parse_ddg_html(html_text: str, max_items: int) -> List[Dict[str, str]]:
    if HTMLParser is None:
        return []
    tree = HTMLParser(html_text)
    results = []
    seen = set()
    for node in tree.css("div.result, div.web-result"):
        a = node.css_first("a.result__a")
        if not a:
            continue
        href = a.attributes.get("href", "") or ""
        if href.startswith("//duckduckgo.com/l/") or "duckduckgo.com/l/" in href:
            try:
                q = parse_qs(urlparse("https:" + href if href.startswith("//") else href).query)
                href = (q.get("uddg") or [href])[0]
            except Exception:
                pass
        if not href.startswith(("http://", "https://")) or href in seen:
            continue
        seen.add(href)
        sn = node.css_first("a.result__snippet") or node.css_first(".result__snippet")
        results.append({
            "title": (a.text(strip=True) or href)[:200],
            "url": href,
            "snippet": _escape(sn.text(separator=" ", strip=True) if sn else "", 240),
        })
        if len(results) >= max_items:
            break
    return results


def _search_lynx(query: str, timeout_sec: int, max_chars: int) -> Optional[str]:
    encoded = quote(query)
    for tmpl in SEARCH_URLS:
        url = tmpl.format(q=encoded)
        try:
            res = subprocess.run(
                ["lynx", "-dump", "-number_links", "-display_charset=utf-8",
                 f"-connect_timeout={min(timeout_sec, 60)}",
                 f"-read_timeout={min(timeout_sec, 120)}", url],
                capture_output=True, text=True, timeout=min(timeout_sec + 10, 130),
            )
        except Exception:
            continue
        if res.returncode == 0 and res.stdout and len(res.stdout.strip()) > 100:
            lines = [ln for ln in res.stdout.split("\n") if ln.strip()]
            return "\n".join(lines)[:max_chars]
    return None


def _action_search(query: str, headers, timeout_sec: int, max_bytes: int,
                   max_items: int) -> Tuple[str, List[str]]:
    cfg = _config()
    results: List[Dict[str, str]] = []
    try:
        raw, final_url, ctype, status, _ = _fetch(
            SEARCH_URLS[0].format(q=quote(query)), headers, timeout_sec, max_bytes, True)
        if status < 400 and raw:
            results = _parse_ddg_html(raw.decode("utf-8", errors="replace"), max_items)
    except Exception:
        results = []
    if not results:
        # fallback: lynx
        text = _search_lynx(query, timeout_sec, cfg["max_chars"])
        if text:
            return text, [
                f'web action=open url="<ссылка из результата>"',
                f'web action=search query="{_escape(query, 60)}"',
            ]
        return ("❌ Поиск не дал результатов (DuckDuckGo недоступен или заблокировал).",
                ['web action=open url="<прямая ссылка>"'])
    lines = [f"🔎 {query} — {len(results)} результатов", ""]
    nxt = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
    if results:
        nxt.append(f'web action=open url="{results[0]["url"]}"')
        nxt.append(f'web action=open url="{results[1]["url"]}"' if len(results) > 1 else
                   f'web action=search query="{_escape(query, 60)}"')
    return "\n".join(lines), nxt


# --------------------------------------------------------------------------
# Основной вход
# --------------------------------------------------------------------------

def _go(url: str, action: str, extract, css, jq_filter, output_path, headers,
        timeout_sec, max_bytes, follow_redirects, max_items, session_path,
        resume: bool = False, expected_sha256: Optional[str] = None) -> str:
    if not url or not str(url).strip():
        return _finish("❌ Не указан url.",
                       {"action": action}, "error",
                       "укажи url или используй action=search query=…", [])
    url = str(url).strip()
    is_magnet = url.lower().startswith("magnet:")
    if is_magnet and action in ("auto", "download"):
        action = "download"
    if not url.startswith(("http://", "https://")) and not (action == "download" and is_magnet):
        return _finish(f"❌ URL должен начинаться с http:// или https://: {url[:80]}",
                       {"action": action}, "error",
                       "проверь схему URL (адрес без схемы попробуй через https://)", [])

    # Скачивание — отдельный надёжный путь (aria2c, докачка, проверка типа/хеша).
    if action == "download":
        return _do_download(url, output_path, headers, timeout_sec, session_path,
                            resume, expected_sha256)

    started = time.time()

    def _try(u):
        return _fetch(u, headers, timeout_sec, max_bytes, follow_redirects)

    try:
        raw, final_url, ctype, status, truncated = _try(url)
    except httpx.TimeoutException:
        return _finish(f"❌ Таймаут ({timeout_sec}с): {url}",
                       {"action": action}, "error",
                       "увеличь timeout_sec", [])
    except httpx.RequestError as e:
        return _finish(f"❌ Ошибка запроса: {e}",
                       {"action": action}, "error",
                       "проверь URL/сеть", [])
    except Exception as e:
        return _finish(f"❌ Ошибка: {type(e).__name__}: {e}",
                       {"action": action}, "error", "проверь URL", [])

    # Беззнаковый авто-ремонт: декодируем безопасные процент-экранирования и
    # повторяем запрос один раз. Семантические замены значений не делаются —
    # они предлагаются модели в «Следующих шагах» по тексту ошибки сервера.
    fixed_note = ""
    if status >= 400:
        # 1) Беззнаковая правка: декодировать безопасные процент-экранирования.
        fixed_url, note = _repair_url(url)
        if fixed_url and fixed_url != url:
            try:
                raw2, final2, ctype2, status2, trunc2 = _try(fixed_url)
                if status2 < 400 and raw2:
                    url, raw, final_url, ctype, status, truncated = (
                        fixed_url, raw2, final2, ctype2, status2, trunc2)
                    fixed_note = note
            except Exception:
                pass
        # 2) Общая методика: сервер назвал параметр(ы), которые ему не нравятся —
        #    пробуем один раз без них и, если данные пришли, отдаём их, чтобы
        #    модель не зацикливалась на второстепенных параметрах (например, tz).
        if status >= 400:
            reason = _server_reason(raw)
            offenders = _params_named_in_reason(url, reason)
            stripped = _strip_params(url, offenders)
            if stripped and stripped != url:
                try:
                    raw3, final3, ctype3, status3, trunc3 = _try(stripped)
                    if status3 < 400 and raw3:
                        url, raw, final_url, ctype, status, truncated = (
                            stripped, raw3, final3, ctype3, status3, trunc3)
                        fixed_note = "dropped " + ",".join(offenders)
                except Exception:
                    pass

    elapsed = f"{time.time() - started:.2f}s"
    if status >= 400:
        reason = _server_reason(raw)
        offenders = _params_named_in_reason(url, reason)
        nxt = []
        stripped = _strip_params(url, offenders)
        if stripped:
            call = f'web action={action} url="{stripped}"'
            if jq_filter:
                call += f' jq="{jq_filter}"'
            nxt.append(call)
        nxt.append("web action=help")
        return _finish(_http_error(status, url, raw),
                       {"action": action, "status": status}, "error", "", nxt)
    if not raw:
        return _finish("⚠️ Пустой ответ.", {"action": action, "status": status},
                       "raw", "проверь URL или headers", [])

    kind = _kind(ctype, raw)
    text = raw.decode("utf-8", errors="replace")
    cfg = _config()
    meta = {"action": action, "kind": kind, "type": ctype or "unknown",
            "size": _human_size(len(raw)), "elapsed": elapsed}
    if final_url and final_url != url:
        meta["final"] = final_url
    if truncated:
        meta["truncated"] = "yes"
    if fixed_note:
        meta["fixed"] = fixed_note

    # авто-роутинг
    if action == "auto":
        if kind == "json":
            action = "json"
        elif kind == "html":
            action = "open"
        elif kind == "binary":
            action = "download"
        else:
            action = "open"
        meta["action"] = action

    # download (сюда попадаем только через авто-роутинг бинарника):
    # переиспользуем надёжный путь с aria2c/докачкой и проверкой типа.
    if action == "download":
        return _do_download(final_url or url, output_path, headers, timeout_sec,
                            session_path, resume, expected_sha256)

    # json
    if action == "json" or (action == "auto" and kind == "json"):
        body = None
        if jq_filter:
            result, err = _run_jq(text, jq_filter)
            if result is not None:
                body = result[:cfg["max_chars"]]
                provenance = "projected"
            elif err:
                meta["jq"] = "failed"
                body = f"⚠️ {err}\n\n{_json_summary(text)}"
                provenance = "raw"
        else:
            body = _json_summary(text)
            provenance = "raw"
        saved = None
        if session_path and len(raw) > 20_000:
            saved, _ = _save_bytes(raw, None, session_path,
                                   (urlparse(final_url or url).path.split("/")[-1] or "data") + ".json")
            if saved:
                meta["saved"] = saved
        nxt = [
            f'web action=json url="{url}" jq=".daily"',
            f'web action=download url="{url}"',
        ]
        if saved:
            nxt.insert(0, f'file_system action=read path="{saved}"')
        return _finish(body, meta, provenance,
                       "если данных много — сузь jq-фильтром; полный ответ сохранён" if saved
                       else "для выборки используй jq", nxt)

    # html / open / extract
    if kind != "html":
        # текст
        if action in ("open",) and kind in ("text",):
            body = text[:cfg["max_chars"]]
            if len(text) > len(body):
                meta["truncated"] = "yes"
            return _finish(body,
                           meta, "readable",
                           "если это не то — попробуй action=download или action=json",
                           [f'web action=download url="{url}"'])
        return _finish(text[:cfg["max_chars"]],
                       meta, "raw",
                       "не HTML — для файлов используй action=download",
                       [f'web action=download url="{url}"'])

    if action == "extract":
        want = [w for w in (extract or ["all"]) if w in SAFE_EXTRACT] or ["all"]
        body, total = _extract_structure(text, final_url or url, want, max_items, css)
        meta["items"] = total
        nxt = [f'web action=open url="{url}"',
               f'web action=json url="{url}"']
        return _finish(body, meta, "extracted",
                       "нужен текст страницы — action=open; API — action=json", nxt)

    # open (по умолчанию для html)
    body = _html_to_markdown(text)
    if not body:
        body = text[:cfg["max_chars"]]
    if len(body) > cfg["max_chars"]:
        body = body[:cfg["max_chars"]]
        meta["truncated"] = "yes"
    if session_path and len(text) > 20_000:
        path, _ = _save_bytes(text.encode("utf-8"), None, session_path,
                              (urlparse(final_url or url).path.split("/")[-1] or "page") + ".html")
        if path:
            meta["saved"] = path
    nxt = [f'web action=extract url="{url}" extract=["links","tables"]']
    if meta.get("saved"):
        nxt.insert(0, f'file_system action=read path="{meta["saved"]}"')
    return _finish(body, meta, "readable",
                   "структура (ссылки/таблицы) — action=extract; API — action=json", nxt)


def execute(
    url: str = None,
    action: str = "auto",
    query: str = None,
    extract: List[str] = None,
    css: List[str] = None,
    jq: str = None,
    jq_filter: str = None,
    output_path: str = None,
    headers=None,
    timeout_sec: int = 30,
    max_bytes: int = DEFAULT_MAX_BYTES,
    follow_redirects: bool = True,
    max_items: int = 100,
    session_path: str = None,
    resume: bool = False,
    expected_sha256: str = None,
    sha256: str = None,
    progress_callback=None,
    format: str = None,
) -> str:
    """Единый вход web. См. action=help."""
    action = (action or "auto").strip().lower()
    aliases = {"get": "auto", "fetch": "auto", "read": "open", "text": "open",
               "links": "extract", "parse": "extract", "project": "json",
               "filter": "json", "save": "download", "find": "search",
               "history": "downloads", "list": "downloads"}
    action = aliases.get(action, action)
    jq_filter = jq_filter or jq
    expected_sha256 = expected_sha256 or sha256

    if action == "help":
        return _help()
    if action == "downloads":
        return _action_downloads(session_path)
    if not url and not query:
        return _finish("❌ Укажи url (или query для action=search).",
                       {"action": action}, "error",
                       "web action=help — список возможностей",
                       ["web action=help"])
    if action == "search":
        if not query:
            return _finish("❌ Для action=search нужен query.",
                           {"action": action}, "error", "укажи query", ["web action=help"])
        body, nxt = _action_search(query, headers, timeout_sec, max_bytes, max_items)
        return _finish(body, {"action": "search", "query": _escape(query, 60)}, "extracted",
                       "открой верхний результат, чтобы получить содержание", nxt)

    return _go(url, action, extract, css, jq_filter, output_path, headers,
               timeout_sec, max_bytes, follow_redirects, max_items, session_path,
               resume, expected_sha256)


# Alias
web = execute


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(execute(url=sys.argv[1]))
    else:
        print(_help())
