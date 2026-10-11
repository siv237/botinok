"""
Простые Textual-диалоги для CLI: замена inquirer / rich.prompt / readchar.

Мастер настройки и выбор сессии раньше использовали inquirer и readchar.
Теперь весь интерактив — Textual; эти диалоги запускаются до основного
приложения (или внутри wizard) и возвращают результат через `App.run()`.

Возврат `None` означает отмену (Esc / закрытие).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from core import themes as botinok_themes


class _SelectApp(botinok_themes.ThemedAppMixin, App):
    """Модальный выбор одного варианта из списка (замена inquirer.List)."""

    CSS = """
    _SelectApp { align: center middle; }
    #q_message { width: 90%; padding: 1 2; color: $text; }
    #q_options { width: 90%; height: auto; max-height: 70%; border: solid $hl; }
    #theme_btn { dock: top; }
    """ + botinok_themes.THEME_BTN_CSS

    def __init__(self, message: str, choices: Sequence[Tuple[str, object]],
                 default: object = None, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.choices = list(choices)
        self.default = default
        self.result: Optional[object] = None

    def compose(self) -> ComposeResult:
        yield self.make_theme_btn()
        with Vertical():
            yield Static(self.message, id="q_message")
            yield OptionList(id="q_options")

    def on_mount(self) -> None:
        options = self.query_one("#q_options", OptionList)
        for i, (label, _value) in enumerate(self.choices):
            options.add_option(Option(str(label), id=str(i)))
        index = 0
        for i, (_label, value) in enumerate(self.choices):
            if value == self.default:
                index = i
                break
        if options.option_count:
            options.highlighted = index
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            self.result = self.choices[int(event.option.id)][1]
        except Exception:
            self.result = None
        self.exit(self.result)

    def on_key(self, event) -> None:
        if getattr(event, "key", "") == "escape":
            event.stop()
            self.result = None
            self.exit(None)


class _ClimbingOptionList(OptionList):
    """Список, передающий фокус соседу на границе: вниз за последний
    пункт — в нижний список, вверх за первый — в верхний."""

    climb_down = None
    climb_up = None

    def action_cursor_down(self) -> None:
        if self.climb_down and self.option_count and \
                self.highlighted == self.option_count - 1:
            self.climb_down()
        else:
            super().action_cursor_down()

    def action_cursor_up(self) -> None:
        if self.climb_up and (self.highlighted is None or self.highlighted == 0):
            self.climb_up()
        else:
            super().action_cursor_up()


class _GroupedSelectApp(botinok_themes.ThemedAppMixin, App):
    """Два блока выбора в одном окне; курсор переходит стрелками."""

    CSS = """
    _GroupedSelectApp { align: center middle; }
    #g_message { width: 90%; padding: 1 2; color: $text; }
    #g_primary { width: 90%; height: auto; max-height: 40%; border: solid $hl; }
    #g_secondary_title { width: 90%; padding: 1 2 0 2; color: $text; }
    #g_secondary { width: 90%; height: auto; max-height: 40%; border: round $hl; }
    #theme_btn { dock: top; }
    """ + botinok_themes.THEME_BTN_CSS

    def __init__(self, message, primary, secondary_title, secondary,
                 default=None, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.primary = list(primary)
        self.secondary_title = secondary_title
        self.secondary = list(secondary)
        self.default = default
        self.result: Optional[object] = None

    def compose(self) -> ComposeResult:
        yield self.make_theme_btn()
        with Vertical():
            yield Static(self.message, id="g_message")
            yield _ClimbingOptionList(id="g_primary")
            yield Static(self.secondary_title, id="g_secondary_title")
            yield _ClimbingOptionList(id="g_secondary")

    def on_mount(self) -> None:
        pl = self.query_one("#g_primary", _ClimbingOptionList)
        sl = self.query_one("#g_secondary", _ClimbingOptionList)
        for i, (label, _v) in enumerate(self.primary):
            pl.add_option(Option(str(label), id=str(i)))
        for i, (label, _v) in enumerate(self.secondary):
            sl.add_option(Option(str(label), id=str(i)))
        index = 0
        for i, (_l, value) in enumerate(self.primary):
            if value == self.default:
                index = i
                break
        if pl.option_count:
            pl.highlighted = index
        pl.climb_down = lambda: (sl.focus(),
                                 setattr(sl, "highlighted", 0 if sl.option_count else None))
        sl.climb_up = lambda: (pl.focus(),
                               setattr(pl, "highlighted", pl.option_count - 1))
        pl.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        choices = self.primary if event.option_list.id == "g_primary" else self.secondary
        try:
            self.result = choices[int(event.option.id)][1]
        except Exception:
            self.result = None
        self.exit(self.result)

    def on_key(self, event) -> None:
        if getattr(event, "key", "") == "escape":
            event.stop()
            self.result = None
            self.exit(None)


def textual_select_grouped(message, primary, secondary_title, secondary,
                           default=None):
    """Два блока выбора в одном окне. Значение из любого блока, None — отмена."""
    return _GroupedSelectApp(message, primary, secondary_title, secondary,
                             default).run()


class _TextApp(botinok_themes.ThemedAppMixin, App):
    """Ввод строки (замена rich.prompt.Prompt)."""

    CSS = """
    _TextApp { align: center middle; }
    #t_message { width: 90%; padding: 1 2; }
    #t_input { width: 90%; }
    #theme_btn { dock: top; }
    """ + botinok_themes.THEME_BTN_CSS

    def __init__(self, message: str, default: str = "",
                 password: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.default = default
        self.password = password
        self.result: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield self.make_theme_btn()
        with Vertical():
            yield Static(self.message, id="t_message")
            yield Input(value=self.default, password=self.password, id="t_input")

    def on_mount(self) -> None:
        self.query_one("#t_input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.result = event.value
        self.exit(event.value)

    def on_key(self, event) -> None:
        if getattr(event, "key", "") == "escape":
            event.stop()
            self.result = None
            self.exit(None)


def textual_select(message: str, choices: Sequence[Tuple[str, object]],
                   default: object = None) -> Optional[object]:
    """Выбор варианта. Возвращает значение или None при отмене."""
    return _SelectApp(message, choices, default).run()


def textual_prompt(message: str, default: str = "",
                   password: bool = False) -> Optional[str]:
    """Ввод строки. Возвращает строку или None при отмене."""
    return _TextApp(message, default, password=password).run()


def textual_confirm(message: str, default: bool = True) -> Optional[bool]:
    """Да/Нет. Возвращает bool или None при отмене."""
    choices = [("Да", True), ("Нет", False)]
    result = textual_select(message, choices, default)
    if result is None:
        return None
    return bool(result)
