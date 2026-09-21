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
import tempfile
from collections import OrderedDict
from typing import Optional

# У части фото (профессиональные/CMYK, напр. Canon) ICC-профиль настолько
# большой, что PIL отказывается открывать PNG с таким iCCP-чанком:
#   ValueError: Decompressed data too large for PngImagePlugin.MAX_TEXT_CHUNK
# PNG-кэш уменьшенных копий пишется нами же, поэтому поднимаем лимит (и не
# тащим профиль в кэш — см. prepare_scaled). Иначе полосовой рендер падает,
# и картинка не показывается.
try:  # pragma: no cover - зависит от версии Pillow
    from PIL import PngImagePlugin
    if PngImagePlugin.MAX_TEXT_CHUNK is not None:
        PngImagePlugin.MAX_TEXT_CHUNK = max(PngImagePlugin.MAX_TEXT_CHUNK,
                                            128 * 1024 * 1024)
except Exception:
    pass

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
    _BAND_CACHE.clear()


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


_CHAFA_CAPS: Optional[set] = None


def chafa_caps() -> set:
    """Кэшированный набор поддерживаемых chafa-флагов (по `chafa --help`).

    Нужен из-за разницы версий: Ubuntu 22.04 даёт chafa 1.8.0, где нет
    `--animate` — с ним команда падает (rc=1) и картинки не рендерятся.
    """
    global _CHAFA_CAPS
    if _CHAFA_CAPS is None:
        caps: set = set()
        chafa = chafa_path()
        if chafa:
            try:
                proc = subprocess.run([chafa, "--help"], capture_output=True,
                                      text=True, timeout=5)
                caps = set(re.findall(r"--([A-Za-z0-9-]+)",
                                      (proc.stdout or "") + (proc.stderr or "")))
            except Exception:
                caps = set()
        _CHAFA_CAPS = caps
    return _CHAFA_CAPS


def _chafa_base_args(symbols: str) -> list:
    """Общие аргументы chafa, совместимые с установленной версией."""
    args = ["--format", "symbols", "--symbols", symbols, "--colors", "full"]
    if "animate" in chafa_caps():
        args += ["--animate", "off"]  # в старых chafa (1.8) флага нет
    return args


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
            [chafa] + _chafa_base_args(symbols) + ["--size", size, path],
            capture_output=True, timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.decode("utf-8", "ignore")
    # chafa прячет/показывает курсор — это нам не нужно в Static.
    return re.sub(r"\x1b\[\?25[lh]", "", text)


# --- Полосовой рендер: рисуем только видимый кусок картинки -----------------
# Смысл: для огромного изображения (например 4000x2250 или очень высокого)
# нет смысла рендерить всё целиком — терминал показывает лишь несколько
# десятков строк. Режем источник на полосы по пикселям, кэшируем их и отдаём
# chafa только нужную полосу. Стоимость не зависит от размера картинки.
_BAND_CACHE: "OrderedDict[tuple, str]" = OrderedDict()
_BAND_CACHE_MAX = 128
_BAND_DIR = os.path.join(tempfile.gettempdir(), "botinok-bands")


def _band_key(path: str, y0: int, y1: int) -> tuple:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    return (os.path.abspath(path), mtime, int(y0), int(y1))


def _crop_source(path: str, y0: int, y1: int) -> Optional[str]:
    """Вырезать полосу источника в отдельный файл (кэшируется на диске)."""
    os.makedirs(_BAND_DIR, exist_ok=True)
    import hashlib
    key = _band_key(path, y0, y1)
    digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16]
    out = os.path.join(_BAND_DIR, f"{digest}.png")
    if os.path.isfile(out):
        return out
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGBA")
            w, h = im.size
            y0c = max(0, min(h - 1, int(y0)))
            y1c = max(y0c + 1, min(h, int(y1)))
            band = im.crop((0, y0c, w, y1c))
        try:
            band.info.pop("icc_profile", None)
            band.info.pop("exif", None)
        except Exception:
            pass
        band.save(out, "PNG")
        return out
    except Exception:
        return None


_SCALE_DIR = os.path.join(tempfile.gettempdir(), "botinok-scale")
# Ограничение только сверху и щедрое: режем по ширине (сколько клеток),
# высоту не «съедаем» — иначе высокие картинки теряли разрешение.
_SCALE_MAX_PIXELS = int(os.environ.get("BOTINOK_IMAGE_TERM_PIXELS", str(24_000_000)))


