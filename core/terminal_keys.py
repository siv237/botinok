"""Различение Alt+Enter в обычных терминалах.

xterm-совместимые терминалы (в т.ч. VTE: xfce4-terminal, GNOME Terminal) шлют
Alt+Enter как ESC + CR/LF. Textual для известных последовательностей теряет
модификатор alt и отдаёт обычный enter, поэтому Alt+Enter отправлял сообщение
вместо переноса строки.

`BotinokXTermParser` превращает ESC+CR/LF в `alt+enter`. Заодно понимает форму
xterm ``CSI 27;<mod>;<code>~`` (на случай, если терминал или пользователь
включает modifyOtherKeys). `install` ставит парсер в Linux-драйверы Textual —
иного API расширения клавиш у Textual 8.x нет.
"""

from __future__ import annotations

import os
import re
import time
from typing import Iterable

from textual import events
from textual._keyboard_protocol import FUNCTIONAL_KEYS
from textual._xterm_parser import XTermParser
from textual.keys import _character_to_key

_MODIFY_OTHER_KEYS = re.compile(r"\x1b\[27;(\d+);(\d+)~")
_MODIFIERS = ("shift", "alt", "ctrl", "super", "hyper", "meta")

# Ответы терминала на запросы (цвет фона/переднего плана OSC 10/11, DA1/DA2,
# размер окна/пикселей CSI ..t, XTVERSION). Textual 8.x их не распознаёт:
# последовательность не совпадает ни с чем, превышает порог поиска и каждый
# символ «переиздаётся» клавишей — при открытии в поле ввода появлялся мусор
# вида `^]10;rgb:...^\^]11;...^[8;24;80t^[4;456;720t[?61;...c`. Вырезаем их
# из потока ввода ДО парсера. DECRPM (`?..$y`) и позицию курсора (`..R`) не
# трогаем — их парсер обрабатывает сам.
_RE_TERM_RESPONSE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL/ST (цвета и т.п.)
    r"|\x1b\[\??[0-9;]*c"                 # DA1/DA2 response
    r"|\x1b\[\??[0-9;]*t"                 # window/pixel/cell size report
    r"|\x1b>P[^\x1b]*\x1b\\",             # XTVERSION (DCS)
)
# Хвост, похожий на НАЧАЛО ответа, пришедший обрывком — придержим до feed-а
# позже (обычно остаток приходит этим же пакетом).
_RE_HELD_TAIL = re.compile(r"(?:\x1b\][^\x07\x1b]*|\x1b\[\??[0-9;]*)$")


class BotinokXTermParser(XTermParser):
    """XTermParser: Alt+Enter как отдельная клавиша + xterm modifyOtherKeys."""

    RESPONSE_HOLD = 1.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._held = ""
        self._held_at = 0.0

    def feed(self, data: str):
        incoming = bool(data)
        if self._held:
            if time.time() - self._held_at > self.RESPONSE_HOLD:
                # Просрочка: ответ так и не дошёл — выбрасываем, в клавиши
                # не отдаём (пользователь CSI-префиксы с цифрами не печатает).
                self.debug_log("DROP held", repr(self._held))
            else:
                data = self._held + data
            self._held = ""
        data = _RE_TERM_RESPONSE.sub("", data)
        tail = _RE_HELD_TAIL.search(data)
        if tail is not None:
            self._held = data[tail.start():]
            self._held_at = time.time()
            data = data[:tail.start()]
        if not data and incoming:
            # Весь пакет — ответы терминала: super().feed("") означало бы EOF
            # и закрыло бы парсер посреди сессии.
            return []
        return super().feed(data)

    def tick(self):
        if self._held and time.time() - self._held_at > self.RESPONSE_HOLD:
            self.debug_log("DROP held (tick)", repr(self._held))
            self._held = ""
        return super().tick()

    def _sequence_to_key_events(
        self, sequence: str, alt: bool = False
    ) -> Iterable[events.Key]:
        # Alt+Enter в обычных терминалах: ESC + CR/LF.
        if alt and sequence in ("\r", "\n"):
            yield events.Key("alt+enter", None)
            return
        # xterm modifyOtherKeys: ESC [ 27 ; <mod> ; <code> ~.
        match = _MODIFY_OTHER_KEYS.fullmatch(sequence)
        if match is not None:
            modifier_bits = int(match.group(1)) - 1
            code = int(match.group(2))
            key = FUNCTIONAL_KEYS.get(f"{code}u", "")
            if not key:
                try:
                    key = _character_to_key(chr(code))
                except Exception:
                    key = chr(code)
            tokens = [
                modifier
                for bit, modifier in enumerate(_MODIFIERS)
                if modifier_bits & (1 << bit)
            ]
            tokens.sort()
            tokens.append(key.lower())
            yield events.Key("+".join(tokens), None)
            return
        yield from super()._sequence_to_key_events(sequence, alt)


_DEBUG_LOG = "/tmp/botinok_input.log"


class _DebugLoggingParser(BotinokXTermParser):
    """То же, но пишет сырой ввод терминала в файл (для диагностики)."""

    def feed(self, data: str):
        try:
            if data:
                with open(_DEBUG_LOG, "a") as f:
                    f.write(repr(data) + "\n")
        except Exception:
            pass
        return super().feed(data)


def install() -> None:
    """Поставить парсер клавиш в Linux-драйверы Textual до запуска приложения."""
    parser_cls = _DebugLoggingParser if os.environ.get("BOTINOK_DEBUG") else BotinokXTermParser
    try:
        import textual.drivers.linux_driver as _linux_driver

        _linux_driver.XTermParser = parser_cls
    except Exception:
        pass
    try:
        import textual.drivers.linux_inline_driver as _linux_inline

        _linux_inline.XTermParser = parser_cls
    except Exception:
        pass
