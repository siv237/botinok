# -*- coding: utf-8 -*-
"""Реестр провайдеров OpenAI-совместимых API.

Каждый провайдер публикует канонический адрес API, но путь у всех свой:
Fireworks — /inference/v1, Z.ai — /api/paas/v4, Aliyun — /compatible-mode/v1
и т.п. Гадать по префиксам долго и неполно. Адрес подтягивается из открытой
базы models.dev (репозиторий anomalyco/models.dev): скачивается один раз,
сжимается до списка «имя/домен → базовый URL» и кэшируется ТОЛЬКО локально
рядом с config.cfg. Список провайдеров в коде НЕ вшит — он актуализируется
без правок бота.

Сеть здесь необязательна: если кэша нет и реестр недоступен, функции вернут
пустой результат, а визард продолжит обычным перебором типовых точек входа.
"""

import json
import os
import time
from urllib.parse import urlparse

import requests

REGISTRY_URL = "https://models.dev/api.json"
# Недели две: список меняется медленно, а запросы к реестру — редкие.
CACHE_TTL = 14 * 24 * 3600


def _cache_path(sm):
    cfg = getattr(sm, 'config_path', None) or os.path.expanduser('~/.config/botinok/config.cfg')
    return os.path.join(os.path.dirname(cfg) or '.', 'provider_registry.json')


def _load_cache(sm):
    try:
        with open(_cache_path(sm), encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('providers'), list):
            return data
    except Exception:
        pass
    return None


def _save_cache(sm, providers):
    try:
        with open(_cache_path(sm), 'w', encoding='utf-8') as f:
            json.dump({'ts': time.time(), 'providers': providers}, f,
                      ensure_ascii=False)
    except Exception:
        pass


def build_providers(raw):
    """Сжимает полный реестр до списка записей {id, name, host, api}."""
    out, seen = [], set()
    for pid, p in (raw or {}).items():
        if not isinstance(p, dict):
            continue
        api = p.get('api')
        if not (isinstance(api, str) and api.startswith('http')):
            continue
        host = urlparse(api).netloc.lower()
        if not host or host in seen:
            continue
        seen.add(host)
        out.append({'id': pid, 'name': p.get('name') or pid,
                    'host': host, 'api': api.rstrip('/')})
    return out


def refresh(sm, timeout=25):
    """Скачивает реестр и сохраняет компактный список. Возвращает список
    записей или None при неудаче (нет сети, неожиданный формат)."""
    try:
        r = requests.get(REGISTRY_URL, timeout=timeout)
        if r.status_code != 200:
            return None
        providers = build_providers(r.json())
    except Exception:
        return None
    if not providers:
        return None
    _save_cache(sm, providers)
    return providers


def load(sm):
    """Список провайдеров из локального кэша. В сеть НЕ ходит — скачивание
    возможно только явным действием пользователя (refresh)."""
    cache = _load_cache(sm)
    return list(cache['providers']) if cache else []


def is_fresh(sm):
    cache = _load_cache(sm)
    return bool(cache and time.time() - float(cache.get('ts', 0)) <= CACHE_TTL)


def updated_at(sm):
    """Время последнего обновления кэша (unix) или 0."""
    cache = _load_cache(sm)
    return float(cache.get('ts', 0)) if cache else 0.0


def age_text(sm):
    """Человекочитаемая давность обновления базы."""
    ts = updated_at(sm)
    if not ts:
        return "нет данных"
    d = int(max(0, time.time() - ts))
    if d < 60:
        return "только что"
    if d < 3600:
        return f"{d // 60} мин назад"
    if d < 86400:
        return f"{d // 3600} ч назад"
    return f"{d // 86400} дн назад"


def updated_date(sm):
    """Дата обновления базы (YYYY-MM-DD HH:MM) или '—'."""
    ts = updated_at(sm)
    if not ts:
        return "—"
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))


def host_of(url):
    u = (url or '').strip()
    if not u:
        return ''
    if '://' not in u:
        u = 'https://' + u
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ''


def lookup(providers, url):
    """Канонический базовый URL провайдера по хосту адреса или None."""
    host = host_of(url)
    if not host:
        return None
    for e in (providers or []):
        if e.get('host') == host:
            return e.get('api')
    return None


def search(providers, query, limit=40):
    """Поиск по имени, id и домену (регистронезависимо). Пустой запрос —
    весь список. Совпадения по началу строки идут раньше прочих."""
    q = (query or '').strip().lower()
    if not q:
        return list(providers or [])[:limit]
    starts, contains = [], []
    for e in (providers or []):
        hay = f"{e.get('name','')} {e.get('id','')} {e.get('host','')}".lower()
        if not all(tok in hay for tok in q.split()):
            continue
        (starts if hay.startswith(q) or e.get('host', '').startswith(q)
         else contains).append(e)
    return (starts + contains)[:limit]
