"""
Textual-экран встроенного терминала (ShellScreen).

Встраивается в BotinokTextualApp как модальный экран:
  * команда крутится в PTY-сессии (core/shell_session.ShellSession);
  * пользователь видит живой вывод и может вводить текст/пароли прямо в окно;
  * «Свернуть» (Ctrl+Q) — спрятать окно, сессия остаётся живой и попадает
    в панель свёрнутых терминалов на основном экране;
  * «Закрыть» — закрыть окно и завершить сессию;
  * Ctrl+C — SIGINT в сессию.

Экран НЕ блокирует агентский цикл: ShellSession живёт в фоне после сворачивания,
и агент может продолжать читать её вывод и слать ввод через инструмент shell.
"""

from __future__ import annotations

import asyncio
import functools
import os
import shutil
import subprocess
import sys
import threading
from typing import Optional, Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static
from textual.widgets import RichLog

from rich.markup import escape as _markup_escape
from rich.text import Text


_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_SHXFMT_PATH: Optional[str] = None


def _shfmt_binary() -> Optional[str]:
    """Путь к бинарю shfmt (ставится пакетом shfmt-py), иначе None."""
    global _SHXFMT_PATH
    if _SHXFMT_PATH is not None:
        return _SHXFMT_PATH or None
    cand = shutil.which("shfmt")
    if not cand:
        exe_dir = os.path.dirname(sys.executable)
        local = os.path.join(exe_dir, "shfmt")
        cand = local if os.path.exists(local) else shutil.which("shfmt", path=exe_dir)
    _SHXFMT_PATH = cand or ""
    return cand


@functools.lru_cache(maxsize=256)
def format_shell_command(command: str) -> str:
    """Красиво развернуть shell-команду через shfmt (mvdan/sh).

    shfmt полноценно парсит bash и pretty-принтит: разбивает `;` на строки,
    сохраняет `for …; do`, выравнивает тело и `done`. Если shfmt недоступен
    или команда не парсится — возвращаем исходную строку.
    """
    cmd = (command or "").strip()
    if not cmd:
        return cmd
    binary = _shfmt_binary()
    if not binary:
        return cmd
    try:
        proc = subprocess.run(
            [binary, "-i", "2", "-"],
            input=cmd.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        out = proc.stdout.decode("utf-8", "replace").strip() if proc.stdout else ""
        return out or cmd
    except Exception:
        return cmd


def _fmt_elapsed(secs) -> str:
    secs = int(secs or 0)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m{secs % 60:02d}s"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"


def _terminal_title(session, frame: int = 0) -> str:
    """Заголовок терминала: статус, счётчик времени и анимация для «идёт».

    Динамические значения экранируются — команда может содержать «[».
    """
    name = _markup_escape((getattr(session, "name", "") or "shell").strip())
    cwd = _markup_escape(getattr(session, "cwd", "") or "")
    try:
        secs = int(session.elapsed)
    except Exception:
        secs = 0
    dur = _fmt_elapsed(secs)
    rc = getattr(session, "returncode", None)
    try:
        running = session.is_running()
    except Exception:
        running = rc is None
    if running:
        spin = _SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]
        head = f"[yellow]{spin}[/yellow] [b]{name}[/b] · [green]идёт {dur}[/green]"
    elif rc is not None:
        head = (f"[green]✔[/green] [b]{name}[/b] · "
                f"[green]завершено за {dur}[/green] (rc={rc})")
    else:
        head = f"[red]■[/red] [b]{name}[/b] · остановлено {dur}"
    tail = f" · cwd: {cwd}" if cwd else ""
    return f" {head}{tail} "


def _is_finished(session) -> bool:
    try:
        return not session.is_running()
    except Exception:
        return getattr(session, "returncode", None) is not None


def _terminal_done_text(session) -> Text:
    """Строка-маркер в лог терминала: явно видно, что команда закончилась."""
    try:
        dur = _fmt_elapsed(int(session.elapsed))
    except Exception:
        dur = "--"
    rc = getattr(session, "returncode", None)
    if rc is not None:
        return Text(f"─── завершено за {dur} (rc={rc}) ───", style="bold green")
    return Text(f"─── остановлено · {dur} ───", style="bold yellow")