def _prune_dir(directory: str, limit: int = 400) -> None:
    try:
        files = [os.path.join(directory, f) for f in os.listdir(directory)]
        if len(files) <= limit:
            return
        files.sort(key=os.path.getmtime)
        for f in files[:len(files) - limit]:
            try:
                os.remove(f)
            except OSError:
                pass
    except Exception:
        pass


def prepare_scaled(path: str, width: int, rows: int,
                   max_pixels: int = 0):
    """Уменьшенная копия источника ровно под текущий размер терминала.

    Возвращает `(путь, ширина_px, высота_px)` или None. Кэшируется на диске по
    (файл, mtime, ширина, высота) — пока размер терминала не изменился, картинка
    не пересчитывается. Декодирование JPEG ускоряется через `Image.draft`.
    """
    if not path or width <= 0 or rows <= 0 or not os.path.isfile(path):
        return None
    # chafa качественнее работает, если скормить копию с увеличенным (×2 к
    # минимально необходимому) разрешением — тогда ей есть из чего усреднять.
    over = float(os.environ.get("BOTINOK_IMAGE_OVERSAMPLE", "2"))
    target_w = max(1, int(width * 2 * over))
    target_h = max(1, int(rows * 2 * over))
    cap = max_pixels or _SCALE_MAX_PIXELS
    if cap and target_w * target_h > cap:
        scale = (cap / float(target_w * target_h)) ** 0.5
        target_w = max(1, int(target_w * scale))
        target_h = max(1, int(target_h * scale))
    key = _band_key(path, 0, 0)[:2] + (target_w, target_h)
    import hashlib
    digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16]
    os.makedirs(_SCALE_DIR, exist_ok=True)
    out = os.path.join(_SCALE_DIR, f"{digest}.png")
    if os.path.isfile(out):
        return out, target_w, target_h
    try:
        from PIL import Image
        with Image.open(path) as im:
            try:
                im.draft("RGB", (target_w, target_h))  # быстрый DCT-скейл для JPEG
            except Exception:
                pass
            im = im.convert("RGB")
            if im.size != (target_w, target_h):
                resample = getattr(Image, "Resampling", Image).BILINEAR
                im = im.resize((target_w, target_h), resample)
            # Не тащим тяжёлый ICC/EXIF в PNG-кэш: иначе PIL не может переоткрыть
            # файл (MAX_TEXT_CHUNK) и полосовой рендер ломается на CMYK-фото.
            try:
                im.info.pop("icc_profile", None)
                im.info.pop("exif", None)
            except Exception:
                pass
        im.save(out, "PNG")
    except Exception:
        return None
    _prune_dir(_SCALE_DIR, limit=120)
    return out, target_w, target_h


def _prune_band_dir(limit: int = 400) -> None:
    try:
        files = [os.path.join(_BAND_DIR, f) for f in os.listdir(_BAND_DIR)]
        if len(files) <= limit:
            return
        files.sort(key=os.path.getmtime)
        for f in files[:len(files) - limit]:
            try:
                os.remove(f)
            except OSError:
                pass
    except Exception:
        pass


def render_image_band(path: str, width: int, rows: int, y0: int, y1: int,
                      symbols: Optional[str] = None,
                      timeout: float = 15.0) -> Optional[str]:
    """ANSI ровно для полосы источника [y0, y1) пикселей, высотой `rows` строк.

    Возвращает готовый кусок картинки без перерисовки всего изображения.
    """
    if not path or width <= 0 or rows <= 0 or not os.path.isfile(path):
        return None
    key = _band_key(path, y0, y1) + (int(width), int(rows),
                                     symbols or os.environ.get("BOTINOK_LOGO_SYMBOLS", DEFAULT_SYMBOLS))
    cached = _BAND_CACHE.get(key)
    if cached is not None:
        _BAND_CACHE.move_to_end(key)
        return cached

    band_file = _crop_source(path, y0, y1)
    if not band_file:
        return None
    chafa = chafa_path()
    if not chafa:
        return None
    sym = symbols or os.environ.get("BOTINOK_LOGO_SYMBOLS", DEFAULT_SYMBOLS)
    try:
        proc = subprocess.run(
            [chafa] + _chafa_base_args(sym) + [
                "--size", f"{int(width)}x{int(rows)}", "--stretch", band_file],
            capture_output=True, timeout=timeout,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = re.sub(r"\x1b\[\?25[lh]", "", proc.stdout.decode("utf-8", "ignore")).rstrip("\n")
    _BAND_CACHE[key] = text
    _BAND_CACHE.move_to_end(key)
    while len(_BAND_CACHE) > _BAND_CACHE_MAX:
        _BAND_CACHE.popitem(last=False)
    _prune_band_dir()
    return text


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
