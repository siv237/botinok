#!/usr/bin/env python3
"""Проверка синтаксиса без запуска кода и без dangerous mode.

В процессе:
  * stdlib-парсеры: `ast` (python), `json`, `tomllib`, `yaml.safe_load`, `xml`;
  * tree-sitter (`tree-sitter-language-pack`): python, json, yaml, toml, bash,
    javascript, typescript, html.

Никакой код не исполняется. При неоднозначном типе возвращаются кандидаты,
и вызывающая сторона предлагает выбрать `kind=`.
"""

import json
import os
from typing import Dict, List, Optional

from core.file_kinds import detect_kinds, normalize_kind

SUPPORTED_KINDS = (
    "python", "json", "yaml", "toml", "xml",
    "bash", "javascript", "typescript", "html",
)

_TS_LANGS = {
    "python": "python", "json": "json", "yaml": "yaml", "toml": "toml",
    "bash": "bash", "javascript": "javascript", "typescript": "typescript",
    "html": "html",
}
_RANK = {"EXACT": 0, "DERIVED": 1, "HINT": 2}


def _errors(line: int, col: int, message: str) -> List[Dict]:
    return [{"line": int(line or 0), "col": int(col or 0), "message": str(message)}]


def _check_python(text: str) -> List[Dict]:
    import ast
    try:
        ast.parse(text)
        return []
    except SyntaxError as e:
        return _errors(e.lineno or 0, e.offset or 0, e.msg or "SyntaxError")


def _check_json(text: str) -> List[Dict]:
    try:
        json.loads(text)
        return []
    except json.JSONDecodeError as e:
        return _errors(e.lineno, e.colno, e.msg)


def _check_toml(text: str) -> List[Dict]:
    import tomllib
    try:
        tomllib.loads(text)
        return []
    except Exception as e:
        return _errors(0, 0, str(e))


def _check_yaml(text: str) -> Optional[List[Dict]]:
    try:
        import yaml
    except ImportError:
        return None
    try:
        yaml.safe_load(text)
        return []
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        line = (mark.line + 1) if mark else 0
        col = (mark.column + 1) if mark else 0
        return _errors(line, col, getattr(e, "problem", None) or str(e))


def _check_xml(text: str) -> List[Dict]:
    import xml.etree.ElementTree as ET
    try:
        ET.fromstring(text)
        return []
    except ET.ParseError as e:
        pos = getattr(e, "position", (0, 0))
        return _errors(pos[0], pos[1], str(e))


def _check_treesitter(text: str, kind: str) -> Optional[List[Dict]]:
    ts_lang = _TS_LANGS.get(kind)
    if not ts_lang:
        return None
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None
    try:
        parser = get_parser(ts_lang)
    except Exception:
        return None
    tree = parser.parse(text.encode("utf-8", errors="replace"))
    errors: List[Dict] = []
    stack = [tree.root_node]
    while stack and len(errors) < 5:
        node = stack.pop()
        if node.type == "ERROR":
            errors.append(_errors(node.start_point[0] + 1, node.start_point[1] + 1,
                                  "синтаксическая ошибка"))
        elif node.is_missing:
            errors.append(_errors(node.start_point[0] + 1, node.start_point[1] + 1,
                                  f'ожидается "{node.type}"'))
        for child in reversed(node.children):
            stack.append(child)
    return errors


def check_syntax(path: Optional[str] = None, text: Optional[str] = None,
                 kind: Optional[str] = None) -> Dict:
    """Проверить синтаксис. Возвращает словарь со `status`.

    status: ok | error | skipped | ambiguous | unsupported.
    """
    head = b""
    if text is None:
        if not path or not os.path.isfile(path):
            return {"status": "error", "kind": kind, "errors": _errors(0, 0, "файл не найден")}
        with open(path, "rb") as f:
            raw = f.read()
        head = raw[:4096]
        if b"\x00" in head:
            return {"status": "skipped", "kind": "binary", "reason": "бинарный файл",
                    "errors": []}
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        head = text.encode("utf-8", errors="replace")[:4096]
        if b"\x00" in head:
            return {"status": "skipped", "kind": "binary", "reason": "бинарный файл",
                    "errors": []}

    candidates: List[Dict] = []
    if not kind:
        candidates = detect_kinds(path or "", head=head)
        if not candidates:
            return {"status": "unsupported", "kind": None, "errors": [],
                    "supported": list(SUPPORTED_KINDS)}
        top = candidates[0]
        ambiguous = any(
            c["kind"] != top["kind"] and _RANK.get(c["confidence"], 9) == _RANK.get(top["confidence"], 9)
            for c in candidates[1:]
        )
        if ambiguous and top["confidence"] != "EXACT":
            return {"status": "ambiguous", "kind": None, "candidates": candidates,
                    "errors": [], "supported": list(SUPPORTED_KINDS)}
        kind = top["kind"]

    kind = normalize_kind(kind)

    if kind == "python":
        errors, checker = _check_python(text), "ast.parse"
    elif kind == "json":
        errors, checker = _check_json(text), "json.loads"
    elif kind == "toml":
        errors, checker = _check_toml(text), "tomllib"
    elif kind == "yaml":
        errors = _check_yaml(text)
        checker = "yaml.safe_load"
        if errors is None:
            errors = _check_treesitter(text, kind)
            checker = "tree-sitter"
    elif kind == "xml":
        errors, checker = _check_xml(text), "ElementTree"
    elif kind in _TS_LANGS:
        errors = _check_treesitter(text, kind)
        checker = "tree-sitter"
        if errors is None:
            return {"status": "unsupported", "kind": kind, "errors": [],
                    "reason": "нет парсера tree-sitter",
                    "supported": list(SUPPORTED_KINDS)}
    else:
        return {"status": "unsupported", "kind": kind, "errors": [],
                "supported": list(SUPPORTED_KINDS)}

    return {
        "status": "ok" if not errors else "error",
        "kind": kind,
        "checker": checker,
        "mode": "inproc",
        "errors": errors,
    }
