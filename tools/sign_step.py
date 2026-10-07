#!/usr/bin/env python3
"""sign_step — внутренняя подпись хода самой моделью (этап 6 плана
wiki/concepts/context_memory_research.md).

Харнес подписаний: модель один раз за ход (перед финальным ответом) вызывает
sign_step с жёстной схемой: goal/done ≤15 слов, status enum, entities — только
закрытый список того, что харнес реально видел в ходе (пути/URL/аргументы
инструментов). Валидация подстрокой по observed; левая сущность → одна ретрай-
попытка с текстом ошибки, затем отказ и механическая строка дайджеста.
Подпись кладётся в signatures.json и подхватывается core/session_digest
(поле Window.sign → строка блока FORGOTTEN_INDEX). В чат и в messages не попадает.
"""

import json
import os
import re
import time
from typing import Dict, List, Optional

_STATUSES = ("progress", "blocked", "decision", "answered")
_STATUS_ALIASES = {
    "in_progress": "progress", "работа": "progress", "прогресс": "progress",
    "done": "answered", "готово": "answered", "ответ": "answered",
    "заблокирован": "blocked", "заблокировано": "blocked",
    "решение": "decision", "выбор": "decision",
}

_observed: Dict[str, set] = {}
_signatures: Dict[str, Optional[Dict]] = {}
_attempts: Dict[str, int] = {}
_done: Dict[str, bool] = {}

_WORD_RE = re.compile(r"\S+")


def _norm_session(session_path: Optional[str]) -> str:
    sp = str(session_path or os.environ.get("BOTINOK_SESSION_PATH") or "").strip()
    return sp or "."


def observe(session_path: Optional[str], texts) -> None:
    """Харнес регистрирует, что реально мелькало в ходе (пути, URL, аргументы)."""
    key = _norm_session(session_path)
    bucket = _observed.setdefault(key, set())
    if isinstance(texts, str):
        texts = [texts]
    for t in texts or []:
        s = str(t or "").strip().lower()
        if s:
            bucket.add(s)


def reset_turn(session_path: Optional[str]) -> None:
    key = _norm_session(session_path)
    _observed[key] = set()
    _signatures.pop(key, None)
    _attempts[key] = 0
    _done[key] = False


def has_signature(session_path: Optional[str]) -> bool:
    return _signatures.get(_norm_session(session_path)) is not None


def pop_signature(session_path: Optional[str]) -> Optional[Dict]:
    return _signatures.pop(_norm_session(session_path), None)


def _clamp_words(text: str, limit: int = 15) -> str:
    words = _WORD_RE.findall(str(text or "").strip())
    return " ".join(words[:limit])


def _norm_status(status) -> str:
    s = str(status or "").strip().lower()
    if s in _STATUSES:
        return s
    return _STATUS_ALIASES.get(s, "progress")


def _norm_entities(entities) -> List[str]:
    if entities is None:
        return []
    if isinstance(entities, str):
        items = re.split(r"[,\n;]+", entities)
    elif isinstance(entities, (list, tuple)):
        items = list(entities)
    else:
        items = [entities]
    out: List[str] = []
    for it in items:
        s = str(it or "").strip()
        if s and s not in out:
            out.append(s)
    return out[:6]


def _persist(session_path: str, sign: Dict) -> None:
    """Кладёт подпись в signatures.json, привязывая к текущему последнему окну."""
    window_id = -1
    try:
        from core import session_digest
        windows = session_digest.build_windows(session_path)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        for w in windows:
            if w.ts_end <= now_iso:
                window_id = w.window_id
        if window_id == -1 and windows:
            window_id = windows[-1].window_id
    except Exception:
        pass
    sign = dict(sign)
    sign["window_id"] = window_id
    sign["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = os.path.join(session_path, "signatures.json")
    try:
        records = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                if not isinstance(records, list):
                    records = []
            except (json.JSONDecodeError, OSError):
                records = []
        records = [r for r in records if r.get("window_id") != window_id]
        records.append(sign)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def sign_step_tool(goal: str = "", done: str = "", status: str = "progress",
                   entities=None, session_path: Optional[str] = None, **kwargs) -> str:
    """Подпись хода. Результат всегда «ok» — инструмент не спорит с моделью."""
    key = _norm_session(session_path)
    if _done.get(key) or has_signature(key):
        return "ok"
    observed = _observed.get(key, set())
    ents = _norm_entities(entities)
    bad = [e for e in ents if not any(e.lower() in obs for obs in observed)]
    if bad:
        _attempts[key] = _attempts.get(key, 0) + 1
        if _attempts[key] >= 2:
            # отказ: механическая строка дайджеста, дальше не мучаем
            _done[key] = True
            return "ok"
        return ("Ошибка: эти сущности не встречались в ходе: "
                + ", ".join(bad[:6])
                + ". Вызови sign_step ещё раз, указав в entities только то, "
                "что реально упоминалось в этом ходе (пути, URL, имена инструментов), "
                "или оставь entities пустым.")
    sign = {
        "goal": _clamp_words(goal),
        "done": _clamp_words(done),
        "status": _norm_status(status),
        "entities": ents,
    }
    _signatures[key] = sign
    _done[key] = True
    _persist(key, sign)
    return "ok"
