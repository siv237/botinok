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
import threading
from typing import Optional, Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static
from textual.widgets import RichLog

from rich.text import Text


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
        self._closed = False
        self._tick_timer = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ UI

    def compose(self) -> ComposeResult:
        s = self.session
        title = f" shell: {s.name} "
        if s.cwd:
            title += f"| cwd: {s.cwd} "
        with Vertical(id="shell_dialog"):
            yield Static(title, id="shell_title")
            yield RichLog(id="shell_log", markup=False, highlight=False,
                          wrap=False, auto_scroll=True, min_width=60)
            yield Static("[dim]Enter — отправить · Ctrl+Q — свернуть · Ctrl+C — прервать[/dim]",
                         id="shell_hint")
            yield Input(placeholder="ввод в терминал...", id="shell_input")
            with Horizontal(id="shell_buttons"):
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
        # Периодическая проверка состояния сессии (чтобы показать «завершено»).
        self._tick_timer = self.set_interval(0.5, self._tick_state)

    def _tick_state(self) -> None:
        if self._closed:
            return
        try:
            title = self.query_one("#shell_title", Static)
        except Exception:
            return
        s = self.session
        rc = s.returncode
        if rc is not None:
            state = f"завершён (rc={rc})"
        elif s.is_running():
            state = "выполняется"
        else:
            state = "остановлен"
        title.update(f" shell: {s.name} | cwd: {s.cwd} | {state} | elapsed {s.elapsed:.1f}s ")

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
        if self._closed or not chunk:
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

    def _detach(self) -> bool:
        """Отписать экран от PTY и снять со стека, НЕ трогая сессию.

        Возвращает False, если экран уже был отсоединён (идемпотентность).
        """
        with self._lock:
            if self._closed:
                return False
            self._closed = True
        if self._tick_timer is not None:
            try:
                self._tick_timer.stop()
            except Exception:
                pass
            self._tick_timer = None
        if self._on_chunk is not None:
            self.session.unsubscribe(self._on_chunk)
            self._on_chunk = None
        app = self._resolve_app()
        popped = False
        # Прямой путь — вызываемся из UI-потока (кнопка/Ctrl+Q).
        try:
            self._drive_pop(self.app.pop_screen())
            popped = True
        except Exception:
            popped = False
        # Фолбэк: если инициировано из рабочего потока — через реестр.
        if not popped and app is not None:
            try:
                app.call_from_thread(lambda: self._do_pop(app))
                popped = True
            except Exception:
                popped = False
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
        """Спрятать окно и показать сессию в панели свёрнутых терминалов."""
        if not self._detach():
            return
        app = self._resolve_app()
        if app is not None:
            try:
                app.minimize_shell_session(self.session)
            except Exception:
                pass

    def _terminate(self) -> None:
        """Закрыть окно и завершить сессию (кнопка «Закрыть»)."""
        session = self.session
        if not self._detach():
            return
        try:
            session.close()
        except Exception:
            pass
        app = self._resolve_app()
        if app is not None:
            try:
                app.forget_shell_session(session.session_id)
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
        if bid == "shell_minimize":
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
