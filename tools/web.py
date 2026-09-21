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

import base64
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

try:
    from core import process_control as _pc
except Exception:  # pragma: no cover
    _pc = None

try:
    from core import net_config as _net
except Exception:  # pragma: no cover
    _net = None


def _run(argv, **kwargs):
    """subprocess.run, но прерываемый по Esc (через process_control)."""
    return _pc.run(argv, **kwargs) if _pc else subprocess.run(argv, **kwargs)


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
                   "favicon", "badge", "avatar", "feedback", "flag",
                   "spacer", "placeholder", "loading", "blank", "pixel",
                   "tracking", "analytics", "button"):
        if marker in low:
            rank += 5
    return rank


# --------------------------------------------------------------------------
# Харнес (по образцу архивариуса session_memory)
# --------------------------------------------------------------------------

def _harness(meta: Dict, provenance: str, advice: str,
             next_actions: List[str], inventory: str = "") -> str:
    line = " | ".join(f"{k}={v}" for k, v in meta.items() if v not in (None, "", []))
    out = [f"🧭 web · {line}", f"provenance={provenance}"]
    if inventory:
        out.append(f"📦 На странице: {inventory}")
    if advice:
        out.append(f"💡 Совет: {advice}")
    if next_actions:
        out.append("➡ Следующие шаги (web):")
        out.extend(f"   • {a}" for a in next_actions)
    return "\n".join(out)


def _finish(body: str, meta: Dict, provenance: str, advice: str,
            next_actions: List[str], inventory: str = "") -> str:
    parts = [body.rstrip()] if body else []
    parts.append("")
    parts.append("────────────────────────────")
    parts.append(_harness(meta, provenance, advice, next_actions, inventory))
    return "\n".join(parts)


def _help() -> str:
    return (
        "🧭 web — единый добыватель данных из сети.\n"
        "\n"
        "Действия:\n"
        "  web action=auto url=…                     — сам выберет стратегию\n"
        "  web action=open url=…                     — читаемый текст страницы\n"
        "  web action=extract url=… extract=[links,tables] — структура\n"
        "  web action=images url=… | query=…         — найти прямые картинки\n"
        "    (со страницы или из выдачи; каждая ссылка проверяется на живую картинку)\n"
        "  web action=json url=… jq=\".daily\"        — JSON + фильтр\n"
        "    jq применяется к входу '.': '.items[] | .name',\n"
        "    условие: '.items[] | select(.time | startswith(\"2026\"))'\n"
        "  web action=download url=… [output_path=…] — скачать файл (докачка, торренты, sha256)\n"
        "    большие файлы (ISO) и торренты: url=https://….torrent или url=magnet:?…\n"
        "    resume=true — докачать/перекачать; если файл уже цел — вернётся из памяти\n"
        "    expected_sha256=… — проверка хеша (при несовпадении файл удаляется)\n"
        "  web action=downloads                      — память загрузок: что/куда/целое\n"
        "  web action=search query=\"…\"               — поиск в интернете\n"
        "  web action=proxy [command=show|set|clear|test] — прокси (см. ниже)\n"
        "  web action=help                           — эта справка\n"
        "\n"
        "  web action=json url=… method=POST json_body={…} — веб-API (POST/PUT/…)\n"
        "    для API, требующих тело: method, json_body (объект) или body (строка)\n"
        "\n"
        "Чем качать (движки):\n"
        "  • большие файлы, докачка, торренты/magnet, проверка sha256 — движок aria2c;\n"
        "  • сложные HTTP-запросы (методы, тело, JSON, заголовки, API) — HTTP-клиент (httpx).\n"
        "  Если aria2c не проходит, загрузка автоматически повторяется через HTTP-клиент.\n"
        "\n"
        "Прокси (не обязателен, по умолчанию сеть напрямую):\n"
        "  • задать: web action=proxy command=set proxy=\"host:port\"\n"
        "      принимается в любом виде: 17277 · host:port · host:port user pass ·\n"
        "      scheme://user:pass@host:port · none (снять). scope=session|global.\n"
        "  • проверить: web action=proxy command=test url=\"https://…\"\n"
        "      (TCP + реальный запрос; для aria2c и HTTP-клиента отдельно; подтверждает работоспособность)\n"
        "  • посмотреть: web action=proxy command=show · снять: command=clear\n"
        "  Настройка наследуется всеми сетевыми инструментами (web/image/vision/audio).\n"
        "\n"
        "Общее: headers, timeout_sec, max_bytes, follow_redirects, session_path, proxy.\n"
        "Запись вне папки сессии требует dangerous mode.\n"
        "Память загрузок глобальна (~/.botinok/downloads/history.json) и не зависит от сессии.\n"
        "Старые имена (web_search, open_url, web_extract, curl) работают как алиасы.\n"
    )


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _resolve_file_markers(obj):
    """Заменить маркеры локальных файлов на их base64.

    Модель передаёт путь, а не гигантский base64: в json_body вместо строки
    пишется {"$file_base64": "/путь/к/файлу"} — web сам читает файл и
    подставляет base64. Так байты не проходят через tool-call модели.
    """
    if isinstance(obj, dict):
        if set(obj.keys()) == {"$file_base64"}:
            path = obj.get("$file_base64")
            if hasattr(path, "__fspath__"):
                path = os.fspath(path)
            if not path or not os.path.isfile(path):
                raise FileNotFoundError(f"$file_base64: файл не найден: {path}")
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        return {k: _resolve_file_markers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_file_markers(v) for v in obj]
    return obj


