"""Рендер изображений в терминал для TUI (основа показа картинок в чате).

Механика: изображение превращается в ANSI-текст, который можно вставить в
`Static`. Основной путь — `chafa` (символы-секстанты 2x3 на ячейку, truecolor),
фолбэк — встроенный рендер из `core/image_ascii`.

Модуль намеренно без зависимости от Textual: его легко тестировать и
переиспользовать для превью скачанных/сгенерированных картинок.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections import OrderedDict
from typing import Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

DEFAULT_SYMBOLS = "sextant"
DEFAULT_MAX_HEIGHT = 200

# Кэш отрендеренного ANSI: (путь, mtime, ширина, символы) -> текст.
# Нужен для реактивности: при ресайзе/перерисовке одна и та же картинка
# на той же ширине отдаётся мгновенно, без запуска chafa.
_CACHE: "OrderedDict[tuple, str]" = OrderedDict()
_CACHE_MAX = 12
# Ограничение по суммарной памяти: одна широко отрендеренная картинка может
# весить мегабайты, поэтому держим не «сколько влезет», а бюджет.
_CACHE_MAX_BYTES = 32 * 1024 * 1024
_CACHE_BYTES = 0

# Кэш уже РАЗОБРАННОГО rich.Text. Разбор ANSI (Text.from_ansi) стоит сотни
# миллисекунд на широких картинках, поэтому делаем его один раз и в фоне,
# а не на UI-потоке при каждом ресайзе.
_TEXT_CACHE: "OrderedDict[tuple, object]" = OrderedDict()
_TEXT_CACHE_MAX = 16


def clear_cache() -> None:
    global _CACHE_BYTES
    _CACHE.clear()
    _CACHE_BYTES = 0
    _TEXT_CACHE.clear()


def _cache_key(path: str, width: int, symbols: Optional[str],
               max_height: int = 0) -> tuple:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    return (os.path.abspath(path), mtime, int(width), int(max_height),
            symbols or os.environ.get("BOTINOK_LOGO_SYMBOLS", DEFAULT_SYMBOLS))


def _cache_get(key: tuple) -> Optional[str]:
    value = _CACHE.get(key)
    if value is not None:
        _CACHE.move_to_end(key)
    return value


def _cache_put(key: tuple, value: str) -> None:
    global _CACHE_BYTES
    old = _CACHE.get(key)
    if old is not None:
        _CACHE_BYTES -= len(old)
    _CACHE[key] = value
    _CACHE_BYTES += len(value)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX or (_CACHE_BYTES > _CACHE_MAX_BYTES and len(_CACHE) > 1):
        _, dropped = _CACHE.popitem(last=False)
        _CACHE_BYTES -= len(dropped)


def strip_ansi(text: str) -> str:
    """Убрать ANSI-последовательности (для измерения/тестов)."""
    return _ANSI_RE.sub("", text)


def visible_width(ansi_text: str) -> int:
    """Максимальная ширина строки в ячейках (без ANSI)."""
    plain = strip_ansi(ansi_text)
    return max((len(line) for line in plain.split("\n")), default=0)


def visible_height(ansi_text: str) -> int:
    return len(strip_ansi(ansi_text).split("\n")) if ansi_text else 0


def chafa_path() -> Optional[str]:
    return shutil.which("chafa")


def render_with_chafa(path: str, width: int,
                      symbols: Optional[str] = None,
                      timeout: float = 15.0,
                      max_height: int = 0) -> Optional[str]:
    """Рендер через chafa. None, если chafa нет/ошибка.

    max_height > 0 ограничивает высоту в строках: важно, чтобы картинка на
    широком окне не превращалась в сотни строк (это дорого и в разборе, и в
    раскладке Textual).
    """
    chafa = chafa_path()
    if not chafa or width <= 0:
        return None
    symbols = symbols or os.environ.get("BOTINOK_LOGO_SYMBOLS", DEFAULT_SYMBOLS)
    size = f"{int(width)}x" if max_height <= 0 else f"{int(width)}x{int(max_height)}"
    try:
        proc = subprocess.run(
            [chafa, "--format", "symbols", "--symbols", symbols,
             "--colors", "full", "--animate", "off", "--size", size,
             path],
            capture_output=True, timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", "ignore")
    # chafa прячет/показывает курсор — это нам не нужно в Static.
    return re.sub(r"\x1b\[\?25[lh]", "", text)


def render_with_pillow(path: str, width: int) -> Optional[str]:
    """Встроенный полноцветный рендер (фолбэк). None при ошибке."""
    if width <= 0:
        return None
    try:
        from core.image_ascii import image_to_fullcolor
        text, _ = image_to_fullcolor(path, max(8, width // 2))
        return text
    except Exception:
        return None


def render_image_ansi(path: str, width: int, prefer_chafa: bool = True,
                      symbols: Optional[str] = None,
                      max_height: int = 0) -> Optional[str]:
    """ANSI-представление изображения на заданную ширину (в ячейках).

    По умолчанию (max_height=0) картинка занимает всю ширину, высота — по
    пропорциям, без ограничения (в UI она просто скроллится). Результат
    кэшируется; None, если файла нет/не картинка или ширина некорректна.
    """
    if not path or width <= 0 or not os.path.isfile(path):
        return None
    key = _cache_key(path, width, symbols, max_height)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    rendered = None
    if prefer_chafa:
        rendered = render_with_chafa(path, width, symbols=symbols,
                                     max_height=max_height)
    if not rendered:
        rendered = render_with_pillow(path, width)
    if rendered:
        _cache_put(key, rendered)
    return rendered


def render_image_text(path: str, width: int, prefer_chafa: bool = True,
                      symbols: Optional[str] = None, max_height: int = 0):
    """Готовый rich.Text для вставки в виджет — разбор ANSI кэшируется.

    Тяжёлую часть (chafa + Text.from_ansi) можно безопасно вызывать из фонового
    потока; на UI-потоке остаётся только `static.update(text)`.
    """
    ansi = render_image_ansi(path, width, prefer_chafa=prefer_chafa,
                             symbols=symbols, max_height=max_height)
    if not ansi:
        return None
    key = _cache_key(path, width, symbols, max_height)
    cached = _TEXT_CACHE.get(key)
    if cached is not None:
        _TEXT_CACHE.move_to_end(key)
        return cached
    try:
        from rich.text import Text
        text = Text.from_ansi(ansi)
    except Exception:
        return None
    _TEXT_CACHE[key] = text
    _TEXT_CACHE.move_to_end(key)
    while len(_TEXT_CACHE) > _TEXT_CACHE_MAX:
        _TEXT_CACHE.popitem(last=False)
    return text
