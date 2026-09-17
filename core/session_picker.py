"""
Textual-экран выбора/возобновления сессии (замена inquirer + readchar-таблицы).

UX как раньше, в два шага:
  1) меню из трёх пунктов: «Продолжить последнюю», «Выбрать другую сессию»,
     «Начать новую сессию»;
  2) список сессий с живым фильтром — только если выбран пункт «Выбрать другую».

Запускается из `botinok.py::_choose_or_resume_session` до основного TUI.
Возвращает кортеж действия: ("latest"|"new"|"path"|"cancel", path).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional, Tuple

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option


def _relative_time(timestamp) -> str:
    if not timestamp:
        return "unknown"
    try:
        diff = datetime.now().timestamp() - float(timestamp)
        if diff < 60:
            return f"{int(diff)} сек назад"
        if diff < 3600:
            return f"{int(diff / 60)} мин назад"
        if diff < 86400:
            return f"{int(diff / 3600)} час назад"
        if diff < 604800:
            return f"{int(diff / 86400)} дн назад"
        return f"{int(diff / 604800)} нед назад"
    except Exception:
        return "unknown"


def _absolute_time(mtime) -> str:
    try:
        return datetime.fromtimestamp(float(mtime)).strftime("%H:%M %d.%m")
    except Exception:
        return "unknown"


class _MenuScreen(Screen):
    """Первый экран: три действия."""

    CSS = """
    _MenuScreen { align: center middle; }
    #pk_menu_box { width: 90%; height: auto; }
    #pk_menu_title { width: 100%; padding: 0 0 1 0; }
    #pk_menu { width: 100%; height: auto; border: solid cyan; }
    """

    def __init__(self, latest_name: str, **kwargs):
        super().__init__(**kwargs)
        self.latest_name = latest_name

    def compose(self) -> ComposeResult:
        with Vertical(id="pk_menu_box"):
            yield Static(
                "[bold cyan]Старт BOTINOK: выбрать сессию[/bold cyan]\n"
                "[dim]↑↓ — выбор · Enter — открыть · Esc — отмена[/dim]",
                id="pk_menu_title",
            )
            yield OptionList(id="pk_menu")

    def on_mount(self) -> None:
        options = self.query_one("#pk_menu", OptionList)
        options.add_option(Option(f"▶ Продолжить последнюю: {self.latest_name}", id="latest"))
        options.add_option(Option("☰ Выбрать другую сессию", id="choose"))
        options.add_option(Option("＋ Начать новую сессию", id="new"))
        options.highlighted = 0
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        key = event.option.id or ""
        if key == "latest":
            self.app.exit(("latest", ""))
        elif key == "new":
            self.app.exit(("new", ""))
        elif key == "choose":
            self.app.push_screen(_ListScreen())

    def on_key(self, event) -> None:
        if getattr(event, "key", "") == "escape":
            event.stop()
            self.app.exit(("cancel", ""))


class _ListScreen(Screen):
    """Второй экран: список сессий с фильтром."""

    CSS = """
    _ListScreen { align: center middle; }
    #pk_list_box { width: 96%; height: 90%; }
    #pk_list_title { width: 100%; padding: 0 0 1 0; }
    #pk_filter { width: 100%; }
    #pk_list { width: 100%; height: 1fr; border: solid cyan; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="pk_list_box"):
            yield Static(
                "[bold cyan]Выбор сессии[/bold cyan]\n"
                "[dim]↑↓ — выбор · Enter — открыть · ввод — фильтр · "
                "0 — новая · Esc — назад[/dim]",
                id="pk_list_title",
            )
            yield Input(placeholder="фильтр по названию/превью...", id="pk_filter")
            yield OptionList(id="pk_list")

    def on_mount(self) -> None:
        self._rebuild("")
        self.query_one("#pk_filter", Input).focus()

    def _sessions(self) -> List[dict]:
        return getattr(self.app, "sessions", [])

    def _entries(self, flt: str) -> List[Tuple[str, str]]:
        flt = (flt or "").strip().lower()
        entries: List[Tuple[str, str]] = []
        for s in self._sessions():
            name = s.get("name") or "(unknown)"
            preview = s.get("preview") or ""
            if flt and flt not in name.lower() and flt not in str(preview).lower():
                continue
            ts = _absolute_time(s.get("mtime"))
            rel = _relative_time(s.get("mtime"))
            prev = (preview or "...")[:50]
            label = f"{name}  ·  {ts}  ·  {rel}  ·  {prev}"
            entries.append((f"path:{s.get('path', '')}", label))
        return entries

    def _rebuild(self, flt: str) -> None:
        options = self.query_one("#pk_list", OptionList)
        options.clear_options()
        for key, label in self._entries(flt):
            options.add_option(Option(label, id=key))
        if options.option_count:
            options.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._rebuild(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip() == "0":
            self.app.exit(("new", ""))
            return
        self.query_one("#pk_list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        key = event.option.id or ""
        if key.startswith("path:"):
            self.app.exit(("path", key[len("path:"):]))

    def on_key(self, event) -> None:
        key = getattr(event, "key", "")
        if key == "escape":
            event.stop()
            self.app.pop_screen()
            return
        # Стрелки переключают фокус между фильтром и списком, чтобы можно было
        # навигировать сразу, как в старом readchar-меню.
        if key == "down":
            try:
                if isinstance(self.focused, Input):
                    self.query_one("#pk_list", OptionList).focus()
                    event.stop()
            except Exception:
                pass
        elif key == "up":
            try:
                options = self.query_one("#pk_list", OptionList)
                if self.focused is options and (options.highlighted or 0) == 0:
                    self.query_one("#pk_filter", Input).focus()
                    event.stop()
            except Exception:
                pass


class SessionPickerApp(App):
    """Двухшаговый выбор сессии."""

    CSS = """
    SessionPickerApp { background: $surface; }
    """

    def __init__(self, sessions: List[dict], latest_name: str, **kwargs):
        super().__init__(**kwargs)
        self.sessions = sessions
        self.latest_name = latest_name

    def get_default_screen(self) -> Screen:
        return _MenuScreen(self.latest_name)


def pick_session(sessions: List[dict], latest_name: str) -> Tuple[str, str]:
    """Показать экран выбора. Возвращает (action, path); action: latest/new/path/cancel."""
    result = SessionPickerApp(sessions, latest_name).run()
    if not result:
        return ("cancel", "")
    return result