def _request_kwargs(method: str, content, json_body, data) -> dict:
    """Собрать тело запроса для httpx из body/json/data."""
    kwargs = {}
    if json_body is not None:
        kwargs["json"] = _resolve_file_markers(json_body)
    elif data is not None:
        if isinstance(data, (dict, list)):
            kwargs["json"] = _resolve_file_markers(data)
        else:
            kwargs["content"] = data
    elif content is not None:
        kwargs["content"] = content
    return kwargs


def _effective_proxy(session_path: Optional[str], proxy=None) -> Optional[str]:
    """Прокси из net_config (или None). Без net_config — только явный параметр."""
    if _net is None:
        return proxy or None
    try:
        return _net.httpx_proxy(session_path, proxy)
    except Exception:
        return proxy or None


def _fetch(url: str, headers, timeout_sec: int, max_bytes: int,
           follow_redirects: bool, method: str = "GET",
           content=None, json_body=None, data=None,
           session_path: Optional[str] = None,
           proxy=None) -> Tuple[bytes, str, str, int, bool]:
    """HTTP-запрос (GET/POST/PUT/PATCH/DELETE) с ограничением размера.

    Прокси берётся у net_config (сессия/конфиг/env) или явного `proxy`.
    -> raw, final_url, content_type, status, truncated.
    """
    hdrs = _build_headers(headers)
    timeout = httpx.Timeout(connect=min(timeout_sec, 60) or 10,
                            read=max(timeout_sec or 10, 10),
                            write=10, pool=10)
    req_kwargs = _request_kwargs(method, content, json_body, data)
    px = _effective_proxy(session_path, proxy)
    with httpx.Client(follow_redirects=follow_redirects, timeout=timeout,
                      proxy=px) as client:
        with client.stream(method.upper(), url, headers=hdrs, **req_kwargs) as resp:
            chunks: List[bytes] = []
            total = 0
            truncated = False
            for chunk in resp.iter_bytes():
                if _pc and _pc.stop_requested():
                    raise httpx.RequestError("остановлено пользователем")
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
        r = _run(["file", "-b", path], capture_output=True, text=True, timeout=3)
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
        r = _run(["file", "-b", path], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _looks_like_html_doc(raw: bytes) -> bool:
    head = (raw[:1024] or b"").lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)


def _looks_like_image(raw: bytes) -> bool:
    """Похоже ли содержимое на изображение (по magic-байтам)."""
    if not raw:
        return False
    head = raw[:16]
    for magic, _name in _IMAGE_MAGIC:
        if head.startswith(magic):
            return True
    # WebP: RIFF....WEBP
    if head.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return True
    return False


def _image_kind(raw: bytes) -> str:
    head = raw[:16]
    for magic, name in _IMAGE_MAGIC:
        if head.startswith(magic):
            return name
    if head.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "webp"
    return ""


