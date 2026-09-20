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

import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from core.text_width import cell_width, cell_truncate


def _human_size(size: Optional[int]) -> str:
    """Размер в удобочитаемом виде (None — ещё считается)."""
    if size is None:
        return "…"
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


SIZE_COL_WIDTH = 8      # ширина столбика размера
DETAILS_ICON = "ⓘ"      # юникод-иконка «подробности/действия» в конце строки
DETAILS_RESERVED = 2    # резерв под иконку: глиф бывает шириной 1 ИЛИ 2 ячейки
DETAILS_ZONE = 3        # кликабельная зона: пробел + иконка (с запасом)
DETAILS_HINT = "Действия по сессии: открыть, клонировать, проверить, папка, удалить"


def _dir_stats(path: str) -> Tuple[int, int]:
    """(размер папки, число файлов). Папка может содержать тысячи файлов."""
    total = 0
    files_count = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                files_count += 1
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except OSError:
        pass
    return total, files_count


def _dir_size(path: str) -> int:
    return _dir_stats(path)[0]


def _check_session(path: str) -> Tuple[List[str], List[str]]:
    """Простая проверка целостности сессии: (проблемы, успехи)."""
    issues: List[str] = []
    ok: List[str] = []
    if not os.path.isdir(path):
        return ["папка сессии не найдена"], []
    if not os.listdir(path):
        issues.append("папка пуста")
    for fname in ("context.json", "messages.json"):
        fpath = os.path.join(path, fname)
        if not os.path.exists(fpath):
            issues.append(f"{fname}: отсутствует")
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                json.load(fh)
            ok.append(f"{fname}: ok")
        except Exception as exc:
            issues.append(f"{fname}: повреждён ({exc.__class__.__name__})")
    return issues, ok


class _SessionActions(ModalScreen):
    """Подробности сессии: статистика и действия (открыть/папка/удалить)."""

    CSS = """
    _SessionActions { align: center middle; }
    #pk_actions { width: 70%; height: auto; border: solid cyan; padding: 1 2;
                  background: $surface; }
    #pk_stats_title { height: auto; padding: 0 0 1 0; }
    #pk_stats { height: auto; padding: 0 0 1 0; }
    #pk_actions_buttons { height: auto; align-horizontal: right; }
    #pk_actions_buttons Button { margin-left: 2; }
    """

    def __init__(self, name: str, path: str):
        super().__init__()
        self._name = name
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical(id="pk_actions"):
            yield Static(f"[bold]Сессия:[/bold] {self._name}", id="pk_stats_title")
            yield Static("…", id="pk_stats")
            yield Static("", id="pk_check")
            with Horizontal(id="pk_actions_buttons"):
                yield Button("Открыть", variant="primary", id="pk_open")
                yield Button("Клонировать", id="pk_clone")
                yield Button("Проверить", id="pk_check_btn")
                yield Button("Перейти в папку", id="pk_cd")
                yield Button("Удалить", variant="error", id="pk_delete")
                yield Button("Отмена", id="pk_no")

    def on_mount(self) -> None:
        path = self._path

        def worker() -> None:
            size, files = _dir_stats(path)
            text = (f"Путь: {path}\n"
                    f"Размер: {_human_size(size)} · файлов: {files}")
            try:
                self.app.call_from_thread(self._set_stats, text)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _set_stats(self, text: str) -> None:
        try:
            self.query_one("#pk_stats", Static).update(text)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = getattr(event.button, "id", "")
        if button_id == "pk_check_btn":
            self._run_check()
            return
        action = {
            "pk_open": "open",
            "pk_clone": "clone",
            "pk_cd": "cd",
            "pk_delete": "delete",
            "pk_no": "cancel",
        }.get(button_id, "cancel")
        self.dismiss(action)

    def _run_check(self) -> None:
        path = self._path

        def worker() -> None:
            issues, ok = _check_session(path)
            if issues:
                text = "[yellow]Проверка: есть проблемы[/yellow]\n" + "\n".join(
                    f"· {item}" for item in issues
                )
            else:
                text = "[green]Проверка: всё в порядке[/green]\n" + "\n".join(
                    f"· {item}" for item in ok
                )
            try:
                self.app.call_from_thread(self._set_check, text)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _set_check(self, text: str) -> None:
        try:
            self.query_one("#pk_check", Static).update(text)
        except Exception:
            pass

    def on_key(self, event) -> None:
        if getattr(event, "key", "") == "escape":
            event.stop()
            self.dismiss("cancel")


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
        return datetime.fromtimestamp(float(mtime)).strftime("%H:%M %d.%m.%y")
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

    def __init__(self, latest_name: str, preview_loader=None, **kwargs):
        super().__init__(**kwargs)
        self.latest_name = latest_name
        self._preview_loader = preview_loader

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
            self.app.push_screen(_ListScreen(self._preview_loader))

    def on_key(self, event) -> None:
        if getattr(event, "key", "") == "escape":
            event.stop()
            self.app.exit(("cancel", ""))