class ShellScreen(ModalScreen):
    """Модальный экран «встроенный терминал».

    Параметры:
        session: уже стартовавшая ShellSession (владение не передаётся —
                 сессия остаётся живой и после закрытия экрана).
        on_done: колбэк, вызываемый при закрытии: on_done(session).
    """

    BINDINGS = []

    CSS = """
    ShellScreen {
        align: center middle;
        background: $surface;
    }
    #shell_dialog {
        width: 92%;
        height: 88%;
        border: thick green;
        background: $surface;
        padding: 0;
    }
    #shell_title {
        height: 1;
        background: green;
        color: $text;
        padding: 0 1;
    }
    #shell_log {
        height: 1fr;
        border: none;
        padding: 0 1;
        background: #0c0c0c;
    }
    #shell_hint {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #shell_input {
        height: 3;
    }
    #shell_buttons {
        height: 3;
        align: right middle;
    }
    #shell_buttons Button {
        min-width: 12;
        height: 3;
        margin: 0 1;
    }
    """

    def __init__(
        self,
        session,
        on_done: Optional[Callable] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.on_done = on_done
        self._on_chunk = None
        self._view_closed = False
        self._tick_timer = None
        self._spin = 0
        self._done_written = False
        self._cmd_shown = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ UI

    def compose(self) -> ComposeResult:
        title = _terminal_title(self.session, 0)
        with Vertical(id="shell_dialog"):
            yield Static(title, id="shell_title")
            yield Static("", id="shell_cmd", markup=False)
            yield RichLog(id="shell_log", markup=False, highlight=False,
                          wrap=False, auto_scroll=True, min_width=60)
            yield Static("[dim]Enter — отправить · Ctrl+Q — свернуть · Ctrl+C — прервать · "
                         "клик по заголовку — команда[/dim]",
                         id="shell_hint")
            yield Input(placeholder="ввод в терминал...", id="shell_input")
            with Horizontal(id="shell_buttons"):
                yield Button("В окно", id="shell_inline", variant="primary")
                yield Button("Свернуть", id="shell_minimize", variant="default")
                yield Button("Закрыть", id="shell_close", variant="error")

    def on_mount(self) -> None:
        # Подписываемся на свежие порции сырого вывода PTY.
        self._on_chunk = self._handle_chunk
        self.session.subscribe(self._on_chunk)
        # Отдаём уже накопленный вывод (на случай, если экран открыт позже).
        try:
            log = self.query_one("#shell_log", RichLog)
            tail = self.session.get_raw_tail(max_bytes=64 * 1024)
            if tail:
                log.write(Text.from_ansi(tail.decode("utf-8", "ignore")))
        except Exception:
            pass
        try:
            self.query_one("#shell_input", Input).focus()
        except Exception:
            pass
        # Периодическая проверка состояния: статус + счётчик + анимация спиннера.
        self._tick_timer = self.set_interval(0.15, self._tick_state)

    def _tick_state(self) -> None:
        if self._view_closed:
            return
        try:
            title = self.query_one("#shell_title", Static)
        except Exception:
            return
        self._spin += 1
        title.update(_terminal_title(self.session, self._spin))
        # Один раз дописываем в лог явный маркер завершения.
        if not self._done_written and _is_finished(self.session):
            self._done_written = True
            try:
                self.query_one("#shell_log", RichLog).write(
                    _terminal_done_text(self.session))
            except Exception:
                pass

    # -------------------------------------------------------------- вывод

    def _handle_chunk(self, chunk: bytes) -> None:
        """Колбэк из потока-ридера PTY — отдаём порцию в RichLog.

        Внимание: вызывается из НЕ UI-потока (читатель PTY), где ContextVar
        active_app НЕ установлен. Поэтому приложение берём из глобального
        реестра (TextualAppRegistry) — это надёжнее self.app в потоке.
        Textual виджеты не потокобезопасны, поэтому весь DOM-доступ
        планируем через app.call_from_thread (если приложение недоступно —
        пишем в буфер).
        """
        if self._view_closed or not chunk:
            return
        app = None
        try:
            from core.shell_session import TextualAppRegistry
            app = TextualAppRegistry.get_app()
        except Exception:
            app = None
        if app is None:
            try:
                app = self.app
            except Exception:
                app = None
        if app is not None:
            try:
                app.call_from_thread(self._write_chunk, chunk)
                return
            except Exception:
                pass
        # Запасной вариант: пробуем напрямую (вне Textual event loop).
        try:
            self._write_chunk(chunk)
        except Exception:
            pass

    def _write_chunk(self, chunk: bytes) -> None:
        """Запись порции в RichLog — только из UI-потока."""
        try:
            log = self.query_one("#shell_log", RichLog)
        except Exception:
            return
        try:
            text = chunk.decode("utf-8", "ignore")
            log.write(Text.from_ansi(text))
        except Exception:
            try:
                log.write(chunk.decode("utf-8", "ignore"))
            except Exception:
                pass

    # -------------------------------------------------------------- ввод

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value
        event.input.value = ""
        self.session.send_input(text)

    def _send_ctrl_c(self) -> None:
        self.session.send_key("ctrl-c")
        try:
            self.query_one("#shell_input", Input).value = ""
        except Exception:
            pass

    # ---------------------------------------------------- команда целиком

    def on_click(self, event) -> None:
        """Клик по заголовку — показать/скрыть развёрнутую команду."""
        if getattr(getattr(event, "widget", None), "id", "") == "shell_title":
            event.stop()
            self._toggle_cmd()

    def _toggle_cmd(self) -> None:
        try:
            cmd_w = self.query_one("#shell_cmd", Static)
        except Exception:
            return
        self._cmd_shown = not self._cmd_shown
        if self._cmd_shown:
            raw = getattr(self.session, "command", "") or getattr(self.session, "name", "")
            try:
                cmd_w.update(format_shell_command(raw))
            except Exception:
                pass
        try:
            if self._cmd_shown:
                cmd_w.add_class("show")
            else:
                cmd_w.remove_class("show")
        except Exception:
            pass

    # ----------------------------------------------------------- закрытие

    def _resolve_app(self):
        """Единая точка получения живого приложения (UI-поток или рабочий)."""
        app = None
        try:
            from core.shell_session import TextualAppRegistry
            app = TextualAppRegistry.get_app()
        except Exception:
            app = None
        if app is None:
            try:
                app = self.app
            except Exception:
                app = None
        return app

    def _detach_view(self) -> bool:
        """Отписать экран от PTY и остановить таймер (идемпотентно)."""
        with self._lock:
            if self._view_closed:
                return False
            self._view_closed = True
        if self._tick_timer is not None:
            try:
                self._tick_timer.stop()
            except Exception:
                pass
            self._tick_timer = None
        if self._on_chunk is not None:
            self.session.unsubscribe(self._on_chunk)
            self._on_chunk = None
        return True

    def _defer_after_pop(self, callback) -> None:
        """Выполнить callback, когда активным снова станет основной экран.

        Возвращаться к DOM основного экрана прямо в обработчике pop_screen
        нельзя: модалка ещё активна и «подвешена». AwaitComplete от pop_screen
        ждать также ненадёжно, поэтому просто опрашиваем `app.screen`.
        """
        app = self._resolve_app()
        screen = self

        async def _run() -> None:
            for _ in range(100):
                await asyncio.sleep(0.02)
                try:
                    if app is None or app.screen is not screen:
                        break
                except Exception:
                    break
            try:
                callback()
            except Exception:
                pass

        try:
            asyncio.ensure_future(_run())
        except Exception:
            try:
                callback()
            except Exception:
                pass

    def _pop_screen(self, callback=None) -> bool:
        """Снять модалку; callback (если задан) вызвать после смены экрана."""
        try:
            awaitable = self.app.pop_screen()
        except Exception:
            # Инициировано не из UI-потока — снимаем через реестр приложения.
            app = self._resolve_app()
            if app is not None:
                try:
                    app.call_from_thread(lambda: self._do_pop(app))
                except Exception:
                    pass
            if callback is not None:
                self._defer_after_pop(callback)
            return False
        self._drive_pop(awaitable)
        if callback is not None:
            self._defer_after_pop(callback)
        return True

    def _detach(self) -> bool:
        """Отписать экран от PTY и снять со стека, НЕ трогая сессию.

        Возвращает False, если экран уже был отсоединён (идемпотентность).
        """
        if not self._detach_view():
            return False
        self._pop_screen(None)
        if self.on_done is not None:
            try:
                self.on_done(self.session)
            except Exception:
                pass
        return True

    def _close(self) -> None:
        """Свернуть окно, оставив сессию живой (совместимость со старым вызовом)."""
        self._detach()

    def _minimize(self) -> None:
        """Спрятать окно и показать сессию в панели свёрнутых терминалов.

        Панель — DOM основного экрана, поэтому обновляем её только после того,
        как модалка фактически снята (`_defer_after_pop`). Иначе сообщения
        подвисают: модалка не домонтируется и UI перестаёт перерисовываться,
        хотя фон продолжает работать.
        """
        if not self._detach_view():
            return
        app = self._resolve_app()
        if app is not None:
            self._pop_screen(lambda: app.minimize_shell_session(self.session))
        if self.on_done is not None:
            try:
                self.on_done(self.session)
            except Exception:
                pass

    def _to_inline(self) -> None:
        """Вернуть терминал в окно вывода: модалка снимается, панель встраивается."""
        if not self._detach_view():
            return
        app = self._resolve_app()
        if app is not None:
            self._pop_screen(lambda: app.embed_shell_session(self.session))
        if self.on_done is not None:
            try:
                self.on_done(self.session)
            except Exception:
                pass

    def _terminate(self) -> None:
        """Закрыть окно и завершить сессию (кнопка «Закрыть»)."""
        session = self.session
        if not self._detach_view():
            return
        try:
            session.close()
        except Exception:
            pass
        app = self._resolve_app()
        if app is not None:
            # Панель основного экрана трогаем только после снятия модалки.
            self._pop_screen(
                lambda: app.forget_shell_session(session.session_id))
        if self.on_done is not None:
            try:
                self.on_done(session)
            except Exception:
                pass

    def _drive_pop(self, awaitable) -> None:
        """До-выполнить AwaitComplete от pop_screen в текущем цикле событий.

        Без этого снятая со стека модальная оболочка не домонтируется (её
        таймеры/очередь сообщений остаются живыми).
        """
        if awaitable is None:
            return
        try:
            asyncio.ensure_future(awaitable)
        except Exception:
            pass

    def _do_pop(self, app) -> None:
        """Синхронный pop_screen в UI-контексте (вызывается через call_from_thread)."""
        try:
            self._drive_pop(app.pop_screen())
        except Exception:
            pass

    # ------------------------------------------------------------ события

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = getattr(event.button, "id", "") or ""
        if bid == "shell_inline":
            event.stop()
            self._to_inline()
        elif bid == "shell_minimize":
            event.stop()
            self._minimize()
        elif bid == "shell_close":
            event.stop()
            self._terminate()

    # ------------------------------------------------------------ клавиши

    def on_key(self, event) -> None:
        key = getattr(event, "key", "") or ""
        char = getattr(event, "character", "") or ""

        # Ctrl+Q — свернуть окно: сессия остаётся живой, окно уходит в панель.
        if key in ("ctrl+q",):
            event.stop()
            self._minimize()
            return

        # Ctrl+C — SIGINT в сессию.
        if key in ("ctrl+c",):
            event.stop()
            self._send_ctrl_c()
            return

        # Стрелки/pgup/pgdown прокидываем в терминал, только если фокус на логе.
        target = getattr(event, "target", None)
        target_id = ""
        try:
            target_id = getattr(target, "id", "") or ""
        except Exception:
            pass

        if target_id == "shell_log":
            seq = self.session.KEY_SEQUENCES.get(key)
            if seq is None and char:
                seq = char.encode("utf-8", "ignore")
            if seq:
                event.stop()
                self.session.send_bytes(seq)
                return

    def on_unmount(self) -> None:
        if self._on_chunk is not None:
            self.session.unsubscribe(self._on_chunk)
            self._on_chunk = None


class ShellInline(Vertical):
    """Встроенная панель терминала в основном экране (верхняя часть вывода).

    Это режим по умолчанию при запуске shell из агента: панель занимает верх
    колонки вывода, а чат со стримом модели продолжается снизу. Кнопка
    «Развернуть» открывает обычное модальное окно (ShellScreen), «Свернуть»
    убирает панель (сессия уходит в панель свёрнутых), «Закрыть» завершает
    сессию.

    Панель — ещё один наблюдатель той же `ShellSession`: подписка на сырой
    вывод, ввод уходит прямо в PTY, сама сессия живёт независимо от виджета.
    """

    DEFAULT_CSS = """
    ShellInline { height: 1fr; }
    """

    BINDINGS = []

    def __init__(self, session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._on_chunk = None
        self._view_closed = False
        self._tick_timer = None
        self._spin = 0
        self._done_written = False
        self._cmd_shown = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ UI

    def compose(self) -> ComposeResult:
        yield Static(_terminal_title(self.session, 0), id="inline_shell_title")
        yield Static("", id="inline_shell_cmd", markup=False)
        yield RichLog(id="inline_shell_log", markup=False, highlight=False,
                      wrap=False, auto_scroll=True, min_width=40)
        yield Static("[dim]Enter — отправить · Ctrl+C — прервать · Ctrl+Q — свернуть · "
                     "клик по заголовку — команда[/dim]",
                     id="inline_shell_hint")
        yield Input(placeholder="ввод в терминал...", id="inline_shell_input")
        with Horizontal(id="inline_shell_buttons"):
            yield Button("Развернуть", id="inline_shell_expand", variant="primary")
            yield Button("Свернуть", id="inline_shell_minimize", variant="default")
            yield Button("Закрыть", id="inline_shell_close", variant="error")

    def on_mount(self) -> None:
        self._on_chunk = self._handle_chunk
        self.session.subscribe(self._on_chunk)
        try:
            log = self.query_one("#inline_shell_log", RichLog)
            tail = self.session.get_raw_tail(max_bytes=64 * 1024)
            if tail:
                log.write(Text.from_ansi(tail.decode("utf-8", "ignore")))
        except Exception:
            pass
        try:
            self.query_one("#inline_shell_input", Input).focus()
        except Exception:
            pass
        self._tick_timer = self.set_interval(0.15, self._tick_state)

    def set_session(self, session) -> None:
        """Переключить уже смонтированную панель на другую сессию.

        Переиспользование виджета вместо remove+mount: уборка старого виджета
        в Textual асинхронна, и вновь смонтированная панель на кадр перекрывалась
        бы с исчезающей (кнопки старой ловили клик / уезжали за границу).
        """
        old = getattr(self, "session", None)
        if old is not None and old is not session:
            try:
                self.session.unsubscribe(self._on_chunk)
            except Exception:
                pass
        self.session = session
        self._view_closed = False
        self._done_written = False
        self._on_chunk = self._handle_chunk
        try:
            session.subscribe(self._on_chunk)
        except Exception:
            pass
        # Виджет могли «спрятать» (detach остановил таймер) — перезапускаем его.
        try:
            if self._tick_timer is None:
                self._tick_timer = self.set_interval(0.15, self._tick_state)
        except Exception:
            pass
        try:
            log = self.query_one("#inline_shell_log", RichLog)
            log.clear()
            tail = session.get_raw_tail(max_bytes=64 * 1024)
            if tail:
                log.write(Text.from_ansi(tail.decode("utf-8", "ignore")))
        except Exception:
            pass
        self._tick_state()
        try:
            self.query_one("#inline_shell_input", Input).focus()
        except Exception:
            pass

    def _tick_state(self) -> None:
        if self._view_closed:
            return
        try:
            title = self.query_one("#inline_shell_title", Static)
        except Exception:
            return
        self._spin += 1
        title.update(_terminal_title(self.session, self._spin))
        # Один раз дописываем в лог явный маркер завершения.
        if not self._done_written and _is_finished(self.session):
            self._done_written = True
            try:
                self.query_one("#inline_shell_log", RichLog).write(
                    _terminal_done_text(self.session))
            except Exception:
                pass

    # ---------------------------------------------------- команда целиком

    def on_click(self, event) -> None:
        """Клик по заголовку — показать/скрыть развёрнутую команду."""
        if getattr(getattr(event, "widget", None), "id", "") == "inline_shell_title":
            event.stop()
            self._toggle_cmd()

    def _toggle_cmd(self) -> None:
        try:
            cmd_w = self.query_one("#inline_shell_cmd", Static)
        except Exception:
            return
        self._cmd_shown = not self._cmd_shown
        if self._cmd_shown:
            raw = getattr(self.session, "command", "") or getattr(self.session, "name", "")
            try:
                cmd_w.update(format_shell_command(raw))
            except Exception:
                pass
        try:
            if self._cmd_shown:
                cmd_w.add_class("show")
            else:
                cmd_w.remove_class("show")
        except Exception:
            pass

    # -------------------------------------------------------------- вывод

    def _app(self):
        """Живое приложение: сначала глобальный реестр, затем self.app."""
        try:
            from core.shell_session import TextualAppRegistry
            app = TextualAppRegistry.get_app()
            if app is not None:
                return app
        except Exception:
            pass
        try:
            return self.app
        except Exception:
            return None

    def _handle_chunk(self, chunk: bytes) -> None:
        """Колбэк из потока-ридера PTY — DOM трогаем только через UI-поток."""
        if self._view_closed or not chunk:
            return
        app = self._app()
        if app is not None:
            try:
                app.call_from_thread(self._write_chunk, chunk)
                return
            except Exception:
                pass
        try:
            self._write_chunk(chunk)
        except Exception:
            pass

    def _write_chunk(self, chunk: bytes) -> None:
        try:
            log = self.query_one("#inline_shell_log", RichLog)
        except Exception:
            return
        try:
            log.write(Text.from_ansi(chunk.decode("utf-8", "ignore")))
        except Exception:
            try:
                log.write(chunk.decode("utf-8", "ignore"))
            except Exception:
                pass

    # -------------------------------------------------------------- ввод

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value
        event.input.value = ""
        self.session.send_input(text)

    # ----------------------------------------------------------- закрытие

    def detach(self) -> bool:
        """Отписать панель от PTY и остановить таймер (идемпотентно)."""
        with self._lock:
            if self._view_closed:
                return False
            self._view_closed = True
        if self._tick_timer is not None:
            try:
                self._tick_timer.stop()
            except Exception:
                pass
            self._tick_timer = None
        if self._on_chunk is not None:
            self.session.unsubscribe(self._on_chunk)
            self._on_chunk = None
        return True

    def _expand(self) -> None:
        """Развернуть терминал в модальное окно на весь экран."""
        if not self.detach():
            return
        app = self._app()
        if app is not None:
            try:
                app.expand_shell_session(self.session)
            except Exception:
                pass

    def _minimize(self) -> None:
        """Убрать панель, оставив сессию в панели свёрнутых терминалов."""
        if not self.detach():
            return
        app = self._app()
        if app is not None:
            try:
                app.minimize_shell_session(self.session)
            except Exception:
                pass

    def _terminate(self) -> None:
        """Убрать панель и завершить сессию."""
        session = self.session
        if not self.detach():
            return
        try:
            session.close()
        except Exception:
            pass
        app = self._app()
        if app is not None:
            try:
                app.forget_shell_session(session.session_id)
            except Exception:
                pass

    # ------------------------------------------------------------ события

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = getattr(event.button, "id", "") or ""
        if bid == "inline_shell_expand":
            event.stop()
            self._expand()
        elif bid == "inline_shell_minimize":
            event.stop()
            self._minimize()
        elif bid == "inline_shell_close":
            event.stop()
            self._terminate()

    def on_key(self, event) -> None:
        key = getattr(event, "key", "") or ""
        char = getattr(event, "character", "") or ""

        # Ctrl+Q — убрать панель (сессия остаётся живой).
        if key == "ctrl+q":
            event.stop()
            self._minimize()
            return

        # Ctrl+C — SIGINT в сессию.
        if key == "ctrl+c":
            event.stop()
            self.session.send_key("ctrl-c")
            return

        # Стрелки/pgup/pgdown прокидываем в терминал, если фокус на логе.
        target = getattr(event, "target", None)
        target_id = ""
        try:
            target_id = getattr(target, "id", "") or ""
        except Exception:
            pass
        if target_id == "inline_shell_log":
            seq = self.session.KEY_SEQUENCES.get(key)
            if seq is None and char:
                seq = char.encode("utf-8", "ignore")
            if seq:
                event.stop()
                self.session.send_bytes(seq)
                return

    def on_unmount(self) -> None:
        if self._on_chunk is not None:
            self.session.unsubscribe(self._on_chunk)
            self._on_chunk = None
