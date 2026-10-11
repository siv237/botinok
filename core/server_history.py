"""История использованных серверов для автоподстановки в мастере.

Пишется в server_history.json рядом с config.cfg (не в git). Запись:
backend, url, api_key, ts, count.
"""

import json
import os
import time


def _path(sm):
    cfg = getattr(sm, 'config_path', None) or os.path.expanduser('~/.config/botinok/config.cfg')
    return os.path.join(os.path.dirname(cfg) or '.', 'server_history.json')


def load(sm):
    try:
        with open(_path(sm), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def record(sm, backend, url, api_key=""):
    url = (url or '').strip().rstrip('/')
    if not url:
        return
    data = load(sm)
    key = f"{backend}|{url}"
    ent = data.get(key) or {}
    ent.update({'backend': backend, 'url': url,
                'api_key': (api_key or '').strip() or ent.get('api_key', ''),
                'ts': time.time(), 'count': int(ent.get('count', 0)) + 1})
    data[key] = ent
    try:
        with open(_path(sm), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def recent(sm, backend=None, limit=10):
    items = [e for e in load(sm).values() if isinstance(e, dict) and e.get('url')]
    if backend:
        items = [e for e in items if e.get('backend') == backend]
    items.sort(key=lambda e: e.get('ts', 0), reverse=True)
    return items[:limit]


def label(entry):
    """Строка списка: дата, тип, адрес, ключ (обрезан в середине)."""
    key = (entry.get('api_key') or '').strip()
    key = (f"{key[:4]}…{key[-4:]}" if len(key) > 8 else '•' * len(key)) if key else "без ключа"
    when = time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.get('ts', 0)))
    return f"{when}  {entry.get('backend', '?'):<7} {entry['url']}  {key}"
