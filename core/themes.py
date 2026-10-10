"""Темы оформления TUI: ночь (текущая, по умолчанию), день (белая), вечер (голубая).

Палитра «ночь» — клон textual-dark: внешний вид не меняется. Кастомные CSS-переменные
(hdr-bg, hl, shell-bg и т.д.) несут цвета, которые раньше были захардкожены в CSS
приложения; в ночи они равны прежним литералам 1-в-1.

Выбор темы хранится ГЛОБАЛЬНО в ~/.config/botinok/config.cfg ([UI] theme) и действует
на все Textual-приложения (чат, меню, визарды, просмотр истории). Сохранение —
построчная правка, комментарии в конфиге сохраняются. ThemedAppMixin подключает темы
и иконку-переключатель к любому App.
"""

import copy
import os
import re

from textual.theme import BUILTIN_THEMES, Theme
from textual.widgets import Static

GLOBAL_CONFIG_PATH = os.path.expanduser(os.path.join("~", ".config", "botinok", "config.cfg"))

DEFAULT_THEME = "night"
THEME_ORDER = ("night", "day", "evening")
THEME_LABELS = {"night": "Ночь", "day": "День", "evening": "Вечер"}
THEME_GLYPHS = {"night": "☾", "day": "☀\ufe0e", "evening": "◓"}


def next_theme(name: str) -> str:
    """Следующая тема по циклу: ночь → день → вечер → ночь."""
    try:
        return THEME_ORDER[(THEME_ORDER.index(name) + 1) % len(THEME_ORDER)]
    except ValueError:
        return DEFAULT_THEME

# Ночь: те же цвета, что были зашиты в CSS BotinokTextualApp до появления тем.
_NIGHT_VARS = {
    "hdr-bg": "#0055aa",
    "hdr-fg": "white",
    "flag-bg": "#cc8800",
    "flag-fg": "black",
    "hl": "#00ffff",
    "ok": "green",
    "warn": "yellow",
    "err": "red",
    "danger-bg": "red",
    "warn-bg": "yellow",
    "shell-bg": "#0c0c0c",
    "cmd-bg": "#0f0f0f",
    "cmd-fg": "#d0d0d0",
    "cmd-border": "#5f87af",
    "pager-fg": "#6b8f9a",
    "accent-fg": "black",
}

_DAY_VARS = {
    "hdr-bg": "#2b6cb0",
    "hdr-fg": "#ffffff",
    "flag-bg": "#ffb300",
    "flag-fg": "#000000",
    "hl": "#0677c9",
    "ok": "#177a3d",
    "warn": "#a06800",
    "err": "#c02d2d",
    "danger-bg": "#c02d2d",
    "warn-bg": "#ffd75f",
    "shell-bg": "#fafafa",
    "cmd-bg": "#f0f0f0",
    "cmd-fg": "#1a1a1a",
    "cmd-border": "#7fa6c9",
    "pager-fg": "#5a7a8a",
    "accent-fg": "#ffffff",
}

_EVENING_VARS = {
    "hdr-bg": "#08406f",
    "hdr-fg": "#eaf6ff",
    "flag-bg": "#2b7bb8",
    "flag-fg": "#eaf6ff",
    "hl": "#7ec8ff",
    "ok": "#5fd68f",
    "warn": "#ffd75f",
    "err": "#ff7b7b",
    "danger-bg": "#a03030",
    "warn-bg": "#b8860b",
    "shell-bg": "#0a2236",
    "cmd-bg": "#0d2b45",
    "cmd-fg": "#d6ecff",
    "cmd-border": "#4a90c4",
    "pager-fg": "#6fa8cc",
    "accent-fg": "#062033",
}


def build_themes() -> dict:
    """Три темы: night (клон textual-dark, дефолт), day (белая), evening (голубая)."""
    night = copy.copy(BUILTIN_THEMES["textual-dark"])
    night.name = "night"
    night.variables = dict(_NIGHT_VARS)

    day = Theme(
        name="day",
        dark=False,
        primary="#1d6fd6",
        secondary="#0a4a8f",
        accent="#0677c9",
        background="#ffffff",
        surface="#f2f2f2",
        panel="#e2e2e2",
        foreground="#111111",
        success="#177a3d",
        warning="#a06800",
        error="#c02d2d",
        variables=dict(_DAY_VARS),
    )

    evening = Theme(
        name="evening",
        dark=True,
        primary="#4aa8e8",
        secondary="#2b7bb8",
        accent="#7ec8ff",
        background="#0d2b45",
        surface="#10324f",
        panel="#143a5c",
        foreground="#d6ecff",
        success="#5fd68f",
        warning="#ffd75f",
        error="#ff7b7b",
        variables=dict(_EVENING_VARS),
    )

    return {"night": night, "day": day, "evening": evening}