def _aria2c_available() -> bool:
    try:
        return _run(["aria2c", "--version"], capture_output=True,
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


def _aria2c_error_text(msg: str) -> str:
    """Достать из вывода aria2c человекочитаемую причину."""
    text = _strip_ansi(msg or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()
             and "CUID#" not in ln]
    # aria2c печатает локализованные «шапки»; оставляем содержательные строки.
    noise = ("Использованные обозначения", "aria2 продолжит загрузку",
             "проверьте log-файл", "Для более подробной информации",
             "Если возникли какие-либо ошибки", "Смотрите")
    lines = [ln for ln in lines if not any(n.lower() in ln.lower() for n in noise)]
    if not lines:
        return ""
    return " | ".join(lines[-3:])[:400]


def _aria2c_download(url: str, dest: str, headers, timeout_sec: int,
                     proxy=None, session_path: Optional[str] = None) -> Tuple[bool, str]:
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
    if _net is not None:
        try:
            cmd.extend(_net.aria2c_args(session_path, proxy))
        except Exception:
            pass
    elif proxy:
        cmd.append(f"--all-proxy={proxy}")
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
        r = _run(cmd, capture_output=True, text=True, timeout=hard_timeout)
    except subprocess.TimeoutExpired:
        return False, "aria2c timeout"
    if r.returncode != 0:
        msg = _aria2c_error_text(r.stderr or r.stdout or "") or "aria2c error"
        return False, msg
    if torrent:
        if not os.path.isdir(work_dir) or not any(os.scandir(work_dir)):
            return False, "торрент не создал файлов"
    elif not os.path.exists(dest):
        return False, "aria2c не создал файл"
    return True, ""


def _httpx_download(url: str, dest: str, headers, timeout_sec: int,
                    proxy=None, session_path: Optional[str] = None) -> Tuple[bool, str]:
    """Запасной движок загрузки (httpx): без обрезки, с прокси. -> (ok, error)."""
    try:
        px = _effective_proxy(session_path, proxy)
        with httpx.Client(follow_redirects=True, proxy=px,
                          timeout=httpx.Timeout(connect=15, read=max(timeout_sec, 30),
                                                write=30, pool=15)) as client:
            with client.stream("GET", url, headers=_build_headers(headers)) as resp:
                if resp.status_code >= 400:
                    body = b"".join(resp.iter_bytes())[:600]
                    return False, f"HTTP {resp.status_code}: {_server_reason(body)}"
                with open(dest, "wb") as f:
                    for chunk in resp.iter_bytes():
                        if _pc and _pc.stop_requested():
                            raise httpx.RequestError("остановлено пользователем")
                        f.write(chunk)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _download_file(url: str, dest: str, headers, timeout_sec: int,
                   resume: bool = False, proxy=None,
                   session_path: Optional[str] = None) -> Tuple[bool, str, str]:
    """Скачать файл надёжно. -> (ok, error, engine).

    Предпочтительно aria2c (докачка, большие файлы). Если он недоступен или
    упал — автоматический повтор через httpx (у движков разная маршрутизация:
    то, что не проходит у aria2c, часто проходит у httpx, и наоборот).
    """
    if _aria2c_available():
        ok, err = _aria2c_download(url, dest, headers, timeout_sec,
                                   proxy=proxy, session_path=session_path)
        if ok:
            return True, "", "aria2c"
        # Запасной движок: не оставляем модель без результата из-за движка.
        ok2, err2 = _httpx_download(url, dest, headers, timeout_sec,
                                    proxy=proxy, session_path=session_path)
        if ok2:
            return True, "", "httpx (после aria2c)"
        return False, f"aria2c: {err} | httpx: {err2}", "aria2c+httpx"
    ok, err = _httpx_download(url, dest, headers, timeout_sec,
                              proxy=proxy, session_path=session_path)
    return ok, err, "httpx"


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
                 expected_sha256: Optional[str] = None, proxy=None) -> str:
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

    ok, err, engine = _download_file(url, dest, headers, timeout_sec, resume,
                                     proxy=proxy, session_path=session_path)
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
    is_image = _looks_like_image(head)
    next_actions = []
    if is_image:
        next_actions.append(f'image(source="{dest}", alt="…")')
        advice = "это изображение — покажи его в чате через image(source=…)"
    else:
        advice = "файл в папке сессии"
    return _finish(
        f"✅ Скачано: {url}\n📁 Файл: {dest}\n📊 {_human_size(size)}\n"
        f"📝 {ftype}\n🔐 {sha}",
        {"action": "download", "saved": dest, "size": _human_size(size),
         "elapsed": elapsed, "engine": engine},
        "saved", advice, next_actions)


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
# Прокси (настраивает агент; без хардкодов адресов и сервисов)
# --------------------------------------------------------------------------

