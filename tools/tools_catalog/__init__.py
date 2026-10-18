#!/usr/bin/env python3
"""tools — мета-инструмент ступенчатого раскрытия инструментов.

В payload модели всегда лежат только: этот мета-инструмент, sign_step и
ранее включённые инструменты; остальные перечислены кратким каталогом в
system-промпте. Модели нужен инструмент → tools(action=enable, name=…) —
со следующего запроса его полная схема попадает в payload (и остаётся до конца
сессии). Экономия фиксированной базы: ~9k токенов схем → ~0.4k каталога.

Набор инструментов — плагинный (папки в `tools/` с манифестом tool.json):
каталог, «всегда включённые» и известные имена берутся из сканирования
`core/tool_discovery.py`, поэтому добавление/удаление папки сразу меняет
и каталог, и payload, и доступность `enable`.
"""

import json
import os
from typing import Optional

_enabled: dict = {}


def _always_on() -> set:
    """Ядро харнесса: инструменты, всегда присутствующие в payload.

    Читается из манифестов (`"always_on": true`), а не из списка в коде:
    инструмент может сам объявить себя всегда включённым. Литеральный набор
    используется только как страховка, когда сканирование недоступно (тогда
    честнее показать ядро, чем остаться вообще без инструментов).
    """
    try:
        from core.tool_discovery import always_on_names
        names = always_on_names()
    except Exception:
        names = None
    if names is None:
        return {"tools", "sign_step", "session_memory"}
    return set(names)


def _known():
    """Все подключённые имена инструментов (основные + алиасы).

    None — если сканирование недоступно (тогда фильтровать нельзя, чтобы не
    потерять включённое из-за сбоя); пустое множество — валидный результат
    (инструментов нет вовсе).
    """
    try:
        from core.tool_discovery import known_names
        return known_names()
    except Exception:
        return None



def _norm_session(session_path: Optional[str]) -> str:
    sp = str(session_path or os.environ.get("BOTINOK_SESSION_PATH") or "").strip()
    return sp or "."


def _state_path(session_path: str) -> str:
    return os.path.join(session_path, "enabled_tools.json")


def _load(session_path: str) -> set:
    if session_path in _enabled:
        return _enabled[session_path]
    names = set()
    try:
        with open(_state_path(session_path), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            names = {str(x) for x in data}
    except (OSError, json.JSONDecodeError):
        pass
    _enabled[session_path] = names
    return names


def _save(session_path: str, names: set) -> None:
    try:
        with open(_state_path(session_path), "w", encoding="utf-8") as f:
            json.dump(sorted(names), f, ensure_ascii=False)
    except OSError:
        pass


def enabled_tools(session_path: Optional[str]):
    """Имена инструментов, которые харнес кладёт в payload наравне с ядром."""
    enabled = _load(_norm_session(session_path))
    known = _known()
    if known is not None:
        # Инструмент мог исчезнуть (папку удалили) — старое имя в
        # enabled_tools.json больше ничего не включает.
        enabled = {n for n in enabled if n in known}
    return set(_always_on()) | enabled


def catalog_lines(tm) -> list:
    """Краткий каталог: имя — первое предложение описания (≤160 знаков)."""
    lines = []
    try:
        defs = tm.get_tool_definitions()
        items = defs.items() if isinstance(defs, dict) else [(d["function"]["name"], d) for d in defs]
    except Exception:
        return lines
    always = _always_on()
    for name, d in sorted(items):
        if name in always:
            continue
        desc = str(((d or {}).get("function") or {}).get("description") or "")
        first = desc.split(". ")[0].split(";")[0].strip().rstrip(".")
        if len(first) > 160:
            first = first[:157] + "..."
        lines.append(f"- {name}: {first}")
    return lines


def catalog_text(tm) -> str:
    # Список «всегда доступны» берём из манифестов: переключение `always_on`
    # у плагина не должно расходиться с тем, что читает модель.
    always = sorted(_always_on())
    hint = ", ".join(always) if always else "—"
    extra = (" (session_memory — история сессии, главный инструмент при "
             "прерванном/вытесненном контексте)" if "session_memory" in always else "")
    return (
        "ИНСТРУМЕНТЫ (краткий каталог; схемы по запросу):\n"
        f"В твоём запросе всегда доступны: {hint}{extra}. "
        "Нужен инструмент из каталога — вызови tools(action=enable, name=…), "
        "его полная схема появится в следующем запросе и останется на всю сессию. "
        "Включай только то, чем будешь пользоваться в этом ходе.\n"
        + "\n".join(catalog_lines(tm))
    )


def tools_catalog_tool(action: str = "list", name: str = "",
                       session_path: Optional[str] = None, **kwargs) -> str:
    action = str(action or "list").strip().lower()
    sess = _norm_session(session_path)
    try:
        from core.tool_manager import ToolManager
        tm = ToolManager()
    except Exception as e:
        return f"Error: ToolManager недоступен: {e}"

    known = set(tm._tool_registry.keys())

    if action in ("list", "каталог"):
        return catalog_text(tm)

    if action in ("enable", "включить", "on"):
        n = str(name or kwargs.get("tool") or "").strip().lower()
        if not n:
            return "Error: укажи name=имя_инструмента. Каталог: tools(action=list)"
        if n in _always_on():
            return f"ok: {n} и так всегда доступен"
        if n not in known:
            return f"Error: неизвестный инструмент '{n}'. Есть: {', '.join(sorted(known))}"
        names = _load(sess)
        if n in names:
            return f"ok: {n} уже включён"
        names.add(n)
        _save(sess, names)
        desc = str(((tm._descriptions.get(n) or {}).get("function") or {}).get("description") or "")
        return (f"ok: {n} включён — его схема будет в следующем запросе (до конца сессии). "
                + (f"Кратко: {desc[:300]}" if desc else ""))

    if action in ("disable", "выключить"):
        n = str(name or "").strip().lower()
        names = _load(sess)
        names.discard(n)
        _save(sess, names)
        return f"ok: {n} выключен"

    return f"Error: неизвестное действие '{action}'. Есть: list, enable(name), disable(name)."