def resolve_theme_name(config) -> str:
    """Имя темы из [UI] theme данного конфига; любое неизвестное/пустое — night."""
    try:
        name = (config.get("UI", "theme", fallback="") or "").strip().lower()
    except Exception:
        name = ""
    return name if name in THEME_ORDER else DEFAULT_THEME


def load_theme_name(fallback_config=None) -> str:
    """Глобальный ~/.config/botinok/config.cfg > fallback_config > night."""
    try:
        if os.path.exists(GLOBAL_CONFIG_PATH):
            import configparser
            cp = configparser.ConfigParser()
            cp.read(GLOBAL_CONFIG_PATH, encoding="utf-8")
            name = resolve_theme_name(cp)
            if name != DEFAULT_THEME or cp.has_option("UI", "theme"):
                return name
    except Exception:
        pass
    if fallback_config is not None:
        return resolve_theme_name(fallback_config)
    return DEFAULT_THEME


def save_theme_name(name: str, path=None) -> bool:
    """Записать [UI] theme = <name> построчно (комментарии целы).

    path=None — глобальный ~/.config/botinok/config.cfg (для всех).
    """
    if name not in THEME_ORDER:
        return False
    path = path or GLOBAL_CONFIG_PATH
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        lines = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        ui_idx = next((i for i, ln in enumerate(lines)
                       if ln.strip().lower() == "[ui]"), None)
        if ui_idx is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append("[UI]")
            lines.append(f"theme = {name}")
        else:
            end = next((i for i in range(ui_idx + 1, len(lines))
                        if lines[i].strip().startswith("[")), len(lines))
            key = re.compile(r"^\s*theme\s*=", re.IGNORECASE)
            replaced = False
            for i in range(ui_idx + 1, end):
                if key.match(lines[i]):
                    lines[i] = f"theme = {name}"
                    replaced = True
                    break
            if not replaced:
                lines.insert(end, f"theme = {name}")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# CSS для приложений с иконкой-переключателем (добавляется к CSS каждого App).
THEME_BTN_CSS = """
.theme_btn { width: auto; height: 1; padding: 0 1; margin: 0; border: none;
             background: transparent; color: $text-muted; }
.theme_btn:hover { color: $accent; text-style: bold underline; }
"""


class ThemedAppMixin:
    """Подключает темы к любому Textual App: регистрация, глобальный выбор,
    иконка-цикл в левом верхнем углу (make_theme_btn в compose), персист."""

    def __init__(self, *args, **kwargs):
        self.theme_btn = None
        self.config_path = None
        super().__init__(*args, **kwargs)
        for _t in build_themes().values():
            self.register_theme(_t)
        self.theme = load_theme_name()

    def make_theme_btn(self):
        """Иконка, показывающая СЛЕДУЮЩУЮ тему цикла; клик — применить."""
        nxt = next_theme(self.theme)
        btn = Static(THEME_GLYPHS[nxt], classes="theme_btn", id="theme_btn")
        try:
            btn.tooltip = ("Тема: " + THEME_LABELS[self.theme]
                           + " (клик — " + THEME_LABELS[nxt] + ")")
        except Exception:
            pass
        self.theme_btn = btn
        return btn

    def apply_theme(self, name: str) -> None:
        if name not in THEME_ORDER:
            return
        self.theme = name
        save_theme_name(name, self.config_path)

    def on_click(self, event) -> None:
        try:
            if self.theme_btn is not None and getattr(event, "widget", None) is self.theme_btn:
                self.apply_theme(next_theme(self.theme))
                event.stop()
                return
        except Exception:
            pass
        _super = getattr(super(), "on_click", None)
        if _super is not None:
            try:
                _super(event)
            except Exception:
                pass

    def watch_theme(self, old_theme: str, new_theme: str) -> None:
        try:
            nxt = next_theme(new_theme)
            targets = []
            if self.theme_btn is not None:
                targets.append(self.theme_btn)
            try:
                targets.extend(self.query(".theme_btn"))
            except Exception:
                pass
            for b in targets:
                try:
                    b.update(THEME_GLYPHS[nxt])
                    b.tooltip = ("Тема: " + THEME_LABELS[new_theme]
                                 + " (клик — " + THEME_LABELS[nxt] + ")")
                except Exception:
                    pass
        except Exception:
            pass