def _fmt_proxy_state(st: dict) -> str:
    lines = []
    if st.get("proxy"):
        lines.append(f"Прокси: {st.get('masked')}")
        lines.append(f"источник: {st.get('source')}")
        if st.get("no_proxy"):
            lines.append(f"no_proxy: {st.get('no_proxy')}")
    else:
        lines.append("Прокси не задан (сеть напрямую).")
    if st.get("env_values"):
        lines.append("env: " + ", ".join(f"{k}={(v or '')[:40]}" for k, v in st["env_values"].items()))
    if st.get("session_path"):
        lines.append(f"настройки сессии: {st['session_path']}")
    if st.get("config_path"):
        lines.append(f"глобальный конфиг: {st['config_path']}")
    return "\n".join(lines)


def _action_proxy(sub: str, proxy, no_proxy, scope, url, session_path) -> str:
    if _net is None:
        return _finish("❌ Сетевой конфиг недоступен (core/net_config).",
                       {"action": "proxy"}, "error", "", [])
    sub = (sub or "show").lower()
    try:
        if sub == "show":
            st = _net.show(session_path)
            return _finish(_fmt_proxy_state(st), {"action": "proxy", "sub": "show"},
                           "readable",
                           "чтобы проверить — web action=proxy command=test url=\"https://…\"",
                           ['web action=proxy command=test url="https://…"',
                            'web action=proxy command=set proxy="host:port"',
                            'web action=proxy command=clear'])
        if sub == "set":
            if not proxy:
                return _finish("❌ Укажи proxy (напр. proxy=\"host:port\", "
                               "proxy=\"scheme://user:pass@host:port\", или proxy=17277).",
                               {"action": "proxy", "sub": "set"}, "error",
                               "формат ввода прощающий: host:port / порт / scheme://…",
                               ['web action=proxy command=set proxy="host:port"'])
            st = _net.set_proxy(proxy, session_path, no_proxy, scope)
            return _finish(f"✅ Прокси задан: {st.get('masked')}\n"
                           f"scope: {st.get('scope')}\nзаписано: {st.get('stored')}",
                           {"action": "proxy", "sub": "set", "scope": st.get("scope")},
                           "saved",
                           "проверь работоспособность — command=test url=\"https://…\"",
                           ['web action=proxy command=test url="https://…"'])
        if sub == "clear":
            st = _net.clear(session_path, scope)
            return _finish(f"✅ Прокси снят ({st.get('scope')}): {st.get('stored')}",
                           {"action": "proxy", "sub": "clear"}, "saved",
                           "запросы пойдут напрямую", [])
        if sub == "test":
            res = _net.test(session_path, override=proxy, url=url)
            if res.get("error"):
                return _finish(f"❌ {res['error']}", {"action": "proxy", "sub": "test"},
                               "error", "сначала задай прокси: command=set",
                               ['web action=proxy command=set proxy="host:port"'])
            lines = [f"Прокси: {res.get('masked')} (источник: {res.get('source')})"]
            tcp = res.get("tcp") or {}
            lines.append(f"{'✅' if tcp.get('ok') else '❌'} TCP {tcp.get('host')}:{tcp.get('port')}"
                         + (f" — {tcp.get('error')}" if tcp.get('error') else " — доступен"))
            nxt = []
            if url:
                h = res.get("http") or {}
                if h.get("ok"):
                    lines.append(f"✅ httpx: HTTP {h.get('status')} "
                                 f"{h.get('type') or ''} {_human_size(h.get('bytes') or 0)} "
                                 f"за {h.get('elapsed')}")
                else:
                    lines.append(f"❌ httpx: {h.get('error') or ('HTTP ' + str(h.get('status')))}")
                a = res.get("aria2c")
                if a is not None:
                    if a.get("ok"):
                        lines.append(f"✅ aria2c: получено {_human_size(a.get('bytes') or 0)}")
                    else:
                        lines.append(f"❌ aria2c: {a.get('error')}")
                    if not a.get("ok") and h.get("ok"):
                        lines.append("(aria2c не проходит — загрузки уйдут через httpx-фолбэк)")
            else:
                lines.append("ℹ️ Полная проверка — передай url=\"https://…\".")
                nxt.append('web action=proxy command=test url="https://…"')
            ok = res.get("ok")
            return _finish("\n".join(lines),
                           {"action": "proxy", "sub": "test",
                            "result": "работает" if ok else "проблемы"},
                           "readable",
                           "прокси подтверждён" if ok else "проверь адрес/сеть",
                           nxt)
        return _finish(f"❌ Неизвестная подкоманда proxy: {sub}",
                       {"action": "proxy"}, "error",
                       "команды: show | set | clear | test",
                       ['web action=proxy command=show'])
    except ValueError as e:
        return _finish(f"❌ {e}", {"action": "proxy", "sub": sub}, "error",
                       "формат: host:port, порт, scheme://user:pass@host:port, none",
                       ['web action=proxy command=show'])
    except Exception as e:
        return _finish(f"❌ {type(e).__name__}: {e}", {"action": "proxy"}, "error", "", [])


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
            for label, full in links[:max_items]:
                out.append(f"- [{label}]({full})")
            out.append("")
            total += len(links[:max_items])

    if want_all or "images" in want:
        images = _collect_image_urls(html_text, base_url, max_items)
        if images:
            out.append("## 🖼️ Images")
            out.append("")
            for cap, full in images:
                out.append(f"- {cap}: `{full}`")
            out.append("")
            total += len(images)

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


