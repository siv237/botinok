#!/usr/bin/env python3
"""Реестр типов файлов: определение языка/типа с оценкой уверенности.

Каскад: magic-байты и shebang (EXACT) → расширение через `mimetypes`/Pygments
(DERIVED) → сниффер по содержимому (HINT). Используется `code_editor`
(автопроверка синтаксиса) и `core/syntax_check.py`.

Возвращается СПИСОК кандидатов, а не один тип: при неоднозначности вызывающая
сторона сообщает варианты и предлагает выбрать через `kind=`.
"""

import os
from typing import Dict, List, Optional

CONFIDENCE_RANK = {"EXACT": 0, "DERIVED": 1, "HINT": 2}

EXT_KINDS: Dict[str, str] = {
    "py": "python", "pyi": "python", "pyw": "python",
    "json": "json", "jsonl": "json", "ndjson": "json",
    "yaml": "yaml", "yml": "yaml",
    "toml": "toml",
    "xml": "xml", "svg": "xml",
    "html": "html", "htm": "html",
    "sh": "bash", "bash": "bash", "zsh": "bash", "ksh": "bash",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "md": "markdown", "txt": "text",
    "log": "text", "ini": "text", "cfg": "text", "conf": "text",
}

# Pygments lexer name (lowercase) → kind
LEXER_KINDS: Dict[str, str] = {
    "python": "python", "json": "json", "yaml": "yaml", "toml": "toml",
    "xml": "xml", "html": "html", "bash": "bash", "shell": "bash",
    "javascript": "javascript", "typescript": "typescript",
    "markdown": "markdown", "text only": "text",
}

_MAGIC = (
    (b"\x7fELF", "binary"),
    (b"MZ", "binary"),
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF8", "image"),
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"),
    (b"\x1f\x8b", "gzip"),
    (b"GGUF", "gguf"),
    (b"RIFF", "binary"),
    (b"OggS", "binary"),
    (b"fLaC", "binary"),
    (b"\x1a\x45\xdf\xa3", "binary"),
)


def _rank(conf: str) -> int:
    return CONFIDENCE_RANK.get(conf, 9)


def _add(cands: List[Dict], kind: str, conf: str, why: str) -> None:
    if not kind:
        return
    for c in cands:
        if c["kind"] == kind:
            if _rank(conf) < _rank(c["confidence"]):
                c["confidence"] = conf
                c["why"] = why
            return
    cands.append({"kind": kind, "confidence": conf, "why": why})


def _from_shebang(text: str) -> Optional[tuple]:
    if not text.startswith("#!"):
        return None
    first = text.splitlines()[0].lower()
    if "python" in first:
        return "python", first.strip()
    if any(x in first for x in ("bash", "/sh", "zsh", "ksh")):
        return "bash", first.strip()
    if "node" in first:
        return "javascript", first.strip()
    return None


def _sniff(text: str) -> Optional[tuple]:
    stripped = text.lstrip()
    low = stripped.lower()
    if low.startswith("<?xml"):
        return "xml", "начинается с <?xml"
    if low.startswith("<!doctype html") or low.startswith("<html"):
        return "html", "HTML-документ"
    if stripped[:1] in ("{", "["):
        return "json", "начинается с { или ["
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if lines and lines[0].strip() == "---":
        return "yaml", "YAML front-matter (---)"
    if any(ln.lstrip().startswith(("def ", "import ", "from ", "class ")) for ln in lines[:40]):
        return "python", "ключевые слова Python в начале строк"
    if any(ln.lstrip().startswith(("function ", "const ", "let ", "var ", "export ")) for ln in lines[:40]):
        return "javascript", "ключевые слова JavaScript"
    if any(":" in ln and not ln.lstrip().startswith(("{", "[", "<")) for ln in lines[:20]) \
            and sum(":" in ln for ln in lines[:20]) >= 2:
        return "yaml", "пары ключ: значение"
    if stripped.startswith("[") and "]" in stripped.splitlines()[0] and "=" in text:
        return "toml", "секция [name] и ключи = значение"
    return None


def _from_pygments(path: str, text: str) -> Optional[str]:
    try:
        from pygments.lexers import get_lexer_for_filename
        try:
            lexer = get_lexer_for_filename(os.path.basename(path), text)
        except Exception:
            return None
        return LEXER_KINDS.get(lexer.name.lower())
    except Exception:
        return None


def detect_kinds(path: str, head: Optional[bytes] = None) -> List[Dict]:
    """Возвращает кандидатов типа файла, отсортированных по уверенности."""
    cands: List[Dict] = []
    if head is None:
        try:
            with open(path, "rb") as f:
                head = f.read(4096)
        except Exception:
            head = b""

    for magic, kind in _MAGIC:
        if head.startswith(magic):
            _add(cands, kind, "EXACT", "magic-байты")
            return sorted(cands, key=lambda c: _rank(c["confidence"]))

    if b"\x00" in head:
        _add(cands, "binary", "EXACT", "NUL-байт")
        return cands

    try:
        text = head.decode("utf-8", errors="replace")
    except Exception:
        text = ""

    sb = _from_shebang(text)
    if sb:
        _add(cands, sb[0], "EXACT", f"shebang: {sb[1]}")

    base = os.path.basename(path)
    ext = base.rsplit(".", 1)[1].lower() if "." in base else ""
    if ext in EXT_KINDS:
        _add(cands, EXT_KINDS[ext], "DERIVED", f"расширение .{ext}")
    else:
        pg = _from_pygments(path, text)
        if pg:
            _add(cands, pg, "DERIVED", "Pygments по имени")

    sniff = _sniff(text)
    if sniff:
        _add(cands, sniff[0], "HINT", sniff[1])

    if not cands:
        _add(cands, "text", "HINT", "по умолчанию текст")
    return sorted(cands, key=lambda c: _rank(c["confidence"]))


def primary_kind(cands: List[Dict]) -> Optional[str]:
    return cands[0]["kind"] if cands else None


def normalize_kind(kind: Optional[str]) -> Optional[str]:
    if not kind:
        return kind
    k = str(kind).strip().lower()
    aliases = {
        "py": "python", "python3": "python",
        "yml": "yaml", "js": "javascript", "jsx": "javascript",
        "ts": "typescript", "tsx": "typescript",
        "sh": "bash", "shell": "bash", "zsh": "bash",
        "htm": "html",
    }
    return aliases.get(k, k)