class _NamePrompt(ModalScreen):
    """Ввод имени для клонирования сессии."""

    CSS = """
    _NamePrompt { align: center middle; }
    #pk_name_box { width: 60%; height: auto; border: solid cyan; padding: 1 2;
                   background: $surface; }
    #pk_name_buttons { height: auto; align-horizontal: right; }
    #pk_name_buttons Button { margin-left: 2; }
    """

    def __init__(self, prompt: str):
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="pk_name_box"):
            yield Static(self._prompt)
            yield Input(placeholder="название", id="pk_name_input")
            with Horizontal(id="pk_name_buttons"):
                yield Button("OK", variant="primary", id="pk_name_ok")
                yield Button("Отмена", id="pk_name_no")

    def on_mount(self) -> None:
        self.query_one("#pk_name_input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if getattr(event.button, "id", "") == "pk_name_no":
            self.dismiss(None)
            return
        try:
            self.dismiss(self.query_one("#pk_name_input", Input).value)
        except Exception:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value)

    def on_key(self, event) -> None:
        if getattr(event, "key", "") == "escape":
            event.stop()
            self.dismiss(None)


class _SessionRow(Horizontal):
    """Строка списка сессий: текст (клик — открыть) + кнопка действий (ⓘ)."""

    def __init__(self, path: str, text: str):
        super().__init__(classes="session-row")
        self.path = path
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(self._text, classes="row-text", markup=False)
        button = Button("ⓘ", classes="row-info")
        try:
            button.tooltip = DETAILS_HINT
        except Exception:
            pass
        yield button

    def set_text(self, text: str) -> None:
        self._text = text
        try:
            self.query_one(".row-text", Static).update(text)
        except Exception:
            pass


