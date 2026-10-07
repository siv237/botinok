#!/usr/bin/env python3
"""Механический дайджест сессии: окна вызовов модели, облака терминов, строки индекса.

Окно = один вызов модели: границы — события ``metrics`` в ``session_raw.log``
(каждое = конец вызова). Инструменты из ``tools.log`` (status=completed) и записи
``context.json`` привязываются по таймстампам. Без единого LLM-вызова.

Метрика качества — recall: строка окна обязана давать указатели (turn_id,
индексы сообщений, подписи инструментов), а не читаться как проза.

См. wiki/concepts/context_memory_research.md (этап 1 плана).
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    from pymorphy3 import MorphAnalyzer
    _MORPH = MorphAnalyzer()
except Exception:  # пакет не установлен — работаем суффиксным стеммером
    _MORPH = None

_KEEP_POS = {"NOUN", "ADJF", "ADJS", "VERB", "INFN", "BREV", "COMP", "PROPN"}

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_][A-Za-zА-Яа-яЁё0-9_.\-/]{3,}")
_ENTITY_RE = re.compile(
    r"(?:https?://\S+|[\w./-]+\.(?:py|md|json|log|cfg|sh|txt|html?|csv|ya?ml|toml|xml|ini)\b"
    r"|[a-z][a-z0-9]*_[a-z0-9_]+)",
    re.I,
)
_CYR_RE = re.compile(r"[а-яё]", re.I)

_STOP = frozenset("""
это вот еще ещё очень всего также можно нужно тогда сейчас просто который было есть
понимаю пожалуйста должен могу ваше спасибо давайте конечно хорошо отлично прошу давай просьба
важный требование сессия папка файл если какой через без себя буду кажется важно дальше раз
подумай будет хотеть делать сделать сделал делает после перед тем как или хотя чтобы над
about with that this from have will there what when them they here where just like
should could would please session file tool tools answer user assistant system message
""".split())

# Минимальный русский суффиксный стеммер — fallback без pymorphy3.
_RU_SUFFIXES = sorted(
    "иями иею ами ах ами ов ево емя ами ями ами ов ев ам ями ой ей иями ией ая яя ое ее ые ие "
    "ого его ему ыми ими ому ых их ах ох ами "
    "ешь ует уют ите ет ют ем им ую ют ая яя "
    "ло ли ла лем лам лами "
    "ом ем ам ям ами "
    "ах ох ерд".split(),
    key=len, reverse=True,
)


def _stem_ru(word: str) -> str:
    w = word.lower()
    for suf in _RU_SUFFIXES:
        if len(w) - len(suf) >= 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def lemmatize(word: str) -> Optional[str]:
    """Лемма слова; None — если слово не заслуживает попадания в облако."""
    if _CYR_RE.search(word):
        w = word.lower()
        if _MORPH is not None:
            try:
                p = _MORPH.parse(w)[0]
                if p.tag.POS in _KEEP_POS:
                    return p.normal_form
                return None
            except Exception:
                pass
        return _stem_ru(w) if len(w) > 4 else None
    w = word.lower()
    if w.isdigit() or "_" in w and w.count("_") > 3:
        return None
    return w


def slugify_url(u: str) -> str:
    m = re.match(r"https?://(?:duckduckgo\.com/l/\?uddg=)?([^?#]+)", u)
    if not m:
        return u[:40]
    parts = [p for p in m.group(1).rstrip("/").split("/") if p and not re.fullmatch(r"[0-9a-f]{16,}", p)]
    return "/".join(parts[:3])


def _iter_jsonl(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


@dataclass
class Window:
    """Один вызов модели: от первого чанка после предыдущего metrics до metrics."""
    window_id: int
    ts_start: str = ""
    ts_end: str = ""
    prompt_eval_count: int = 0
    eval_count: int = 0
    final_text: str = ""
    tools: List[Dict] = field(default_factory=list)      # {tool, arguments, size_kb, timestamp}
    call_args: List[str] = field(default_factory=list)   # аргументы tool_calls, порождённых этим окном
    msg_indices: List[int] = field(default_factory=list)  # номера записей context.json.history
    turn_ids: List[int] = field(default_factory=list)     # номера ходов session_memory
    sign: Optional[Dict] = None                           # подпись sign_step (этап 6), если есть
    cloud: str = ""                                       # предвычисленное облако (build_digest_lines)
    selfpath: str = ""                                    # имя своей папки сессии (шум в облаке)

    @property
    def ctx_used(self) -> int:
        return self.prompt_eval_count + self.eval_count


def _turn_numbers(history: List[Dict]) -> List[int]:
    """Нумерация ходов как в tools/session_memory.parse_turns: ход закрывается
    новым непустым user; подряд идущие дубли user не создают фантомный ход."""
    nums: List[int] = []
    counter = 0
    last_user_text = None
    for entry in history:
        role = entry.get("role")
        text = str(entry.get("content") or "").strip()
        if role == "user":
            if not text:
                nums.append(counter or 1)
                continue
            if text == last_user_text:
                nums.append(counter)
                continue
            counter += 1
            last_user_text = text
            nums.append(counter)
        else:
            nums.append(counter or 1)
    return nums


def build_windows(session_path: str) -> List[Window]:
    """Режет session_raw.log по metrics-событиям, привязывает tools.log и context.json."""
    windows: List[Window] = []
    cur_text: List[str] = []
    cur_start = ""
    wid = 0
    selfpath = os.path.basename(os.path.normpath(session_path))
    raw = os.path.join(session_path, "session_raw.log")
    for ev in _iter_jsonl(raw):
        ts = str(ev.get("timestamp") or "")
        etype = ev.get("type")
        if etype == "metrics":
            w = Window(
                window_id=wid,
                ts_start=cur_start or ts,
                ts_end=ts,
                final_text="".join(cur_text),
                selfpath=selfpath,
            )
            m = ev.get("metrics") or {}
            try:
                w.prompt_eval_count = int(m.get("prompt_eval_count") or 0)
                w.eval_count = int(m.get("eval_count") or 0)
            except (TypeError, ValueError):
                pass
            windows.append(w)
            wid += 1
            cur_text = []
            cur_start = ""
            continue
        if not cur_start and ts:
            cur_start = ts
        if etype == "response":
            cur_text.append(str(ev.get("content") or ""))
    # хвост без metrics (обрывок последнего вызова) — дописываем в последнее окно
    if cur_text and windows:
        windows[-1].final_text += "".join(cur_text)

    # tools.log: completed-события привязываются к первому окну с ts_end >= ts события
    tools_path = os.path.join(session_path, "tools.log")
    for ev in _iter_jsonl(tools_path):
        if ev.get("status") != "completed":
            continue
        ts = str(ev.get("timestamp") or "")
        target = None
        for w in windows:
            if w.ts_end and ts and ts <= w.ts_end:
                target = w
                break
        if target is None and windows:
            target = windows[-1]
        if target is not None:
            target.tools.append({
                "tool": ev.get("tool"),
                "arguments": ev.get("arguments") or {},
                "size_kb": ev.get("size_kb"),
                "timestamp": ts,
            })

    # context.json: индексы сообщений и номера ходов по таймстампам
    try:
        with open(os.path.join(session_path, "context.json"), "r", encoding="utf-8", errors="ignore") as f:
            history = (json.load(f) or {}).get("history") or []
    except (OSError, json.JSONDecodeError):
        history = []
    turns = _turn_numbers(history)
    for idx, msg in enumerate(history):
        ts = str(msg.get("timestamp") or "")
        target = None
        for w in windows:
            if w.ts_end and ts and ts <= w.ts_end:
                target = w
                break
        if target is None and windows:
            target = windows[-1]
        if target is not None:
            target.msg_indices.append(idx)
            tn = turns[idx] if idx < len(turns) else 0
            if tn and tn not in target.turn_ids:
                target.turn_ids.append(tn)
            for tc in (msg.get("tool_calls") or []):
                try:
                    fn = tc.get("function") or {}
                    target.call_args.append(f"{fn.get('name','')} {fn.get('arguments','')}")
                except AttributeError:
                    continue

    # подписи sign_step (этап 6): window_id → goal/done/status/entities
    try:
        with open(os.path.join(session_path, "signatures.json"), "r", encoding="utf-8", errors="ignore") as f:
            records = json.load(f)
        if isinstance(records, list):
            by_window = {}
            for rec in records:
                try:
                    by_window[int(rec.get("window_id", -1))] = rec
                except (TypeError, ValueError):
                    continue
            for w in windows:
                if w.window_id in by_window:
                    w.sign = by_window[w.window_id]
    except (OSError, json.JSONDecodeError):
        pass
    return windows


def window_terms(window: Window, prev_clouds: Optional[List[str]] = None,
                 cross_ratio: float = 0.7) -> Counter:
    """Термы окна с весами: леммы из ответа + аргументов инструментов, сущности весом выше."""
    parts = [window.final_text]
    parts.extend(window.call_args)
    for t in window.tools:
        for v in (t.get("arguments") or {}).values():
            parts.append(str(v))
    blob = "\n".join(parts)
    selfpath = ""
    entities = {slugify_url(e) for e in _ENTITY_RE.findall(blob)}
    scores: Counter = Counter()
    selfpath = (window.selfpath or "").lower()
    for e in entities:
        if e and len(e) >= 4 and not (selfpath and selfpath in e.lower()):
            scores[e] += 3
    for tok in _TOKEN_RE.findall(blob):
        if tok.isdigit():
            continue
        lem = lemmatize(tok)
        if not lem or lem in _STOP or lem in entities:
            continue
        if selfpath and selfpath in lem.lower():
            continue
        scores[lem] += 1
    # отсев сквозных терминов (в >=cross_ratio предыдущих облаков)
    if prev_clouds and len(prev_clouds) >= 3:
        frequent = {
            w for w in scores
            if sum(1 for c in prev_clouds if w in c.split()) >= max(2, cross_ratio * len(prev_clouds))
        }
        filtered = Counter({w: s for w, s in scores.items() if w not in frequent})
        if filtered:
            return filtered
    return scores


def window_cloud(window: Window, prev_clouds: Optional[List[str]] = None,
                 cross_ratio: float = 0.7) -> str:
    """≤10 лемм окна — компактный «микро-чейнжлог» одного вызова модели."""
    scores = window_terms(window, prev_clouds, cross_ratio)
    top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    return " ".join(w for w, _ in top)


def _tool_signatures(window: Window, limit: int = 4) -> str:
    sigs = []
    for t in window.tools[:limit]:
        args = t.get("arguments") or {}
        arg = str(next(iter(args.values()), ""))[:28].replace("\n", " ") if args else ""
        sigs.append(f"{t.get('tool')}({arg})" if arg else str(t.get("tool")))
    if len(window.tools) > limit:
        sigs.append(f"+{len(window.tools) - limit}")
    return ", ".join(sigs)


def _turn_pointer(window: Window) -> str:
    if window.turn_ids:
        ids = sorted(set(window.turn_ids))
        rng = f"{ids[0]}-{ids[-1]}" if len(ids) > 1 else str(ids[0])
        return f"sm get_turn turn_id={rng}"
    if window.msg_indices:
        return f"context.json#msg={window.msg_indices[0]}-{window.msg_indices[-1]}"
    return "sm get_turn"


def window_line(window: Window) -> str:
    """Двухстрочная запись индекса забытого (формат §7 плана)."""
    cloud = window.cloud or window_cloud(window)
    hhmmss = window.ts_end[11:19] if len(window.ts_end) >= 19 else "--:--:--"
    head = f"## [{hhmmss}] w{window.window_id:02d} ☁ {cloud}"
    if window.sign:
        goal = str(window.sign.get("goal") or "").strip()
        done = str(window.sign.get("done") or "").strip()
        if goal or done:
            head += f"   goal: {goal} | done: {done}"
    tail = f"   {_turn_pointer(window)} | tools: {_tool_signatures(window)} | ctx={window.ctx_used}"
    return head + "\n" + tail


def merge_old_lines(lines: List[str]) -> str:
    """Иерархическое сжатие древних строк индекса: частотный переизбранный
    терминов + счётчик окон. Без LLM."""
    n = 0
    terms: Counter = Counter()
    for line in lines:
        if not line.startswith("## "):
            continue
        n += 1
        m = re.search(r"☁ (.+?)(?:\s{2,}goal:|$)", line)
        if m:
            for w in m.group(1).split():
                terms[w] += 1
    top = sorted(terms.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    return f"## [merged] ×{n} ☁ " + " ".join(w for w, _ in top)


def build_digest_lines(windows: List[Window], cross_ratio: float = 0.7) -> List[str]:
    """Строки индекса для списка окон (облака считаются инкрементально — детерминизм)."""
    lines: List[str] = []
    clouds: List[str] = []
    for w in windows:
        cloud = window_cloud(w, clouds, cross_ratio)
        w.cloud = cloud  # type: ignore[attr-defined]
        clouds.append(cloud)
        lines.extend(window_line(w).split("\n"))
    return lines
