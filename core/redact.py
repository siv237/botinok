#!/usr/bin/env python3
"""Маскирование секретов при записи в аудит-логи.

Агент присылает инструментам заголовки вида ``Authorization: Bearer hf_…``
(токены HuggingFace, OpenAI, cookie). Эти аргументы попадают в ``tools.log``
сессии дословно, а оттуда — в контекст через ``session_memory``. Логи должны
быть пригодны для разбора, но не хранить чужие секреты в открытом виде.

Маскируется только **копия для лога**: сам вызов инструмента получает
исходные значения.
"""

import re

MASK = "«скрыто»"

# Ключи, значение которых всегда маскируем (dict-аргументы).
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[-_]?key|apikey|access[-_]?token|refresh[-_]?token|token|secret|"
    r"password|passwd|authorization|cookie|credential|private[-_]?key|session[-_]?key)")

# Строки-значения: «Bearer XXX», «token=XXX», «api_key: XXX», «Cookie: …».
_INLINE_RE = re.compile(
    r"(?i)\b(bearer|token|api[-_]?key|apikey|secret|password|passwd)\b"
    r"(\s*[:=]\s*|\s+)([^\s,;\"']{6,})")
# Известные форматы токенов (в т.ч. внутри URL и заголовков).
_TOKEN_RES = (
    re.compile(r"\bhf_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
)


def redact_text(text: str) -> str:
    """Замаскировать секреты в строке (заголовки, токены в URL и т.п.)."""
    if not text:
        return text
    out = _INLINE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    for pattern in _TOKEN_RES:
        out = pattern.sub(MASK, out)
    return out


def redact(value):
    """Рекурсивно замаскировать секреты в аргументах инструмента."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                result[key] = MASK if item else item
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
