#!/usr/bin/env python3
"""
Единая сетевая настройка веб-кита: прокси.

Задача — избавить агента от знания форматов: он пишет адрес прокси «как удобно»
(`17277`, `127.0.0.1:17277`, `host:port user pass`, `socks5://user:pass@host:port`,
`none`), а инструмент нормализует и раздаёт значение всем сетевым под-инструментам
в нужной каждому форме (httpx / requests / aria2c / env подпроцесса).

Никаких сервисов и адресов в коде нет: источник — конфиг, файл сессии, переменные
окружения или явный параметр вызова. Прокси не навязывается: если ничего не задано,
поведение прежнее.

Приоритет источников: явный параметр вызова > файл сессии > глобальный конфиг > env.

Пустые значения env (`HTTP_PROXY=""`) игнорируются: иначе httpx молча обходит прокси.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import socket
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

SETTINGS_VERSION = 1
SESSION_SUBDIR = os.path.join(".botinok")
GLOBAL_SECTION = "Tools"
GLOBAL_KEY = "Proxy"
GLOBAL_NOPROXY_KEY = "NoProxy"

_ALLOWED_SCHEMES = ("http", "https", "socks5", "socks5h", "socks4", "all")
_ENV_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
             "ALL_PROXY", "all_proxy")
_ENV_NOPROXY_KEYS = ("NO_PROXY", "no_proxy")


# --------------------------------------------------------------------------
# Пути
# --------------------------------------------------------------------------

def _project_config_path() -> str:
    override = os.environ.get("BOTINOK_CONFIG")
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config.cfg")


def session_settings_path(session_path: Optional[str]) -> Optional[str]:
    if not session_path:
        return None
    return os.path.join(os.path.realpath(session_path), "project", SESSION_SUBDIR,
                        "net.json")


# --------------------------------------------------------------------------
# Нормализация
# --------------------------------------------------------------------------

def _is_off(value: str) -> bool:
    return value.strip().lower() in ("", "none", "off", "no", "direct", "clear", "-", "нет")


def normalize_proxy(value) -> Optional[str]:
    """Привести любой ввод к `scheme://[user:pass@]host:port` (или None).

    Принимает: `17277`, `host:port`, `host port`, `host:port user pass`,
    `host port user pass`, `scheme://…`, `[scheme] host port user pass`,
    `user:pass@host:port`, `none`/`clear`/пусто → None.
    Бросает ValueError на неисправимый ввод.
    """
    if value is None:
        return None
    if isinstance(value, (int,)):
        value = str(value)
    if isinstance(value, (list, tuple)):
        value = ":".join(str(v) for v in value)
    s = str(value).strip()
    if _is_off(s):
        return None

    scheme = "http"
    user = ""
    password = ""
    rest = s

    if "://" in s:
        scheme, rest = s.split("://", 1)
        scheme = scheme.strip().lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"неподдерживаемая схема прокси: {scheme}")
    else:
        tokens = s.split()
        if len(tokens) >= 2 and tokens[0].strip().lower() in _ALLOWED_SCHEMES:
            scheme = tokens[0].strip().lower()
            tokens = tokens[1:]
            s = " ".join(tokens)
        rest = s

    # user:pass@host:port
    if "@" in rest:
        auth, rest = rest.split("@", 1)
        if ":" in auth:
            user, password = auth.split(":", 1)
        else:
            user = auth

    # host:port [user pass]  |  host port user pass
    if " " in rest.strip():
        tokens = rest.split()
        host = tokens[0]
        port = tokens[1] if len(tokens) > 1 else ""
        if len(tokens) > 2 and not user:
            user = tokens[2]
        if len(tokens) > 3 and not password:
            password = tokens[3]
        if ":" in host and not port:
            host, port = host.rsplit(":", 1)
    elif ":" in rest:
        host, port = rest.rsplit(":", 1)
    else:
        # только порт или только хост
        if rest.isdigit():
            host, port = "127.0.0.1", rest
        else:
            raise ValueError(f"не понял прокси (нужен host:port): {s}")

    host = host.strip().strip("[]")
    port = port.strip()
    if not host:
        raise ValueError("не указан хост прокси")
    if not port.isdigit() or not (0 < int(port) < 65536):
        raise ValueError(f"некорректный порт прокси: {port or '(пусто)'}")

    auth = ""
    if user:
        auth = user + (f":{password}" if password else "") + "@"
    return f"{scheme}://{auth}{host}:{int(port)}"


def mask_proxy(value: Optional[str]) -> str:
    """Скрыть пароль для показа агенту/в логах."""
    if not value:
        return "—"
    parsed = urlparse(value if "://" in value else "http://" + value)
    if parsed.password:
        return value.replace(f":{parsed.password}@", ":***@")
    return value


def normalize_no_proxy(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        items = re.split(r"[,\s]+", str(value))
    return ",".join(i.strip() for i in items if i.strip())


def proxy_host_port(value: str) -> Tuple[str, int]:
    parsed = urlparse(value if "://" in value else "http://" + value)
    return parsed.hostname or "", int(parsed.port or 0)


# --------------------------------------------------------------------------
# Хранение: сессия (json) и глобальный конфиг
# --------------------------------------------------------------------------

def _load_session(session_path: Optional[str]) -> dict:
    path = session_settings_path(session_path)
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_session(session_path: Optional[str], data: dict) -> None:
    path = session_settings_path(session_path)
    if not path:
        raise ValueError("нет session_path для хранения настройки сессии")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_global() -> dict:
    parser = configparser.ConfigParser()
    path = _project_config_path()
    if os.path.exists(path):
        try:
            parser.read(path, encoding="utf-8")
        except Exception:
            pass
    out = {}
    try:
        out["proxy"] = parser.get(GLOBAL_SECTION, GLOBAL_KEY, fallback="") or ""
        out["no_proxy"] = parser.get(GLOBAL_SECTION, GLOBAL_NOPROXY_KEY, fallback="") or ""
    except Exception:
        pass
    return out


def _save_global(proxy: Optional[str], no_proxy: str) -> None:
    path = _project_config_path()
    parser = configparser.ConfigParser()
    if os.path.exists(path):
        try:
            parser.read(path, encoding="utf-8")
        except Exception:
            pass
    if not parser.has_section(GLOBAL_SECTION):
        parser.add_section(GLOBAL_SECTION)
    parser.set(GLOBAL_SECTION, GLOBAL_KEY, proxy or "")
    parser.set(GLOBAL_SECTION, GLOBAL_NOPROXY_KEY, no_proxy or "")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        parser.write(f)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Получение эффективного значения
# --------------------------------------------------------------------------

def _env_proxy() -> Optional[str]:
    for key in _ENV_KEYS:
        val = os.environ.get(key)
        if val and val.strip():          # пустые значения игнорируем
            return val.strip()
    return None


def _env_no_proxy() -> str:
    for key in _ENV_NOPROXY_KEYS:
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip()
    return ""


def get(session_path: Optional[str] = None, override=None) -> Tuple[Optional[str], str]:
    """Эффективный прокси и его источник. -> (normalized|None, source)."""
    if override is not None:
        return normalize_proxy(override), "call"
    sess = _load_session(session_path)
    if sess.get("proxy"):
        return normalize_proxy(sess["proxy"]), "session"
    glob = _load_global()
    if glob.get("proxy"):
        return normalize_proxy(glob["proxy"]), "global"
    env = _env_proxy()
    if env:
        try:
            return normalize_proxy(env), "env"
        except ValueError:
            return env, "env"
    return None, "none"


def get_no_proxy(session_path: Optional[str] = None) -> str:
    sess = _load_session(session_path)
    if sess.get("no_proxy"):
        return normalize_no_proxy(sess["no_proxy"])
    glob = _load_global()
    if glob.get("no_proxy"):
        return normalize_no_proxy(glob["no_proxy"])
    return normalize_no_proxy(_env_no_proxy())


def httpx_proxy(session_path: Optional[str] = None, override=None) -> Optional[str]:
    value, _ = get(session_path, override)
    return value


def requests_proxies(session_path: Optional[str] = None, override=None):
    value = httpx_proxy(session_path, override)
    return {"http": value, "https": value} if value else None


def aria2c_args(session_path: Optional[str] = None, override=None) -> List[str]:
    """aria2c не читает env-прокси — передаём флагами (проверено)."""
    args: List[str] = []
    value = httpx_proxy(session_path, override)
    if value:
        args.append(f"--all-proxy={value}")
        nop = get_no_proxy(session_path)
        if nop:
            args.append(f"--no-proxy={nop}")
    return args


def subprocess_env(session_path: Optional[str] = None, override=None) -> dict:
    """Env для subprocess (lynx/git): прокси + зачистка пустых переменных."""
    env = dict(os.environ)
    for key in list(env.keys()):
        if key.lower() in ("http_proxy", "https_proxy", "all_proxy") and not env[key].strip():
            env.pop(key, None)
    value = httpx_proxy(session_path, override)
    if value:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            env[key] = value
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)
        env.pop("all_proxy", None)
        nop = get_no_proxy(session_path)
        if nop:
            env["NO_PROXY"] = nop
    return env


# --------------------------------------------------------------------------
# Управление (для web action=proxy)
# --------------------------------------------------------------------------

def show(session_path: Optional[str] = None) -> dict:
    value, source = get(session_path)
    return {
        "proxy": value,
        "source": source,
        "no_proxy": get_no_proxy(session_path) or None,
        "masked": mask_proxy(value),
        "env_values": {k: os.environ.get(k) for k in _ENV_KEYS
                       if os.environ.get(k) not in (None, "")},
        "config_path": _project_config_path(),
        "session_path": session_settings_path(session_path),
    }


def set_proxy(proxy, session_path: Optional[str] = None, no_proxy=None,
              scope: str = None) -> dict:
    """Записать прокси. scope: session|global (по умолчанию session, если есть)."""
    normalized = normalize_proxy(proxy)
    scope = (scope or ("session" if session_path else "global")).strip().lower()
    nop = normalize_no_proxy(no_proxy) if no_proxy is not None else None
    if scope == "session":
        if not session_path:
            raise ValueError("scope=session требует session_path (или используй scope=global)")
        data = _load_session(session_path)
        data["version"] = SETTINGS_VERSION
        data["proxy"] = normalized or ""
        if nop is not None:
            data["no_proxy"] = nop
        else:
            nop = data.get("no_proxy", "")
        _save_session(session_path, data)
        stored = session_settings_path(session_path)
    elif scope == "global":
        existing = _load_global()
        nop_final = nop if nop is not None else existing.get("no_proxy", "")
        _save_global(normalized, nop_final)
        nop = nop_final
        stored = _project_config_path()
    else:
        raise ValueError(f"неизвестный scope: {scope} (session|global)")
    return {"scope": scope, "proxy": normalized, "masked": mask_proxy(normalized),
            "no_proxy": nop or None, "stored": stored}


def clear(session_path: Optional[str] = None, scope: str = None) -> dict:
    scope = (scope or ("session" if session_path else "global")).strip().lower()
    if scope == "session":
        if not session_path:
            raise ValueError("scope=session требует session_path")
        data = _load_session(session_path)
        data["proxy"] = ""
        data["no_proxy"] = ""
        _save_session(session_path, data)
        stored = session_settings_path(session_path)
    else:
        _save_global(None, "")
        stored = _project_config_path()
    return {"scope": scope, "proxy": None, "stored": stored}


# --------------------------------------------------------------------------
# Проверка работоспособности
# --------------------------------------------------------------------------

def _tcp_check(host: str, port: int, timeout: float) -> Tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test(session_path: Optional[str] = None, override=None, url: Optional[str] = None,
         timeout_sec: int = 15) -> dict:
    """Проверить прокси: TCP-доступность и (если дан url) реальный запрос.

    Никаких сервисов по умолчанию не опрашиваем: без url — только TCP-проверка
    самого прокси и подсказка передать url для полной проверки.
    """
    value, source = get(session_path, override)
    result = {"proxy": value, "source": source, "masked": mask_proxy(value),
              "configured": bool(value), "tcp": None, "http": None, "aria2c": None,
              "ok": False}
    if not value:
        result["error"] = "прокси не задан"
        return result
    host, port = proxy_host_port(value)
    if not host or not port:
        result["error"] = "не удалось разобрать host:port прокси"
        return result
    ok_tcp, err = _tcp_check(host, port, min(max(timeout_sec, 2), 30))
    result["tcp"] = {"ok": ok_tcp, "host": host, "port": port, "error": err or None}

    if url and str(url).strip() and str(url).strip().startswith(("http://", "https://")):
        import httpx
        t0 = time.time()
        try:
            r = httpx.get(url, proxy=value, timeout=timeout_sec, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
            result["http"] = {"ok": r.status_code < 400, "status": r.status_code,
                              "type": (r.headers.get("content-type") or "").split(";")[0],
                              "bytes": len(r.content),
                              "elapsed": f"{time.time() - t0:.2f}s"}
        except Exception as e:
            result["http"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            from tools import web as _web
            if _web._aria2c_available():
                import tempfile
                with tempfile.TemporaryDirectory(prefix="botinok_proxytest_") as d:
                    dest = os.path.join(d, "probe")
                    aok, aerr = _web._aria2c_download(url, dest, None,
                                                      min(max(timeout_sec, 10), 60),
                                                      proxy=value)
                    result["aria2c"] = {"ok": aok, "error": aerr or None,
                                        "bytes": (os.path.getsize(dest)
                                                  if aok and os.path.exists(dest) else 0)}
        except Exception as e:
            result["aria2c"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    result["ok"] = bool(ok_tcp) and (result["http"] is None or result["http"].get("ok"))
    return result