class _ListScreen(Screen):
    """Второй экран: список сессий с фильтром (строки-виджеты)."""

    CSS = """
    _ListScreen { align: center middle; }
    #pk_list_box { width: 96%; height: 90%; }
    #pk_list_title { width: 100%; padding: 0 0 1 0; }
    #pk_filter_row { width: 100%; height: auto; }
    #pk_filter { width: 1fr; }
    #pk_rows { width: 100%; height: 1fr; border: solid cyan; padding: 0; }
    _SessionRow { width: 100%; height: 1; }
    _SessionRow .row-text { width: 1fr; height: 1; }
    _SessionRow .row-info { width: auto; min-width: 1; height: 1; border: none;
                           padding: 0; margin: 0; background: transparent;
                           color: $text-muted; text-style: bold;
                           content-align: center middle; }
    _SessionRow .row-info:hover, _SessionRow .row-info:focus {
                           color: cyan; background: transparent; text-style: bold underline; }
    _SessionRow.selected { background: $block-cursor-background; }
    _SessionRow.selected .row-text { color: $block-cursor-foreground; }
    """

    INFO_COL_WIDTH = 3  # столбец кнопки действий (фактическая ширина Button)

    def __init__(self, preview_loader=None, **kwargs):
        super().__init__(**kwargs)
        self._preview_loader = preview_loader
        self._meta: dict = {}       # path -> {"size": int, "preview": str}
        self._meta_started = False
        self._avail = 0
        self._rows: dict = {}
        self._order: List[str] = []
        self._selected = 0
        self._resize_timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="pk_list_box"):
            yield Static(
                "[bold cyan]Выбор сессии[/bold cyan]\n"
                "[dim]↑↓ — выбор · Enter — открыть · ввод — фильтр · "
                "ⓘ — действия · 0 — новая · Esc — назад[/dim]",
                id="pk_list_title",
            )
            with Horizontal(id="pk_filter_row"):
                yield Input(placeholder="фильтр по названию/превью...", id="pk_filter")
            yield VerticalScroll(id="pk_rows")

    def on_mount(self) -> None:
        self._rebuild("")
        self.call_after_refresh(lambda: self._rebuild(self.query_one("#pk_filter", Input).value))
        self.query_one("#pk_filter", Input).focus()
        self._start_meta_loading()
        # Ширина «устаивается» не сразу — пара отложенных пересчётов.
        self.set_timer(0.15, lambda: self._reflow(force=True))
        self.set_timer(0.5, lambda: self._reflow(force=True))

    def _start_meta_loading(self) -> None:
        """Фон: СНАЧАЛА имена (быстро), ПОТОМ размеры папок (медленно)."""
        if self._meta_started:
            return
        self._meta_started = True
        sessions = list(self._sessions())

        def paths() -> list:
            return [
                s.get("path") or ""
                for s in sessions
                if (s.get("path") or "") and os.path.isdir(s.get("path") or "")
            ]

        def worker() -> None:
            # Фаза 1: имена — параллельно (I/O), обновляем строки по мере готовности.
            if self._preview_loader is not None:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    futures = {
                        pool.submit(self._preview_loader, path): path for path in paths()
                    }
                    for future in as_completed(futures):
                        path = futures[future]
                        try:
                            preview = future.result()
                        except Exception:
                            preview = ""
                        try:
                            self.app.call_from_thread(self._set_preview, path, preview)
                        except Exception:
                            return
            # Фаза 2: размеры папок — тоже параллельно, но меньшим числом потоков.
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(_dir_size, path): path for path in paths()}
                for future in as_completed(futures):
                    path = futures[future]
                    try:
                        size = future.result()
                    except Exception:
                        size = 0
                    try:
                        self.app.call_from_thread(self._set_size, path, size)
                    except Exception:
                        return

        threading.Thread(target=worker, daemon=True).start()

    def _set_preview(self, path: str, preview: str) -> None:
        self._meta.setdefault(path, {})["preview"] = preview
        self._update_row_in_place(path)

    def _set_size(self, path: str, size: int) -> None:
        self._meta.setdefault(path, {})["size"] = size
        self._update_row_in_place(path)

    def _measure_width(self) -> int:
        """Точная ширина текстовой части строки (мера по факту раскладки)."""
        try:
            row = next(iter(self._rows.values()))
            measured = row.query_one(".row-text").region.width
            if measured:
                return max(20, measured)
        except Exception:
            pass
        return max(20, self._avail or self._list_width())

    def _reflow(self, force: bool = False) -> None:
        """Пересчитать ширину текста по факту и переформатировать строки БЕЗ
        пересборки (на ресайзе) — прокрутка и выделение сохраняются."""
        measured = self._measure_width()
        if measured == self._avail and not force:
            return  # ширина не изменилась — ничего не переписываем
        self._avail = measured
        for s in self._sessions():
            path = s.get("path") or ""
            row = self._rows.get(path)
            if row is not None:
                row.set_text(self._text_for(s, self._avail))

    def _update_row_in_place(self, path: str) -> None:
        row = self._rows.get(path)
        if row is None:
            return
        session = None
        for s in self._sessions():
            if (s.get("path") or "") == path:
                session = s
                break
        if session is None:
            return
        measured = self._measure_width()
        if measured != self._avail:
            # Ширина поменялась — переформатируем ВСЕ строки под неё.
            self._reflow(force=True)
        else:
            row.set_text(self._text_for(session, self._avail))

    def _sessions(self) -> List[dict]:
        return getattr(self.app, "sessions", [])

    def _list_width(self) -> int:
        """Ширина текстовой части строки (минус столбец кнопки)."""
        try:
            rows = self.query_one("#pk_rows", VerticalScroll)
            width = rows.content_region.width
        except Exception:
            width = 0
        if width <= 0:
            width = int(self.size.width * 0.96) - 4
        return max(20, width - self.INFO_COL_WIDTH)

    def _text_for(self, s: dict, avail: int) -> str:
        """`дата · срок · текст… размер` — размер прижат вправо."""
        path = s.get("path") or ""
        meta = self._meta.get(path, {})
        preview = meta.get("preview")
        ts = _absolute_time(s.get("mtime"))
        rel = _relative_time(s.get("mtime"))
        if preview is None:
            first = "…"
        else:
            first = " ".join(str(preview).split()) or "(без названия)"
        size_txt = _human_size(meta.get("size"))
        size_cell = " " * max(0, SIZE_COL_WIDTH - cell_width(size_txt)) + size_txt
        left_area = max(8, avail - SIZE_COL_WIDTH - 1)
        left = cell_truncate(f"{ts}  ·  {rel}  ·  {first}", left_area, ellipsis="...")
        left += " " * max(0, left_area - cell_width(left))
        return left + " " + size_cell

    def _rebuild(self, flt: str) -> None:
        rows = self.query_one("#pk_rows", VerticalScroll)
        rows.remove_children()
        self._rows = {}
        self._order = []
        self._avail = 0  # ширина ещё неизвестна — определим после раскладки
        estimate = self._list_width()
        flt = (flt or "").strip().lower()
        for s in self._sessions():
            path = s.get("path") or ""
            name = s.get("name") or "(unknown)"
            preview = self._meta.get(path, {}).get("preview")
            if flt and flt not in name.lower() and flt not in str(preview or "").lower():
                continue
            row = _SessionRow(path, self._text_for(s, estimate))
            rows.mount(row)
            self._rows[path] = row
            self._order.append(path)
        if self._selected >= len(self._order):
            self._selected = max(0, len(self._order) - 1)
        self._apply_selection()
        # После раскладки уточняем ширину текста ПО ФАКТУ и переформатируем.
        self.call_after_refresh(self._reflow)

    def _apply_selection(self) -> None:
        for i, path in enumerate(self._order):
            row = self._rows.get(path)
            if row is None:
                continue
            try:
                if i == self._selected:
                    row.add_class("selected")
                    row.scroll_visible()
                else:
                    row.remove_class("selected")
            except Exception:
                pass

    def action_session_actions(self) -> None:
        if self._order:
            self._open_actions(self._order[self._selected])

    def _open_actions(self, path: str) -> None:
        if not path:
            return
        name = os.path.basename(path)

        def done(action) -> None:
            if action == "open":
                self.app.exit(("path", path))
            elif action == "delete":
                shutil.rmtree(path, ignore_errors=True)
                self._meta.pop(path, None)
                try:
                    self.app.sessions = [
                        s for s in self._sessions() if (s.get("path") or "") != path
                    ]
                except Exception:
                    pass
                self._rebuild(self.query_one("#pk_filter", Input).value)
            elif action == "cd":
                self._open_shell_in(path)
            elif action == "clone":
                self._clone_session(path)

        self.app.push_screen(_SessionActions(name, path), done)

    def _clone_session(self, path: str) -> None:
        def with_name(new_name: Optional[str]) -> None:
            if not new_name or not new_name.strip():
                return
            safe = "".join(
                ch if (ch.isalnum() or ch in "-_") else "_" for ch in new_name.strip()
            ).strip("_") or "clone"
            new_path = os.path.join(
                os.path.dirname(path),
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}",
            )

            def worker() -> None:
                try:
                    shutil.copytree(path, new_path)
                except Exception:
                    return
                try:
                    self.app.call_from_thread(self.app.exit, ("path", new_path))
                except Exception:
                    pass

            threading.Thread(target=worker, daemon=True).start()

        self.app.push_screen(_NamePrompt("Имя новой сессии:"), with_name)

    def _open_shell_in(self, path: str) -> None:
        try:
            with self.app.suspend():
                subprocess.call(["bash"], cwd=path)
        except Exception:
            pass
        finally:
            try:
                self._rebuild(self.query_one("#pk_filter", Input).value)
            except Exception:
                pass

    def on_resize(self, event) -> None:
        # Дебаунс: во время перетаскивания окна не пересчитываем на каждый тик,
        # только после паузы; и только переформатирование (без пересборки).
        try:
            if getattr(self, "_resize_timer", None) is not None:
                self._resize_timer.stop()
        except Exception:
            pass
        self._resize_timer = self.set_timer(0.05, self._reflow)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._rebuild(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip() == "0":
            self.app.exit(("new", ""))
            return
        if self._order:
            self.app.exit(("path", self._order[self._selected]))

    def on_click(self, event) -> None:
        # Клик по тексту строки — открыть сессию.
        try:
            widget = event.widget
        except Exception:
            return
        if widget is None or not getattr(widget, "has_class", lambda _c: False)("row-text"):
            return
        node = widget
        while node is not None and not isinstance(node, _SessionRow):
            node = getattr(node, "parent", None)
        if isinstance(node, _SessionRow):
            event.stop()
            self.app.exit(("path", node.path))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            if not event.button.has_class("row-info"):
                return
        except Exception:
            return
        node = event.button
        while node is not None and not isinstance(node, _SessionRow):
            node = getattr(node, "parent", None)
        if isinstance(node, _SessionRow):
            event.stop()
            self._open_actions(node.path)

    def on_key(self, event) -> None:
        key = getattr(event, "key", "")
        if key == "escape":
            event.stop()
            self.app.pop_screen()
            return
        if not self._order:
            return
        if key in ("down", "up"):
            delta = 1 if key == "down" else -1
            self._selected = max(0, min(len(self._order) - 1, self._selected + delta))
            self._apply_selection()
            event.stop()
            return
        if key == "delete":
            event.stop()
            self._open_actions(self._order[self._selected])
            return
        if key == "enter":
            event.stop()
            self.app.exit(("path", self._order[self._selected]))
            return


class SessionPickerApp(App):
    """Двухшаговый выбор сессии."""

    CSS = """
    SessionPickerApp { background: $surface; }
    """

    def __init__(self, sessions: List[dict], latest_name: str, preview_loader=None, **kwargs):
        super().__init__(**kwargs)
        self.sessions = sessions
        self.latest_name = latest_name
        self._preview_loader = preview_loader

    def get_default_screen(self) -> Screen:
        return _MenuScreen(self.latest_name, self._preview_loader)


def pick_session(sessions: List[dict], latest_name: str, preview_loader=None) -> Tuple[str, str]:
    """Показать экран выбора. Возвращает (action, path); action: latest/new/path/cancel."""
    result = SessionPickerApp(sessions, latest_name, preview_loader).run()
    if not result:
        return ("cancel", "")
    return result
