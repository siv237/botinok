#!/usr/bin/env python3
"""
Менеджер загрузок: история и проверка целостности скачанных файлов.

Хранит по каждой загрузке (url + назначение): статус (completed / incomplete /
error), размер, sha256, тип и время. Позволяет:
  * понять, что уже скачано, где лежит и целое ли оно;
  * найти недокачанные/битые загрузки и докачать их (aria2c -c).

История — JSON рядом с загрузками сессии:
  <session_path>/downloads/.downloads_history.json
или ~/.botinok/downloads/.downloads_history.json, если сессии нет.

Не содержит доменной логики — только учёт файлов.
"""

import hashlib
import json
import os
import time
from typing import Dict, List, Optional, Tuple

HISTORY_NAME = "history.json"
DEFAULT_HISTORY = os.path.join(os.path.expanduser("~"), ".botinok", "downloads", HISTORY_NAME)


def _history_path(session_path: Optional[str] = None) -> str:
    """Глобальная история загрузок web — не зависит от сессии.

    Переопределяется через env BOTINOK_DOWNLOAD_HISTORY.
    """
    override = os.environ.get("BOTINOK_DOWNLOAD_HISTORY")
    if override:
        return override
    return DEFAULT_HISTORY


def _key(url: str, dest: Optional[str]) -> str:
    return f"{url}\n{dest or ''}"


def _load(session_path: Optional[str]) -> Dict[str, dict]:
    path = _history_path(session_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(session_path: Optional[str], data: Dict[str, dict]) -> None:
    path = _history_path(session_path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def record(session_path: Optional[str], url: str, dest: Optional[str],
           status: str, total: Optional[int] = None, sha256: Optional[str] = None,
           file_type: Optional[str] = None, error: Optional[str] = None,
           engine: Optional[str] = None) -> dict:
    """Записать/обновить (глобальную) запись о загрузке."""
    data = _load(session_path)
    key = _key(url, dest)
    entry = data.get(key, {})
    entry.update({
        "url": url,
        "dest": dest,
        "status": status,
        "total": total if total is not None else entry.get("total"),
        "sha256": sha256 or entry.get("sha256"),
        "type": file_type or entry.get("type"),
        "engine": engine or entry.get("engine"),
        "session": session_path or entry.get("session"),
        "error": error,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    if "created" not in entry:
        entry["created"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    # Файл только что скачан и sha256 посчитан самим загрузчиком — это и есть
    # глубокая проверка: кэшируем, чтобы `downloads verify=true` не хешировал
    # свежую загрузку повторно.
    if status == "completed" and dest:
        try:
            st = os.stat(dest)
            entry["verified_size"] = st.st_size
            entry["verified_mtime_ns"] = st.st_mtime_ns
            entry["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        except OSError:
            entry.pop("verified_size", None)
            entry.pop("verified_mtime_ns", None)
    data[key] = entry
    _save(session_path, data)
    return entry


def find(session_path: Optional[str], url: str,
         dest: Optional[str] = None) -> Optional[dict]:
    return _load(session_path).get(_key(url, dest))


def list_entries(session_path: Optional[str]) -> List[dict]:
    return list(_load(session_path).values())


def sha256_file(path: str, chunk: int = 1024 * 1024) -> str:
    """sha256 файла потоком (не тянем гигабайты в память)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify(entry: dict, deep: bool = False) -> Tuple[bool, str]:
    """Проверить, что файл на месте и не обрезан. -> (ok, причина).

    По умолчанию — быстрая проверка: наличие, непустой каталог, размер против
    записанного `total`. sha256 **не** пересчитывается: в истории бывают файлы
    на гигабайты (модели, ISO), и хеширование всей истории на каждый вызов
    `web action=downloads` занимало минуты — выглядело как зависание.

    `deep=True` — сверить sha256 (потоком, чанками). Успешная сверка
    кэшируется в записи (`verified_size`/`verified_mtime_ns`): пока файл не
    изменился, повторная глубокая проверка не хеширует его снова.
    """
    dest = entry.get("dest")
    if not dest:
        return False, "не задан путь"
    if not os.path.exists(dest):
        return False, "файл отсутствует"
    if os.path.isdir(dest):
        # Торрент/многофайловая раздача: проверяем, что каталог не пуст.
        try:
            if any(os.scandir(dest)):
                return True, "ок (каталог)"
        except Exception:
            pass
        return False, "каталог пуст (загрузка не завершена)"
    size = os.path.getsize(dest)
    total = entry.get("total")
    if total and size != total:
        return False, f"недокачан: {size} из {total} байт"
    sha = entry.get("sha256")
    if not sha:
        return True, "ок"
    try:
        st = os.stat(dest)
    except OSError as e:
        return False, f"ошибка чтения: {e}"
    if (entry.get("verified_size") == st.st_size
            and entry.get("verified_mtime_ns") == st.st_mtime_ns):
        return True, "ок (sha256 сверен ранее)"
    if not deep:
        return True, "ок (по размеру; sha256 не пересчитывался)"
    try:
        digest = sha256_file(dest)
    except Exception as e:
        return False, f"ошибка чтения: {e}"
    if digest != sha:
        return False, "sha256 не совпадает"
    return True, "ок (sha256 сверен)"


def record_verification(session_path: Optional[str], entry: dict) -> None:
    """Запомнить успешную глубокую сверку файла (кэш `verified_*`)."""
    dest = entry.get("dest")
    try:
        st = os.stat(dest)
    except OSError:
        return
    data = _load(session_path)
    key = _key(entry.get("url"), dest)
    stored = data.get(key)
    if stored is None:
        return
    stored["verified_size"] = st.st_size
    stored["verified_mtime_ns"] = st.st_mtime_ns
    stored["verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data[key] = stored
    _save(session_path, data)


def pending(session_path: Optional[str], deep: bool = False) -> List[dict]:
    out = []
    for entry in list_entries(session_path):
        ok, reason = verify(entry, deep=deep)
        if not ok:
            item = dict(entry)
            item["reason"] = reason
            out.append(item)
    return out
