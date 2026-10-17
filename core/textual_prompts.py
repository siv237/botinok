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
    """Модальный выбор одного варианта из списка (замена inquirer.List).

    filterable=True добавляет над списком поле быстрого фильтра: ввод
    сужает список, «вниз» переводит фокус в список, Enter выбирает."""

    CSS = """
    _SelectApp { align: center middle; }
    #q_message { width: 90%; padding: 1 2; color: $text; }
    #q_filter { width: 90%; }
    #q_options { width: 90%; height: auto; max-height: 70%; border: solid $hl; }
    #theme_btn { dock: top; }
    """ + botinok_themes.THEME_BTN_CSS

    def __init__(self, message: str, choices: Sequence[Tuple[str, object]],
                 default: object = None, filterable: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.choices = list(choices)
        self.default = default
        self.filterable = filterable
        self.result: Optional[object] = None
        self._visible: List[int] = []

    def compose(self) -> ComposeResult:
        yield self.make_theme_btn()
        with Vertical():
            yield Static(self.message, id="q_message")
            if self.filterable:
                yield Input(placeholder="Фильтр (начните печатать)…", id="q_filter")
            yield _ClimbingOptionList(id="q_options")

    def _fill(self, options, indices) -> None:
        options.clear_options()
        self._visible = list(indices)
        for i in self._visible:
            options.add_option(Option(str(self.choices[i][0]), id=str(i)))
        highlight = 0
        for pos, i in enumerate(self._visible):
            if self.choices[i][1] == self.default:
                highlight = pos
                break
        if options.option_count:
            options.highlighted = highlight

    def _matches(self, query) -> List[int]:
        q = (query or "").strip().lower()
        if not q:
            return list(range(len(self.choices)))
        return [i for i, (label, _v) in enumerate(self.choices)
                if q in str(label).lower()]

    def on_mount(self) -> None:
        options = self.query_one("#q_options", _ClimbingOptionList)
        self._fill(options, range(len(self.choices)))
        options.focus()
        if self.filterable:
            flt = self.query_one("#q_filter", Input)
            flt.focus()
            options.climb_up = flt.focus

    def on_input_changed(self, event: Input.Changed) -> None:
        self._fill(self.query_one("#q_options", _ClimbingOptionList),
                   self._matches(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        options = self.query_one("#q_options", _ClimbingOptionList)
        if self._visible and options.highlighted is not None:
            self.result = self.choices[self._visible[options.highlighted]][1]
            self.exit(self.result)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            self.result = self.choices[int(event.option.id)][1]
        except Exception:
            self.result = None
        self.exit(self.result)

    def on_key(self, event) -> None:
        key = getattr(event, "key", "")
        if key == "escape":
            event.stop()
            self.result = None
            self.exit(None)
        elif key == "down" and self.filterable and isinstance(self.focused, Input):
            options = self.query_one("#q_options", _ClimbingOptionList)
            if options.option_count:
                event.stop()
                options.focus()
                if options.highlighted is None:
                    options.highlighted = 0


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
    """Ввод строки (замена rich.prompt.Prompt).

    Можно добавить кнопки под полем (buttons=[(label, value)]): на них
    спускаются стрелкой «вниз», выбор возвращает value как результат ввода."""

    CSS = """
    _TextApp { align: center middle; }
    #t_message { width: 90%; padding: 1 2; }
    #t_input { width: 90%; }
    #t_buttons { width: 90%; height: auto; max-height: 40%; border: round $hl; }
    #theme_btn { dock: top; }
    """ + botinok_themes.THEME_BTN_CSS

    def __init__(self, message: str, default: str = "",
                 password: bool = False, buttons=None, **kwargs):
        super().__init__(**kwargs)
        self.message = message
        self.default = default
        self.password = password
        self.buttons = list(buttons or [])
        self.result: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield self.make_theme_btn()
        with Vertical():
            yield Static(self.message, id="t_message")
            yield Input(value=self.default, password=self.password, id="t_input")
            if self.buttons:
                yield OptionList(id="t_buttons")

    def on_mount(self) -> None:
        self.query_one("#t_input", Input).focus()
        if self.buttons:
            opts = self.query_one("#t_buttons", OptionList)
            for i, (label, _value) in enumerate(self.buttons):
                opts.add_option(Option(str(label), id=str(i)))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.result = event.value
        self.exit(event.value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            self.result = self.buttons[int(event.option.id)][1]
        except Exception:
            self.result = None
        self.exit(self.result)

    def on_key(self, event) -> None:
        key = getattr(event, "key", "")
        if key == "escape":
            event.stop()
            self.result = None
            self.exit(None)
        elif key == "down" and self.buttons and isinstance(self.focused, Input):
            # Уходим с поля ввода на список кнопок.
            event.stop()
            opts = self.query_one("#t_buttons", OptionList)
            opts.focus()
            if opts.option_count and opts.highlighted is None:
                opts.highlighted = 0
        elif key == "up" and self.buttons and isinstance(self.focused, OptionList):
            if self.focused.highlighted in (0, None):
                event.stop()
                self.query_one("#t_input", Input).focus()


def textual_select(message: str, choices: Sequence[Tuple[str, object]],
                   default: object = None,
                   filterable: bool = False) -> Optional[object]:
    """Выбор варианта. Возвращает значение или None при отмене.

    filterable=True добавляет поле быстрого фильтра над списком."""
    return _SelectApp(message, choices, default, filterable=filterable).run()


def textual_prompt(message: str, default: str = "",
                   password: bool = False, buttons=None) -> Optional[str]:
    """Ввод строки. Возвращает строку или None при отмене.

    buttons=[(label, value)] — кнопки под полем (стрелка «вниз» переводит
    на них фокус); выбор кнопки возвращает её value."""
    return _TextApp(message, default, password=password, buttons=buttons).run()


def textual_confirm(message: str, default: bool = True) -> Optional[bool]:
    """Да/Нет. Возвращает bool или None при отмене."""
    choices = [("Да", True), ("Нет", False)]
    result = textual_select(message, choices, default)
    if result is None:
        return None
    return bool(result)