def _collect_image_urls(text: str, base_url: str,
                        max_items: int = 100) -> List[Tuple[str, str]]:
    """Прямые картинки со страницы: (подпись, абсолютный url), фото вперёд.

    Generic-парсер: `<img>` (src + ленивые атрибуты + srcset), `<source srcset>`,
    `og:image`/`twitter:image`. Иконки/логотипы уезжают в конец (см. `_image_rank`).
    """
    if HTMLParser is None:
        return []
    tree = HTMLParser(text)
    seen = set()
    images: List[Tuple[str, str]] = []

    def _add(raw_ref: str, caption: str = "") -> None:
        ref = (raw_ref or "").strip()
        if not ref or ref.startswith("data:"):
            return
        if "," in ref and " " in ref:  # srcset: первый (обычно крупный) вариант
            ref = ref.split(",")[0].strip().split(" ")[0]
        full = urljoin(base_url, ref)
        if full in seen or full.startswith(("#", "javascript:")):
            return
        seen.add(full)
        images.append((_escape(caption or "[no caption]", 100), full))

    for node in tree.css("img"):
        attrs = node.attributes
        cap = (attrs.get("alt") or attrs.get("title") or "").strip()
        for key in ("src", "data-src", "data-original", "data-lazy-src",
                    "data-srcset", "srcset"):
            if attrs.get(key):
                _add(attrs.get(key), cap)
    for node in tree.css("source[srcset], source[data-srcset]"):
        _add(node.attributes.get("srcset") or node.attributes.get("data-srcset"), "")
    for node in tree.css("meta[property], meta[name]"):
        key = (node.attributes.get("property") or node.attributes.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
            _add(node.attributes.get("content") or "", "")

    images.sort(key=lambda item: _image_rank(item[1]))
    return images[:max_items]


_JS_MARKERS = ("__next_data__", "window.__nuxt__", "ng-version", "data-reactroot",
               "data-v-", "id=\"app\"", "id='app'", "/_next/", "webpack")


def _page_inventory(text: str, base_url: str) -> Dict[str, object]:
    """Дёшево посчитать, что лежит на странице (для навигации модели)."""
    inv: Dict[str, object] = {"images": 0, "photos": 0, "links": 0, "headings": 0,
                              "tables": 0, "meta": 0, "js_heavy": False}
    if HTMLParser is None:
        return inv
    try:
        _, n_images = _extract_structure(text, base_url, ["images"], 500)
        _, n_links = _extract_structure(text, base_url, ["links"], 500)
        _, n_heads = _extract_structure(text, base_url, ["headings"], 500)
        _, n_tables = _extract_structure(text, base_url, ["tables"], 500)
        _, n_meta = _extract_structure(text, base_url, ["meta"], 500)
        inv.update(images=n_images, links=n_links, headings=n_heads,
                   tables=n_tables, meta=n_meta)
        # Фото — картинки, похожие на фотографии (не иконки/логотипы).
        inv["photos"] = sum(1 for _cap, u in _collect_image_urls(text, base_url, 500)
                            if _image_rank(u) <= 1)
        low = text.lower()
        inv["js_heavy"] = (n_images == 0 and n_links < 5) or any(
            m in low for m in _JS_MARKERS)
    except Exception:
        pass
    return inv


def _inventory_line(inv: Dict[str, object]) -> str:
    parts = [f"🖼 images={inv.get('images', 0)}",
             f"links={inv.get('links', 0)}",
             f"headings={inv.get('headings', 0)}",
             f"tables={inv.get('tables', 0)}",
             f"meta={inv.get('meta', 0)}"]
    if inv.get("photos"):
        parts.insert(1, f"фото≈{inv['photos']}")
    return " · ".join(str(p) for p in parts)


def _inventory_actions(inv: Dict[str, object], url: str, query: str = "") -> List[str]:
    """Готовые вызовы под то, что реально есть на странице (без доменной конкретики)."""
    acts: List[str] = []
    if inv.get("images"):
        acts.append(f'web action=extract url="{url}" extract=["images"] max_items=30')
        if inv.get("photos"):
            acts.append(f'web action=images url="{url}" max_items=3')
    if inv.get("links"):
        acts.append(f'web action=extract url="{url}" extract=["links"]')
    if inv.get("tables"):
        acts.append(f'web action=extract url="{url}" extract=["tables"]')
    if inv.get("js_heavy") and not inv.get("images"):
        acts.append('web action=images query="<что нужно найти>" — прямых картинок нет, это JS-страница')
    if not acts:
        acts.append(f'web action=json url="{url}"')
    return acts


# --------------------------------------------------------------------------
# Поиск и проверка изображений (generic, без привязки к сервисам)
# --------------------------------------------------------------------------

IMAGE_PROBE_BYTES = 400_000


def _search_result_urls(query: str, headers, timeout_sec: int, max_bytes: int,
                        limit: int, session_path: Optional[str] = None,
                        proxy=None) -> List[str]:
    """URL-ы результатов поиска (перебирает доступные провайдеры web)."""
    for tmpl in SEARCH_URLS:
        urls: List[str] = []
        try:
            raw, final, ctype, status, _ = _fetch(
                tmpl.format(q=quote(query)), headers, timeout_sec, max_bytes,
                True, session_path=session_path, proxy=proxy)
            if status < 400 and raw:
                for item in _parse_ddg_html(raw.decode("utf-8", errors="replace"), limit):
                    urls.append(item["url"])
        except Exception:
            urls = []
        if urls:
            return urls[:limit]
    return []


def _verify_image(url: str, headers, timeout_sec: int, session_path=None,
                  proxy=None) -> Tuple[bool, str, int]:
    """Проверить, что ссылка отдаёт реальную картинку. -> (ok, info, bytes)."""
    try:
        raw, _final, ctype, status, _tr = _fetch(
            url, headers, min(max(timeout_sec, 5), 20), IMAGE_PROBE_BYTES, True,
            session_path=session_path, proxy=proxy)
        if status >= 400:
            return False, f"HTTP {status}", 0
        kind = _image_kind(raw)
        if kind or ctype.startswith("image/"):
            return True, kind or ctype, len(raw)
        return False, "не картинка", len(raw)
    except Exception as e:
        return False, type(e).__name__, 0


def _action_images(query: str, url: str, headers, timeout_sec: int, max_bytes: int,
                   max_items: int, session_path: Optional[str] = None,
                   proxy=None, max_pages: int = 4) -> Tuple[str, str, List[str], Dict]:
    """Найти прямые изображения (со страницы `url` или из выдачи по `query`).

    Провайдер не зашит: берём любую страницу/выдачу и разбираем generic-парсером
    прямых картинок; каждую ссылку проверяем на реальную картинку и отдаём только
    живые. -> (body, provenance, next_actions, meta)
    """
    max_items = max(1, min(int(max_items or 3), 20))
    candidates: List[Tuple[str, str, str]] = []  # (caption, url, source_page)

    if url:
        pages = [url]
    elif query:
        pages = _search_result_urls(query, headers, timeout_sec, max_bytes, max_pages,
                                    session_path, proxy)
        if not pages:
            return ("❌ Поиск не дал страниц (провайдер недоступен или заблокировал).",
                    "error", ['web action=images url="<адрес страницы с картинками>"'], {})
    else:
        return ("❌ Укажи url (страница с картинками) или query (что искать).",
                "error", ["web action=help"], {})

    pages_tried = 0
    for page in pages[:max_pages]:
        pages_tried += 1
        try:
            raw, final, ctype, status, _tr = _fetch(
                page, headers, timeout_sec, max_bytes, True,
                session_path=session_path, proxy=proxy)
        except Exception:
            continue
        if status >= 400 or not raw:
            continue
        if not (ctype.startswith("text/") or ctype.startswith("image/")
                or b"<" in raw[:512]):
            continue
        text = raw.decode("utf-8", errors="replace")
        for cap, u in _collect_image_urls(text, final or page, max_items * 10):
            candidates.append((cap, u, final or page))
        if len(candidates) >= max_items * 8:
            break

    verified: List[Tuple[str, str, str, int]] = []
    seen = set()
    for cap, u, page in candidates:
        if u in seen:
            continue
        seen.add(u)
        ok, _info, size = _verify_image(u, headers, timeout_sec, session_path, proxy)
        if ok:
            verified.append((cap, u, page, size))
            if len(verified) >= max_items * 3:
                break

    # Фото обычно крупнее служебных иконок: сначала размер (generic-признак),
    # затем «фотографичность» URL.
    verified.sort(key=lambda t: (-t[3], _image_rank(t[1])))
    verified = verified[:max_items]

    meta = {"action": "images", "query": _escape(query, 60) if query else None,
            "pages": pages_tried, "found": len(candidates),
            "working": len(verified)}
    if not verified:
        return (f"❌ Рабочих прямых картинок не найдено (проверено кандидатов: "
                f"{len(candidates)} с {pages_tried} стр.).",
                "error",
                ['web action=images query="<иной запрос>"',
                 'web action=open url="<страница>"',
                 'web action=proxy show — если сеть недоступна'],
                meta)

    lines = [f"🖼 Найдено рабочих изображений: {len(verified)}"]
    if query:
        lines[0] += f" по запросу «{_escape(query, 60)}»"
    lines.append("")
    nxt: List[str] = []
    for i, (cap, u, page, size) in enumerate(verified, 1):
        lines.append(f"{i}. {cap} — {_human_size(size)}")
        lines.append(f"   {u}")
        lines.append(f"   источник: {page}")
        if i <= 3:
            nxt.append(f'image(source="{u}", alt="{cap if cap != "[no caption]" else ""}")')
    nxt.append(f'web action=images query="{_escape(query or "<запрос>", 60)}"')
    return "\n".join(lines), "extracted", nxt, meta


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
        res = _run(["jq", "-r", jq_filter], input=text, capture_output=True,
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


def _search_lynx(query: str, timeout_sec: int, max_chars: int,
                 session_path: Optional[str] = None, proxy=None) -> Optional[str]:
    encoded = quote(query)
    env = None
    if _net is not None:
        try:
            env = _net.subprocess_env(session_path, proxy)
        except Exception:
            env = None
    for tmpl in SEARCH_URLS:
        url = tmpl.format(q=encoded)
        try:
            res = _run(
                ["lynx", "-dump", "-number_links", "-display_charset=utf-8",
                 f"-connect_timeout={min(timeout_sec, 60)}",
                 f"-read_timeout={min(timeout_sec, 120)}", url],
                capture_output=True, text=True, timeout=min(timeout_sec + 10, 130),
                env=env,
            )
        except Exception:
            continue
        if res.returncode == 0 and res.stdout and len(res.stdout.strip()) > 100:
            lines = [ln for ln in res.stdout.split("\n") if ln.strip()]
            return "\n".join(lines)[:max_chars]
    return None


def _action_search(query: str, headers, timeout_sec: int, max_bytes: int,
                   max_items: int, session_path: Optional[str] = None,
                   proxy=None) -> Tuple[str, List[str]]:
    cfg = _config()
    results: List[Dict[str, str]] = []
    try:
        raw, final_url, ctype, status, _ = _fetch(
            SEARCH_URLS[0].format(q=quote(query)), headers, timeout_sec, max_bytes, True,
            session_path=session_path, proxy=proxy)
        if status < 400 and raw:
            results = _parse_ddg_html(raw.decode("utf-8", errors="replace"), max_items)
    except Exception:
        results = []
    if not results:
        # fallback: lynx
        text = _search_lynx(query, timeout_sec, cfg["max_chars"], session_path, proxy)
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
        timeout_sec: int, max_bytes: int, follow_redirects: bool, max_items: int,
        session_path: Optional[str], resume: bool = False,
        expected_sha256: Optional[str] = None, method: str = "GET",
        content=None, json_body=None, data=None, proxy=None) -> str:
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

    method = (method or "GET").upper()
    has_body = any(v is not None for v in (content, json_body, data))

    # Скачивание — отдельный надёжный путь (aria2c, докачка, проверка типа/хеша).
    # aria2c умеет только GET; запросы с телом идут обычным HTTP-путём.
    if action == "download" and method == "GET" and not has_body:
        return _do_download(url, output_path, headers, timeout_sec, session_path,
                            resume, expected_sha256, proxy=proxy)

    started = time.time()

    def _try(u):
        return _fetch(u, headers, timeout_sec, max_bytes, follow_redirects,
                      method=method, content=content, json_body=json_body, data=data,
                      session_path=session_path, proxy=proxy)

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

    # download (авто-роутинг бинарника или запрос с телом):
    # для GET без тела — надёжный путь aria2c; иначе сохраняем полученное.
    if action == "download":
        if method == "GET" and not has_body:
            return _do_download(final_url or url, output_path, headers, timeout_sec,
                                session_path, resume, expected_sha256, proxy=proxy)
        path, ftype = _save_bytes(raw, output_path, session_path, final_url or url)
        if not path:
            return _finish(
                f"❌ Получено {_human_size(len(raw))} — укажи output_path или session_path.",
                {"action": "download"}, "raw",
                "укажи output_path (внутри сессии)", [])
        return _finish(f"✅ Сохранено: {path}\n📊 {_human_size(len(raw))}\n📝 {ftype}",
                       {"action": "download", "saved": path}, "saved",
                       "файл в папке сессии", [])

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
        inv = _page_inventory(text, final_url or url)
        nxt = []
        if "images" in want:
            for _cap, u in _collect_image_urls(text, final_url or url, 3):
                nxt.append(f'image(source="{u}", alt="…")')
        nxt.append(f'web action=images url="{url}" max_items=3')
        nxt.append(f'web action=open url="{url}"')
        return _finish(body, meta, "extracted",
                       "нужен текст страницы — action=open; прямые картинки — image(source=…)",
                       nxt, inventory=_inventory_line(inv))

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
    inv = _page_inventory(text, final_url or url)
    nxt = _inventory_actions(inv, final_url or url)
    if meta.get("saved"):
        nxt.insert(0, f'file_system action=read path="{meta["saved"]}"')
    advice = ("на странице есть картинки — их можно показать/скачать"
              if inv.get("images") else
              "структура (ссылки/картинки/таблицы) — action=extract; API — action=json")
    return _finish(body, meta, "readable", advice, nxt,
                   inventory=_inventory_line(inv))


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
    method: str = "GET",
    body: str = None,
    data=None,
    json_body=None,
    json_data=None,
    progress_callback=None,
    format: str = None,
    proxy: str = None,
    no_proxy: str = None,
    scope: str = None,
    command: str = None,
) -> str:
    """Единый вход web. См. action=help."""
    action = (action or "auto").strip().lower()
    aliases = {"get": "auto", "fetch": "auto", "read": "open", "text": "open",
               "links": "extract", "parse": "extract", "project": "json",
               "filter": "json", "save": "download", "find": "search",
               "history": "downloads", "list": "downloads",
               "images": "images", "photos": "images", "photo": "images",
               "download_image": "images", "proxy_show": "proxy",
               "proxy_set": "proxy", "proxy_clear": "proxy", "proxy_test": "proxy"}
    raw_action = action
    action = aliases.get(action, action)
    jq_filter = jq_filter or jq
    expected_sha256 = expected_sha256 or sha256
    if json_body is None:
        json_body = json_data
    # Синонимы тела запроса: body (строка) / data / json_body (объект).
    if data is None and body is not None:
        data = body

    if action == "help":
        return _help()
    if action == "proxy":
        sub = (command or "").strip().lower()
        if not sub:
            sub = {"proxy_show": "show", "proxy_set": "set",
                   "proxy_clear": "clear", "proxy_test": "test"}.get(raw_action, "show")
        return _action_proxy(sub, proxy, no_proxy, scope, url, session_path)
    if action == "downloads":
        return _action_downloads(session_path)
    if action == "images":
        body, provenance, nxt, meta = _action_images(
            query, url, headers, timeout_sec, max_bytes, max_items or 3,
            session_path, proxy)
        return _finish(body, meta, provenance,
                       "готовые image(source=…) — вставь token в ответ, чтобы показать картинку",
                       nxt)
    if not url and not query:
        return _finish("❌ Укажи url (или query для action=search/images).",
                       {"action": action}, "error",
                       "web action=help — список возможностей",
                       ["web action=help"])
    if action == "search":
        if not query:
            return _finish("❌ Для action=search нужен query.",
                           {"action": action}, "error", "укажи query", ["web action=help"])
        body, nxt = _action_search(query, headers, timeout_sec, max_bytes, max_items,
                                   session_path, proxy)
        return _finish(body, {"action": "search", "query": _escape(query, 60)}, "extracted",
                       "открой верхний результат, чтобы получить содержание", nxt)

    return _go(url, action, extract, css, jq_filter, output_path, headers,
               timeout_sec, max_bytes, follow_redirects, max_items, session_path,
               resume, expected_sha256, method, None, json_body, data, proxy=proxy)


# Alias
web = execute


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(execute(url=sys.argv[1]))
    else:
        print(_help())
