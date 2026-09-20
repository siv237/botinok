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

import re
from typing import Iterable

from textual import events
from textual._keyboard_protocol import FUNCTIONAL_KEYS
from textual._xterm_parser import XTermParser
from textual.keys import _character_to_key

_MODIFY_OTHER_KEYS = re.compile(r"\x1b\[27;(\d+);(\d+)~")
_MODIFIERS = ("shift", "alt", "ctrl", "super", "hyper", "meta")


class BotinokXTermParser(XTermParser):
    """XTermParser: Alt+Enter как отдельная клавиша + xterm modifyOtherKeys."""

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


def install() -> None:
    """Поставить парсер клавиш в Linux-драйверы Textual до запуска приложения."""
    try:
        import textual.drivers.linux_driver as _linux_driver

        _linux_driver.XTermParser = BotinokXTermParser
    except Exception:
        pass
    try:
        import textual.drivers.linux_inline_driver as _linux_inline

        _linux_inline.XTermParser = BotinokXTermParser
    except Exception:
        pass
