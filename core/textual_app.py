"""
Textual приложение для Botinok — стриминг в Static, спойлеры Collapsible в общем потоке.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (Input, Static, Collapsible, OptionList, Button,
                             Markdown, ProgressBar, TextArea)
from textual.widgets.option_list import Option
from textual.containers import Vertical, Horizontal, VerticalScroll
# rich.text.Text используется только как renderable для ANSI-вывода (логотип,
# лог терминала) — Rich является внутренним движком Textual. Панели/таблицы/
# прогресс/разметка переведены на нативные виджеты Textual.
from rich.text import Text
from typing import Optional, Callable, List
import json
import os
import re
import time
import threading
from datetime import datetime
from core.text_width import normalize_cells, cell_truncate
from core.shell_screen import format_shell_command

SPOILER_PREVIEW = 80
# Для прилипания «вниз» требуется буквальная позиция в самом низу (допуск 1px),
# иначе любой прокрут вверх колесом будет неправильно считаться «я всё ещё внизу»
# и автопрокрутка вернёт к выводу, мешая чтению.
SCROLL_BOTTOM_EPS = 1


class ConfirmationScreen(ModalScreen):
    """Модальный экран согласия на опасное действие.

    Заменяет ручной ввод 'y': пользователь выбирает действие из списка
    (OptionList) или нажимает горячие клавиши y/n/esc.
    """

    BINDINGS = []  # обрабатываем клавиши вручную через on_key

    def __init__(self, tool_name: str, args_display: str, warn_text: str = "",
                 on_resolve: Optional[Callable] = None, **kwargs):
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.args_display = args_display
        self.warn_text = warn_text
        self.on_resolve = on_resolve
        self._reason_mode = False
        self._body: Optional[Static] = None
        self._options: Optional[OptionList] = None

    def _esc(self, text: str) -> str:
        return str(text or "").replace("[", r"\[")

    def compose(self) -> ComposeResult:
        warn = f"{self._esc(self.warn_text)}\n" if self.warn_text else ""
        self._body = Static(
            f"[bold red]⚠️  ПОДТВЕРДИТЕ ОПАСНОЕ ДЕЙСТВИЕ[/bold red]\n"
            f"[bold yellow]Инструмент:[/bold yellow] {self._esc(self.tool_name)}\n"
            f"[bold yellow]Аргументы:[/bold yellow] {self._esc(self.args_display)}\n"
            f"{warn}"
            f"[dim]y — да · n/esc — нет · ↑↓ — выбор · Enter — подтвердить[/dim]",
            id="confirm_body")
        yield self._body
        self._options = OptionList(
            Option("✅ Да, выполнить", id="yes"),
            Option("❌ Нет, отменить", id="no"),
            Option("✏️  Отменить с причиной", id="no_reason"),
            id="confirm_options")
        yield self._options

    def on_mount(self) -> None:
        if self._options:
            self._options.focus()

    def _resolve(self, choice: str, reason: str = "") -> None:
        confirmed = (choice == "yes")
        final_reason = reason if (choice == "no_reason" and reason) else ""
        try:
            if self.on_resolve:
                self.on_resolve(confirmed, final_reason)
        finally:
            self.app.pop_screen()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt_id = getattr(event.option, "id", "") or ""
        if opt_id == "no_reason":
            # Переходим в режим ввода причины: показываем мини-инпут.
            self._reason_mode = True
            if self._body is not None:
                self._body.update(
                    getattr(self._body, "content", "")
                    + "\n[bold cyan]Причина отказа (Enter — отправить, esc — просто отменить):[/bold cyan]")
            reason_input = Input(placeholder="причина отказа...", id="reason_input")
            self.mount(reason_input)
            reason_input.focus()
        else:
            self._resolve(opt_id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._reason_mode:
            return
        reason = event.value.strip()
        self._resolve("no_reason", reason or "Отменено пользователем без объяснения причин.")

    def on_key(self, event) -> None:
        if self._reason_mode:
            # В режиме ввода причины esc отменяет без причины, Enter обрабатывается on_input_submitted.
            if event.key == "escape":
                self._resolve("no")
                event.stop()
            return
        k = event.key.lower()
        if k in ("y", "д"):
            self._resolve("yes")
            event.stop()
        elif k in ("n", "escape"):
            self._resolve("no")
            event.stop()


class ConfirmInline(Vertical):
    """Встроенное в окно вывода подтверждение опасного действия.

    Не накрывает правые панели (в отличие от модального ConfirmationScreen):
    живёт в `#content` над терминалом/чатом. Логика та же: y/д — да,
    n/esc — нет, ↑↓ + Enter — выбор, «Отменить с причиной» — мини-инпут.
    """

    BINDINGS = []

    def __init__(self, tool_name: str, args_display: str, warn_text: str = "",
                 on_resolve: Optional[Callable] = None, **kwargs):
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.args_display = args_display
        self.warn_text = warn_text
        self.on_resolve = on_resolve
        self._reason_mode = False
        self._body: Optional[Static] = None
        self._options: Optional[OptionList] = None
        try:
            self._args = json.loads(args_display)
        except Exception:
            self._args = None

    def _esc(self, text: str) -> str:
        return str(text or "").replace("[", r"\[")

    def _command(self) -> Optional[str]:
        if isinstance(self._args, dict):
            cmd = self._args.get("command")
            if isinstance(cmd, str) and cmd.strip():
                return cmd
        return None

    def _args_block(self) -> str:
        """Тело для показа: команда (развёрнутая) либо pretty-JSON аргументов."""
        cmd = self._command()
        if cmd is not None:
            return format_shell_command(cmd)
        if isinstance(self._args, dict):
            try:
                return json.dumps(self._args, ensure_ascii=False, indent=2)[:4000]
            except Exception:
                pass
        return str(self.args_display or "")[:4000]

    def compose(self) -> ComposeResult:
        warn = f"{self._esc(self.warn_text)}\n" if self.warn_text else ""
        has_cmd = self._command() is not None
        label = "Команда:" if has_cmd else "Аргументы:"
        self._body = Static(
            f"[bold red]⚠️  ПОДТВЕРДИТЕ ОПАСНОЕ ДЕЙСТВИЕ[/bold red]\n"
            f"[bold yellow]Инструмент:[/bold yellow] {self._esc(self.tool_name)}\n"
            f"[bold yellow]{label}[/bold yellow]\n"
            f"{warn}"
            f"[dim]y — да · n/esc — нет · ↑↓ — выбор · Enter — подтвердить[/dim]",
            id="inline_confirm_body")
        yield self._body
        # Развёрнутая команда/аргументы — в прокручиваемом блоке, чтобы
        # длинную команду было удобно читать глазами прямо в подтверждении.
        yield VerticalScroll(
            Static(self._args_block(), markup=False, id="inline_confirm_cmd"),
            id="inline_confirm_cmd_scroll")
        self._options = OptionList(
            Option("✅ Да, выполнить", id="yes"),
            Option("❌ Нет, отменить", id="no"),
            Option("✏️  Отменить с причиной", id="no_reason"),
            id="inline_confirm_options")
        yield self._options

    def on_mount(self) -> None:
        if self._options:
            self._options.focus()

    def _resolve(self, choice: str, reason: str = "") -> None:
        confirmed = (choice == "yes")
        final_reason = reason if (choice == "no_reason" and reason) else ""
        try:
            if self.on_resolve:
                self.on_resolve(confirmed, final_reason)
        finally:
            self._hide()

    def _hide(self) -> None:
        try:
            app = self.app
        except Exception:
            app = None
        if app is not None:
            try:
                app.hide_inline_confirmation()
            except Exception:
                pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt_id = getattr(event.option, "id", "") or ""
        if opt_id == "no_reason":
            self._reason_mode = True
            if self._body is not None:
                self._body.update(
                    getattr(self._body, "content", "")
                    + "\n[bold cyan]Причина отказа (Enter — отправить, esc — просто отменить):[/bold cyan]")
            reason_input = Input(placeholder="причина отказа...", id="inline_confirm_reason")
            self.mount(reason_input)
            reason_input.focus()
        else:
            self._resolve(opt_id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._reason_mode:
            return
        reason = event.value.strip()
        self._resolve("no_reason", reason or "Отменено пользователем без объяснения причин.")

    def on_key(self, event) -> None:
        if self._reason_mode:
            if event.key == "escape":
                self._resolve("no")
                event.stop()
            return
        k = event.key.lower()
        if k in ("y", "д"):
            self._resolve("yes")
            event.stop()
        elif k in ("n", "escape"):
            self._resolve("no")
            event.stop()


class Composer(TextArea):
    """Многострочный композер ввода.

    Enter — отправка, Shift+Enter / Ctrl+J — новая строка, Esc — очистить,
    Alt+↑/↓ — история. Вставка из буфера (bracketed paste) вставляет текст
    целиком и НЕ отправляет; дополнительно есть защита от «всплеска» ввода
    на терминалах без bracketed paste (Enter внутри вставки становится
    переводом строки, а не отправкой).
    """

    BINDINGS = [
        Binding("alt+up", "history_prev", "Предыдущий вопрос", show=False),
        Binding("alt+down", "history_next", "Следующий вопрос", show=False),
    ]

    class Submitted(Message):
        """Пользователь отправил ввод (Enter)."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paste_until = 0.0
        self._prev_len = 0
        self._last_change = 0.0

    async def _on_key(self, event) -> None:
        key = getattr(event, "key", "") or ""
        if key == "enter":
            event.stop()
            event.prevent_default()
            if time.time() < self._paste_until:
                # Похоже на вставку из буфера — не отправляем.
                self.insert("\n")
            else:
                self.action_submit()
            return
        if key in ("shift+enter", "ctrl+j"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        if key == "escape":
            event.stop()
            event.prevent_default()
            self.text = ""
            return
        await super()._on_key(event)

    def action_submit(self) -> None:
        text = (self.text or "").strip()
        if text:
            self.post_message(self.Submitted(text))

    def action_history_prev(self) -> None:
        app = self.app
        if hasattr(app, "_composer_history"):
            app._composer_history(self, -1)

    def action_history_next(self) -> None:
        app = self.app
        if hasattr(app, "_composer_history"):
            app._composer_history(self, +1)


class BotinokTextualApp(App):
    """Textual приложение для Botinok."""

    CSS = """
    Screen { layout: vertical; }
    #header { height: 1; min-height: 1; max-height: 1; padding: 0; margin: 0;
              content-align: center middle; background: #0055aa; color: white; text-style: bold; }
    #header.dangerous { background: red; color: white; }
    #header.proofreader { background: yellow; color: black; }
    #main { height: 1fr; }
    #content { width: 2fr; height: 1fr; padding: 0; }
    #diag { height: auto; width: 1fr; background: transparent; border: none; padding: 0; }
    #diag CollapsibleTitle { width: 1fr; padding: 0; color: cyan; }
    #diag_scroll { max-height: 14; }
    #diag_list { height: auto; }
    #diag_list Collapsible { width: 1fr; height: auto; background: transparent;
                             border: none; padding: 0; }
    #diag_list CollapsibleTitle { padding: 0; width: 1fr; }
    #inline_confirm { height: auto; max-height: 60%; display: none;
                      border: solid red; padding: 0 1; background: $surface; }
    #inline_confirm.active { display: block; }
    #inline_confirm ConfirmInline { height: auto; }
    #inline_confirm_body { height: auto; padding: 0 1; }
    #inline_confirm_cmd_scroll { height: auto; max-height: 12; overflow-y: auto; }
    #inline_confirm_cmd { height: auto; background: #0f0f0f; color: #d0d0d0; padding: 0 1; }
    #inline_confirm_options { height: auto; max-height: 10; border: none;
                              padding: 0; background: transparent; }
    #inline_confirm_options:focus { border: none; }
    #inline_confirm_reason { height: 3; }
    /* Запасной модальный вариант: без вложенной рамки OptionList. */
    #confirm_options { border: none; padding: 0; background: transparent; }
    #inline_shell { height: 50%; display: none; border: solid cyan; padding: 0; }
    #inline_shell.active { display: block; }
    #inline_shell ShellInline { height: 1fr; }
    #inline_shell_title { height: 1; background: cyan; color: black;
                          text-style: bold; padding: 0 1; }
    #inline_shell_cmd, #shell_cmd { height: auto; max-height: 40%; display: none;
                                    background: #0f0f0f; color: #d0d0d0;
                                    padding: 0 1; border: none; }
    #inline_shell_cmd.show, #shell_cmd.show { display: block; }
    #inline_shell_log { height: 1fr; border: none; padding: 0 1; background: #0c0c0c; }
    #inline_shell_hint { height: 1; color: $text-muted; padding: 0 1; }
    #inline_shell_input { height: 3; }
    #inline_shell_buttons { height: 3; align: right middle; }
    #inline_shell_buttons Button { min-width: 12; height: 3; margin: 0 1; }
    #chat { height: 1fr; border: solid green; padding: 0 1; overflow-y: auto; }
    #right { width: 1fr; }
    #shells { height: auto; max-height: 50%; display: none; border: solid cyan; padding: 0; }
    #shells.has-items { display: block; }
    #shells_title { height: 1; color: cyan; text-style: bold; padding: 0 1; }
    #shells_active { height: 1; padding: 0 1; color: $success; }
    #shells Horizontal { height: 1; }
    #shells Button { height: 1; min-height: 1; min-width: 0; margin: 0; padding: 0 1;
                     border: none; text-align: left; text-overflow: ellipsis;
                     content-align: left middle; }
    #shells Button.restore { width: 1fr; }
    #shells Static.stamp { width: auto; height: 1; padding: 0 1; color: $text-muted; }
    #shells Button.kill { width: 3; min-width: 3; text-align: center;
                          content-align: center middle; }
    #stats { height: 1fr; border: round yellow; border-title-color: yellow;
             border-title-style: bold; padding: 0 1; }
    #stats_rows { height: 1fr; }
    #ctx_bar { height: 1; }
    #ctx_bar.low .bar--bar { color: green; }
    #ctx_bar.mid .bar--bar { color: yellow; }
    #ctx_bar.high .bar--bar { color: red; }
    #tools { height: 1fr; border: round cyan; border-title-color: cyan;
             border-title-style: bold; }
    #tools_list { height: 1fr; overflow-y: auto; }
    #tools_list Collapsible { width: 1fr; height: auto; background: transparent;
                              border: none; padding: 0; }
    #tools_list CollapsibleTitle { padding: 0; width: 1fr; color: $text; }
    #footer { height: 3; border: round cyan; border-title-color: cyan; padding: 0 1; }
    Input { height: 3; }
    #input { height: 3; min-height: 3; max-height: 10; }
    Collapsible { width: 1fr; height: auto; background: transparent; border: none; padding: 0; }
    CollapsibleTitle { color: $text-muted; padding: 0 1; width: 1fr; }
    """

    def __init__(self, session_path: str = "", on_submit: Optional[Callable] = None,
                 on_slash_command: Optional[Callable] = None, version: str = "",
                 initial_prompt: str = "", **kwargs):
        super().__init__(**kwargs)
        self.session_path = session_path
        self.version = version
        self.initial_prompt = initial_prompt
        self.on_submit = on_submit
        self.on_slash_command = on_slash_command
        self.chat: Optional[Vertical] = None
        self.stream_static: Optional[Static] = None
        self.stats_rows: Optional[Static] = None
        self.ctx_bar: Optional[ProgressBar] = None
        self.tools_list: Optional[Vertical] = None
        self.header_display: Optional[Static] = None
        self.diag: Optional[Collapsible] = None
        self.diag_list: Optional[Vertical] = None
        self.diag_scroll: Optional[VerticalScroll] = None
        self.diag_entries: List[dict] = []
        self._diag_widgets: dict = {}
        self._diag_id_to_key: dict = {}
        self._diag_last_refresh = 0.0
        self.model_name = ""
        self.dangerous_mode = False
        self.is_proofreader = False
        self.current_prompt = ""
        self.stats_data = {
            "status": "Ready", "elapsed": 0.0, "no_chunks": 0.0,
            "ttft": "...", "thinking_tokens": 0, "response_tokens": 0,
            "stream_tool_tokens": 0, "final_tool_tokens": 0, "tps": 0.0,
            "vram": "...", "session_ctx": 0, "session_ctx_max": 8192,
            "last_req_ctx": 0, "last_req_ctx_max": 8192,
        }
        self.active_tools: List[dict] = []
        self._tools_expanded: set = set()  # ключи раскрытых узлов Tools Activity
        self._tool_id_to_key: dict = {}
        self._tool_widgets: dict = {}
        self._tools_placeholder: Optional[Static] = None
        self._start_time = time.time()
        self._last_chunk_time = 0.0
        self._stream_content = ""
        self._stream_thinking = ""
        self._last_tool_content = ""
        self._tool_items: List[str] = []
        self.is_streaming = False
        self._stop_requested = False
        self._user_scrolled_away = False
        self._last_scroll_y: Optional[float] = None
        self._queued_inputs: List[str] = []
        self.input_widget: Optional[Composer] = None
        self._prompt_history: List[str] = []
        self._history_idx = 0
        self._confirmation_event: Optional[threading.Event] = None
        self._confirmation_result: bool = False
        # Встроенное подтверждение опасного действия (не модалка).
        self.inline_confirm_container: Optional[Vertical] = None
        self.inline_confirm_widget = None
        self._stats_dirty = True
        self._tools_dirty = True
        self._footer_dirty = True
        self._last_open_spoiler: Optional[Collapsible] = None
        # Свёрнутые окна терминала: session_id -> окно «висит» на панели.
        self.minimized_shells: set = set()
        self.shells_display: Optional[VerticalScroll] = None
        self._shells_sig: Optional[str] = None
        self._shell_widgets: dict = {}       # session_id -> Horizontal-строка в панели
        self._shells_title_widget = None
        self._shells_active_widget = None
        # Встроенная (inline) панель терминала над чатом — режим по умолчанию.
        # Виджет создаётся один раз и переиспользуется; «свёрнут» — скрыт
        # (контейнер без класса active), а не удалён из DOM.
        self.inline_shell_container: Optional[Vertical] = None
        self.inline_shell_widget = None
        self.inline_shell_active = False

    def _spoiler_title(self, label: str, text: str) -> str:
        ts = datetime.now().strftime("%H:%M:%S")
        max_preview = SPOILER_PREVIEW
        try:
            # Ограничиваем превью по ширине чата, чтобы заголовок не переносился.
            chat_width = self.chat.size.width if self.chat else 0
            if chat_width:
                max_preview = max(20, chat_width - len(label) - len(ts) - 14)
        except Exception:
            pass
        preview = text[:max_preview].replace("\n", " ")
        if len(text) > max_preview:
            preview += "..."
        return f"{label}: {preview}  {ts}"

    def _mount_spoiler(self, title: str, *content_widgets, collapsed: bool = False, before=None):
        if self._last_open_spoiler:
            try:
                self._last_open_spoiler.collapsed = True
            except Exception:
                pass
        c = Collapsible(*content_widgets, title=title, collapsed=collapsed, collapsed_symbol="", expanded_symbol="")
        self._last_open_spoiler = c
        if before is not None:
            try:
                self.chat.mount(c, before=before)
            except Exception:
                self.chat.mount(c)
        else:
            self.chat.mount(c)
        self._auto_scroll_chat(animate=False)
        self._keep_focus()

    def _keep_focus(self) -> None:
        try:
            # Не отбираем фокус у встроенного терминала: пользователь может
            # печатать в него, пока модель стримит ответ в чат ниже.
            if self.inline_shell_active and self.inline_shell_widget is not None:
                node = self.focused
                while node is not None:
                    if node is self.inline_shell_widget:
                        return
                    node = getattr(node, "parent", None)
            self.set_focus(self.query_one("#input", Composer))
        except Exception:
            pass

    def _is_at_bottom(self) -> bool:
        try:
            return self.chat.scroll_y >= (self.chat.max_scroll_y - SCROLL_BOTTOM_EPS)
        except Exception:
            return True

    def _event_inside_chat(self, event) -> bool:
        node = getattr(event, "target", None)
        while node is not None:
            if node is self.chat:
                return True
            node = getattr(node, "parent", None)
        return False

    def on_mouse_scroll(self, event) -> None:
        """Любое колесо мыши над чатом — отключаем прилипание к низу."""
        if self._event_inside_chat(event):
            self._user_scrolled_away = True

    def _auto_scroll_chat(self, animate: bool = False) -> None:
        # Если пользователь листает сам — никогда не трогаем прокрутку.
        if self._user_scrolled_away:
            return
        if self._is_at_bottom():
            self.chat.scroll_end(animate=animate)

    def _add_static(self, content, markup=True):
        # Единая точка вставки в чат: нормализуем ширину для строк, чтобы
        # вариационные селекторы/ZWJ/табы не сдвигали границы панелей.
        if isinstance(content, str):
            content = normalize_cells(content)
        s = Static(content, markup=markup)
        self.chat.mount(s)
        self._keep_focus()
        return s

    def compose(self) -> ComposeResult:
        self.header_display = Static("", id="header")
        yield self.header_display
        with Horizontal(id="main"):
            self.content_container = Vertical(id="content")
            with self.content_container:
                self.diag_list = Vertical(id="diag_list")
                self.diag_scroll = VerticalScroll(self.diag_list, id="diag_scroll")
                self.diag = Collapsible(self.diag_scroll, title="Prompt:", collapsed=True, id="diag")
                yield self.diag
                # Встроенное подтверждение опасного действия (не модалка —
                # чтобы не накрывать правые панели).
                self.inline_confirm_container = Vertical(id="inline_confirm")
                yield self.inline_confirm_container
                # Встроенный терминал: занимает верхнюю часть колонки вывода,
                # чат со стримом модели остаётся под ним.
                self.inline_shell_container = Vertical(id="inline_shell")
                yield self.inline_shell_container
                self.chat = Vertical(id="chat")
                yield self.chat
            with Vertical(id="right"):
                self.shells_display = VerticalScroll(id="shells")
                yield self.shells_display
                with Vertical(id="stats"):
                    self.stats_rows = Static("", id="stats_rows")
                    yield self.stats_rows
                    self.ctx_bar = ProgressBar(total=100, show_eta=False, id="ctx_bar")
                    yield self.ctx_bar
                with Vertical(id="tools"):
                    self.tools_list = Vertical(id="tools_list")
                    yield self.tools_list
        self.input_widget = Composer(
            id="input",
            placeholder="Введите ваш вопрос (Enter — отправить, Shift+Enter — новая строка)...",
        )
        yield self.input_widget

    def on_mount(self) -> None:
        self.load_history()
        # Заголовки панелей и колонки таблицы инструментов — нативные средства Textual.
        try:
            self.query_one("#stats").border_title = "Performance"
            self.query_one("#tools").border_title = "Tools Activity"
        except Exception:
            pass
        try:
            self.set_focus(self.query_one("#input", Composer))
        except Exception:
            pass
        if hasattr(self, '_vram_prep_fn') and self._vram_prep_fn:
            t = threading.Thread(target=self._vram_prep_fn, daemon=True)
            t.start()
        self.set_interval(0.1, self._tick_stats)
        self._stats_dirty = True
        self._tools_dirty = True
        self._footer_dirty = True
        self.update_stats_display()
        # Стартовый промпт из CLI (--prompt / позиционный аргумент): отправляем
        # автоматически, когда приложение готово.
        if self.initial_prompt:
            self.call_after_refresh(self._submit_initial_prompt)

    def on_resize(self, event) -> None:
        # Пересчитать обрезку заголовка Prompt при изменении размеров окна.
        self._footer_dirty = True
        self.update_stats_display()

    def _submit_initial_prompt(self) -> None:
        prompt = (self.initial_prompt or "").strip()
        self.initial_prompt = ""
        if not prompt or not self.on_submit:
            return
        self.current_prompt = prompt
        self._footer_dirty = True
        self._submit_text(prompt)

    def set_model_info(self, model: str, dangerous: bool = False, proofreader: bool = False):
        self.model_name = model
        self.dangerous_mode = dangerous
        self.is_proofreader = proofreader
        self._stats_dirty = True
        self._tools_dirty = True
        self._footer_dirty = True
        self.update_stats_display()

    def report_chunk(self) -> None:
        self._last_chunk_time = time.time()

    def _tick_stats(self) -> None:
        now = time.time()
        # Раз в 30 секунд обновляем относительное время у вопросов в Diagnostic Log.
        if now - self._diag_last_refresh > 30:
            self._footer_dirty = True
        active = ("Generating...", "Connecting...", "Processing tool calls...", "Checking Memory...")
        if self.stats_data["status"] in active:
            self.stats_data["elapsed"] = now - self._start_time
            self._stats_dirty = True
        if self._last_chunk_time > 0:
            new_val = now - self._last_chunk_time
            if abs(new_val - self.stats_data["no_chunks"]) > 0.1:
                self.stats_data["no_chunks"] = new_val
                self._stats_dirty = True
        if self.chat:
            # Отслеживаем изменение позиции: если scroll_y уменьшился — это
            # намеренный скролл вверх (колесо/клавиши), сразу отключаем прилипание.
            cur_y = self.chat.scroll_y or 0
            if self._last_scroll_y is not None and cur_y < self._last_scroll_y - 0.5:
                self._user_scrolled_away = True
            self._last_scroll_y = cur_y

            if self._user_scrolled_away:
                # Пользователь листает сам: не прилипаем, пока он явно не
                # докрутит до самого низа (тогда прилипание вернётся).
                if self._is_at_bottom():
                    self._user_scrolled_away = False
            else:
                self.chat.scroll_end(animate=False)
        if self._stats_dirty or self._tools_dirty or self._footer_dirty:
            self.update_stats_display()
        self._update_shells_panel()

    # ------------------------------------------------ встроенный терминал

    def _shell_sessions_minimized(self) -> list:
        """Живые PTY-сессии, окна которых свёрнуты (для панели на основном экране)."""
        try:
            from core.shell_session import ShellSessionRegistry
            reg = ShellSessionRegistry.instance()
        except Exception:
            return []
        sessions = []
        for sid in list(self.minimized_shells):
            s = reg.get(sid)
            if s is None:
                self.minimized_shells.discard(sid)
                continue
            sessions.append(s)
        return sessions

    @staticmethod
    def _shell_clock(ts: float, with_date: bool = False) -> str:
        fmt = "%d.%m %H:%M:%S" if with_date else "%H:%M:%S"
        try:
            return time.strftime(fmt, time.localtime(ts or 0))
        except Exception:
            return "--:--:--"

    @staticmethod
    def _shell_duration(secs: float) -> str:
        secs = int(secs or 0)
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m{secs % 60:02d}s"
        return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"

    @classmethod
    def _shell_name(cls, s, prefix: str = "", limit: int = 200) -> str:
        state = "▶" if s.is_running() else "■"
        name = (getattr(s, "name", "") or "").replace("\n", " ").strip()
        if len(name) > limit:
            name = name[:limit - 1] + "…"
        return f"{prefix}{state} {name}"

    @classmethod
    def _shell_stamp(cls, s, with_date: bool = False) -> str:
        start = cls._shell_clock(getattr(s, "started_at", 0), with_date)
        try:
            secs = int(s.elapsed)
        except Exception:
            secs = 0
        return f"{start} · {cls._shell_duration(secs)}"

    @classmethod
    def _shell_row_label(cls, s, prefix: str = "") -> str:
        return f"{cls._shell_name(s, prefix)} · {cls._shell_stamp(s, with_date=True)}"

    def _active_shell_session(self):
        if not self.inline_shell_active:
            return None
        w = self.inline_shell_widget
        if w is None:
            return None
        s = getattr(w, "session", None)
        if s is None or not getattr(s, "session_id", ""):
            return None
        return s

    def _clear_shells_panel(self) -> None:
        for sid in list(self._shell_widgets):
            entry = self._shell_widgets.pop(sid)
            try:
                entry["row"].remove()
            except Exception:
                pass
        for attr in ("_shells_title_widget", "_shells_active_widget"):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.remove()
                except Exception:
                    pass
                setattr(self, attr, None)
        try:
            self.shells_display.remove_class("has-items")
        except Exception:
            pass

    def _update_shells_panel(self) -> None:
        """Обновить панель терминалов инкрементально.

        Верхняя строка — всегда активный (встроенный) терминал с тикающим
        счётчиком секунд; ниже — однострочные свёрнутые сессии с временем
        старта, длительностью и кнопкой закрытия. Полный rebuild конкурирует с
        асинхронной уборкой DOM, поэтому строки переиспользуются по session_id.
        """
        if self.shells_display is None:
            return
        active = self._active_shell_session()
        active_sid = getattr(active, "session_id", "")
        sessions = [s for s in self._shell_sessions_minimized()
                    if s.session_id != active_sid]
        sig_parts = [f"{s.session_id}:{s.is_running()}:{s.name}:{int(s.elapsed)}"
                     for s in sessions]
        if active is not None:
            sig_parts.append(
                f"active:{active_sid}:{active.is_running()}:{int(active.elapsed)}")
        sig = "|".join(sig_parts)
        if sig == self._shells_sig:
            return
        self._shells_sig = sig

        if active is None and not sessions:
            self._clear_shells_panel()
            return

        try:
            self.shells_display.add_class("has-items")
        except Exception:
            pass

        if self._shells_title_widget is None:
            self._shells_title_widget = Static(
                "[bold cyan]Терминалы[/bold cyan]", id="shells_title")
            try:
                self.shells_display.mount(self._shells_title_widget)
            except Exception:
                self._shells_title_widget = None

        if self._shells_active_widget is None:
            self._shells_active_widget = Static("", id="shells_active")
            try:
                self.shells_display.mount(self._shells_active_widget)
            except Exception:
                self._shells_active_widget = None
        if self._shells_active_widget is not None:
            try:
                if active is not None:
                    self._shells_active_widget.update(
                        "[bold]● активный[/bold] " + self._shell_row_label(active))
                else:
                    self._shells_active_widget.update("")
            except Exception:
                pass

        current = {s.session_id for s in sessions}
        for sid in list(self._shell_widgets):
            if sid not in current:
                entry = self._shell_widgets.pop(sid)
                try:
                    entry["row"].remove()
                except Exception:
                    pass

        for s in sessions:
            sid = s.session_id
            name = self._shell_name(s)
            stamp = self._shell_stamp(s)
            entry = self._shell_widgets.get(sid)
            if entry is None:
                restore = Button(name, id=f"shell_restore_{sid}",
                                 variant="primary", classes="restore")
                clock = Static(stamp, classes="stamp")
                kill = Button("✕", id=f"shell_kill_{sid}",
                              variant="error", classes="kill")
                row = Horizontal(restore, clock, kill)
                self._shell_widgets[sid] = {"row": row, "restore": restore, "clock": clock}
                try:
                    self.shells_display.mount(row)
                except Exception:
                    self._shell_widgets.pop(sid, None)
            else:
                try:
                    entry["restore"].label = name
                except Exception:
                    pass
                try:
                    entry["clock"].update(stamp)
                except Exception:
                    pass

    def _hide_inline_shell(self, session_id: str = "", minimize: bool = False) -> None:
        """Спрятать встроенную панель (виджет остаётся в DOM для переиспользования).

        Удалять виджет через remove() нельзя: уборка DOM асинхронна, и новый
        терминал, смонтированный до prune, оставлял «застрявшего» потомка —
        после этого следующий shell уже не открывался встроенно. Вместо
        удаления отписываемся от PTY и убираем класс active (контейнер display:none).

        minimize=True — дополнительно отправить сессию в панель свёрнутых.
        """
        w = self.inline_shell_widget
        if w is None:
            return
        wsid = getattr(getattr(w, "session", None), "session_id", "")
        if session_id and wsid != session_id:
            return
        try:
            w.detach()
        except Exception:
            pass
        self.inline_shell_active = False
        try:
            self.inline_shell_container.remove_class("active")
        except Exception:
            pass
        # Скрытый виджет остаётся в DOM и иначе удерживает фокус на своём Input —
        # клавиатура уходит в невидимый терминал. Возвращаем фокус в композер.
        try:
            w.query_one("#inline_shell_input", Input).blur()
        except Exception:
            pass
        self._keep_focus()
        if minimize and wsid:
            self.minimized_shells.add(wsid)
        self._shells_sig = None
        self._update_shells_panel()

    def minimize_shell_session(self, session) -> None:
        """Колбэк терминала: панель/окно свёрнуты, сессия остаётся живой."""
        sid = getattr(session, "session_id", "")
        if not sid:
            return
        self._hide_inline_shell(session_id=sid)
        self.minimized_shells.add(sid)
        self._shells_sig = None
        self._update_shells_panel()

    def forget_shell_session(self, session_id: str) -> None:
        """Колбэк терминала: панель/окно закрыты и сессия завершена."""
        self._hide_inline_shell(session_id=session_id)
        self.minimized_shells.discard(session_id)
        self._shells_sig = None
        self._update_shells_panel()

    def _minimize_open_shell_screens(self, except_session_id: str = "") -> None:
        """Свернуть все открытые окна терминала, кроме указанной сессии.

        Держим на экране только одно окно за раз: остальные уходят в панель,
        а не наслаиваются друг на друга (защита от RecursionError при рендере).
        """
        try:
            screens = list(self.screen_stack)
        except Exception:
            return
        for scr in screens:
            if type(scr).__name__ != "ShellScreen":
                continue
            sid = getattr(getattr(scr, "session", None), "session_id", "")
            if sid and sid == except_session_id:
                continue
            try:
                scr._minimize()
            except Exception:
                pass

    def embed_shell_session(self, session) -> None:
        """Показать терминал встроенным в окно вывода (над чатом) — режим по умолчанию.

        Предыдущая встроенная панель уходит в панель свёрнутых: одновременно
        встроен не более чем один терминал.
        """
        from core.shell_screen import ShellInline
        sid = getattr(session, "session_id", "")
        # Держим на виду не более одного терминала: открытые модалки с другими
        # сессиями свёртываем в панель.
        self._minimize_open_shell_screens(except_session_id=sid)
        if sid:
            self.minimized_shells.discard(sid)
        existing = self.inline_shell_widget
        if existing is not None:
            # Виджет создан один раз и переиспользуется: старая сессия уходит в
            # свёрнутые, новая занимает место без remove+mount.
            old = getattr(existing, "session", None)
            old_sid = getattr(old, "session_id", "")
            try:
                existing.set_session(session)
                self.inline_shell_active = True
                self.inline_shell_container.add_class("active")
                if old_sid and old_sid != sid:
                    self.minimized_shells.add(old_sid)
            except Exception:
                self.inline_shell_active = False
        else:
            try:
                widget = ShellInline(session)
                if self.inline_shell_container is not None:
                    self.inline_shell_container.mount(widget)
                    self.inline_shell_container.add_class("active")
                    self.inline_shell_widget = widget
                    self.inline_shell_active = True
                else:
                    self.inline_shell_widget = None
                    self.inline_shell_active = False
            except Exception:
                self.inline_shell_widget = None
                self.inline_shell_active = False
        self._shells_sig = None
        self._update_shells_panel()

    def open_shell_session(self, session) -> None:
        """Открыть терминал для сессии. По умолчанию — встроенная панель."""
        self.embed_shell_session(session)

    def expand_shell_session(self, session) -> None:
        """Развернуть терминал в модальное окно на весь экран."""
        from core.shell_screen import ShellScreen
        sid = getattr(session, "session_id", "")
        self._hide_inline_shell(session_id=sid)
        if sid:
            self.minimized_shells.discard(sid)
        self._shells_sig = None
        self._update_shells_panel()
        self._minimize_open_shell_screens(except_session_id=sid)
        self.push_screen(ShellScreen(session=session))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = getattr(event.button, "id", "") or ""
        if bid.startswith("shell_restore_"):
            event.stop()
            sid = bid[len("shell_restore_"):]
            try:
                from core.shell_session import ShellSessionRegistry
                session = ShellSessionRegistry.instance().get(sid)
            except Exception:
                session = None
            if session is None:
                self.minimized_shells.discard(sid)
                self._shells_sig = None
                self._update_shells_panel()
                return
            self.open_shell_session(session)
            return
        if bid.startswith("shell_kill_"):
            event.stop()
            sid = bid[len("shell_kill_"):]
            try:
                from core.shell_session import ShellSessionRegistry
                session = ShellSessionRegistry.instance().get(sid)
            except Exception:
                session = None
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            self.minimized_shells.discard(sid)
            self._shells_sig = None
            self._update_shells_panel()

    def _render_header_text(self) -> str:
        danger_tag = " | DANGEROUS MODE: ON" if self.dangerous_mode else ""
        agent_type = "PROOFREADER AGENT" if self.is_proofreader else "BOTINOK AGENT"
        vram = normalize_cells(self.stats_data.get("vram", "..."))
        ctx = self.stats_data.get("session_ctx_max", 8192)
        model = normalize_cells(self.model_name)
        return f"{agent_type}{danger_tag} | Model: {model} | Context: {ctx} | {vram}"

    def _update_header(self) -> None:
        if not self.header_display:
            return
        self.header_display.update(self._render_header_text())
        # Цвет шапки — CSS-классы (см. CSS).
        try:
            self.header_display.set_class(self.dangerous_mode, "dangerous")
            self.header_display.set_class(self.is_proofreader, "proofreader")
        except Exception:
            pass

    @staticmethod
    def _rel_time(ts: float) -> str:
        try:
            diff = max(0.0, time.time() - float(ts))
        except Exception:
            return ""
        if diff < 60:
            return f"{int(diff)} сек назад"
        if diff < 3600:
            return f"{int(diff / 60)} мин назад"
        if diff < 86400:
            return f"{int(diff / 3600)} ч назад"
        return f"{int(diff / 86400)} дн назад"

    @staticmethod
    def _diag_id(key: str) -> str:
        return "d_" + re.sub(r"[^0-9a-zA-Z_-]", "_", key)

    def _record_diag(self, text: str, ts: Optional[float] = None) -> None:
        text = normalize_cells(str(text)).strip()
        if not text:
            return
        if ts is None:
            ts = time.time()
        # Не плодим дубликаты при повторном рендере одного и того же запроса.
        if self.diag_entries:
            last = self.diag_entries[-1]
            if last["text"] == text and abs(ts - last["ts"]) < 3:
                return
        key = f"{ts:.3f}:{len(self.diag_entries)}"
        self.diag_entries.append({"ts": ts, "text": text, "key": key})
        self._footer_dirty = True

    def _diag_card_title(self, entry: dict) -> str:
        text = entry["text"]
        # Дата + «сколько назад» + сам вопрос, обрезанный по ширине окна.
        width = 0
        try:
            width = self.diag.size.width if self.diag else 0
        except Exception:
            width = 0
        head = ""
        try:
            head = datetime.fromtimestamp(entry["ts"]).strftime("%d.%m %H:%M")
        except Exception:
            head = "--.-- --:--"
        rel = self._rel_time(entry["ts"])
        prefix = f"{head} · {rel}  "
        budget = max(8, (width - len(prefix) - 6)) if width else 40
        return f"[dim]{prefix}[/dim][cyan]{cell_truncate(text, budget)}[/cyan]"

    def _update_diag(self) -> None:
        if self.diag is None:
            return
        # Заголовок свёрнутого блока — последний вопрос (обрезанный).
        if self.diag_entries:
            latest = self.diag_entries[-1]
            width = 0
            try:
                width = self.diag.size.width or 0
            except Exception:
                width = 0
            budget = max(10, (width - 10)) if width else 60
            try:
                self.diag.title = f"[bold cyan]Prompt:[/bold cyan] [dim]{cell_truncate(latest['text'], budget)}[/dim]"
            except Exception:
                pass
        # Карточки вопросов (создаём недоимостающие, обновляем заголовки).
        if self.diag_list is not None:
            for entry in self.diag_entries:
                key = entry["key"]
                node = self._diag_widgets.get(key)
                if node is None:
                    cid = self._diag_id(key)
                    self._diag_id_to_key[cid] = key
                    node = Collapsible(Static(normalize_cells(entry["text"])),
                                       title=self._diag_card_title(entry),
                                       collapsed=True, id=cid)
                    self._diag_widgets[key] = node
                    try:
                        self.diag_list.mount(node)
                        node.collapsed = True
                    except Exception:
                        self._diag_widgets.pop(key, None)
                        self._diag_id_to_key.pop(cid, None)
                else:
                    try:
                        node.title = self._diag_card_title(entry)
                    except Exception:
                        pass
        self._diag_last_refresh = time.time()

    def _update_stats_panel(self) -> None:
        if not self.stats_rows:
            return
        s = self.stats_data
        active_statuses = [
            "Generating...", "Waiting for tool call...", "Calling Tools...",
            "Resuming generation...", "Checking Memory...", "Unloading Models...",
            "Forced VRAM Cleanup...", "Connecting...", "Tool-mode parsing..."
        ]
        activity = ""
        if s["status"] in active_statuses or "Tool:" in s["status"]:
            sp = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            activity = f" [bold magenta]{sp[int(time.time()*5) % len(sp)]}[/bold magenta]"

        L = 14  # ширина колонки подписей (моноширинный шрифт)
        def row(label: str, value: str) -> str:
            return f"[cyan]{label:<{L}}[/cyan]{value}"
        lines = [
            row("Status:", f"[bold]{s['status']}[/bold]{activity}"),
            row("Elapsed:", f"{s['elapsed']:.1f}s"),
            row("No chunks:", f"{s['no_chunks']:.1f}s"),
            row("TTFT:", f"[bold yellow]{s['ttft']}[/bold yellow]"),
            row("Thinking:", f"[bold yellow]{s['thinking_tokens']}[/bold yellow]"),
            row("Response:", f"[bold green]{s['response_tokens']}[/bold green]"),
            row("Stream Tool:", f"[bold magenta]{s['stream_tool_tokens']}[/bold magenta]"),
            row("Final Tool:", f"[bold magenta]{s['final_tool_tokens']}[/bold magenta]"),
            row("TPS:", f"[bold green]{s['tps']:.2f}[/bold green]"),
            row("VRAM:", f"[bold yellow]{normalize_cells(s['vram'])}[/bold yellow]"),
            "",
        ]
        ctx_max = s.get("session_ctx_max", 8192)
        ctx_used = s.get("session_ctx", 0)
        ctx_pct = (ctx_used / ctx_max * 100) if ctx_max else 0
        cs = "green" if ctx_pct < 70 else "yellow" if ctx_pct < 90 else "red"
        lines.append(row("SessionCtx:", f"[{cs}]{ctx_used}/{ctx_max} ({ctx_pct:.1f}%)[/{cs}]"))
        lr_ctx = s.get("last_req_ctx", 0)
        lr_pct = (lr_ctx / ctx_max * 100) if ctx_max else 0
        lr_cs = "green" if lr_pct < 70 else "yellow" if lr_pct < 90 else "red"
        lines.append(row("LastReqCtx:", f"[{lr_cs}]{lr_ctx}/{ctx_max} ({lr_pct:.1f}%)[/{lr_cs}]"))
        lines.append("")
        lines.append("[bold cyan]Context Window Fill:[/bold cyan]")
        self.stats_rows.update("\n".join(lines))
        if self.ctx_bar:
            try:
                self.ctx_bar.progress = float(ctx_pct)
                self.ctx_bar.set_class(ctx_pct < 70, "low")
                self.ctx_bar.set_class(70 <= ctx_pct < 90, "mid")
                self.ctx_bar.set_class(ctx_pct >= 90, "high")
            except Exception:
                pass

    @staticmethod
    def _tool_key(t: dict) -> str:
        return f"{t.get('start_time', 0)}:{t.get('name', '')}"

    @staticmethod
    def _tool_id(key: str) -> str:
        return "tool_" + re.sub(r"[^0-9a-zA-Z_-]", "_", key)

    def _tool_details(self, t: dict) -> str:
        ss = "yellow" if t["status"] == "running" else "green" if t["status"] == "completed" else "red"
        sz = f"{t['size_kb']:.2f} KB" if t.get("size_kb", 0) > 0 else "..."
        started = ""
        try:
            started = datetime.fromtimestamp(float(t.get("start_time", 0))).strftime("%H:%M:%S")
        except Exception:
            started = "--:--:--"
        lines = [
            f"[bold cyan]Инструмент:[/bold cyan] {normalize_cells(t.get('name', ''))}",
            f"[bold cyan]Время:[/bold cyan] {started}  [bold cyan]Статус:[/bold cyan] [{ss}]{t['status']}[/{ss}]  [bold cyan]Размер:[/bold cyan] {sz}",
        ]
        query = normalize_cells(t.get("query", ""))
        if query:
            lines += ["", "[bold cyan]Запрос:[/bold cyan]", query]
        result = normalize_cells(t.get("result", ""))
        if result:
            lines += ["", "[bold cyan]Результат:[/bold cyan]", result]
        return "\n".join(lines)

    def _tools_signature(self) -> str:
        return "|".join(
            f"{self._tool_key(t)}:{t['status']}:{round(t.get('size_kb', 0), 3)}:{len(t.get('result', ''))}"
            for t in self.active_tools
        )

    def _update_tools_panel(self) -> None:
        if not self.tools_list:
            return
        if not self.active_tools:
            if self._tools_placeholder is None:
                self._tools_placeholder = Static("[dim]No active tools[/dim]")
                try:
                    self.tools_list.mount(self._tools_placeholder)
                except Exception:
                    self._tools_placeholder = None
            return
        if self._tools_placeholder is not None:
            try:
                self._tools_placeholder.remove()
            except Exception:
                pass
            self._tools_placeholder = None

        current = {self._tool_key(t): t for t in self.active_tools}
        # Удаляем карточки завершённых/ушедших инструментов.
        for key in list(self._tool_widgets):
            if key not in current:
                w = self._tool_widgets.pop(key)
                self._tool_id_to_key.pop(self._tool_id(key), None)
                try:
                    w.remove()
                except Exception:
                    pass
        # Создаём новые и обновляем существующие карточки (без пересоздания —
        # иначе шторм remove/mount и зависание обработки сообщений).
        for t in self.active_tools:  # старые -> новые; новые вставляем наверх
            key = self._tool_key(t)
            tid = self._tool_id(key)
            self._tool_id_to_key[tid] = key
            started = ""
            try:
                started = datetime.fromtimestamp(float(t.get("start_time", 0))).strftime("%H:%M:%S")
            except Exception:
                started = "--:--:--"
            ss = "yellow" if t["status"] == "running" else "green" if t["status"] == "completed" else "red"
            title = (f"[dim]{started}[/dim]  [cyan]{normalize_cells(t.get('name', ''))}[/cyan]  "
                     f"[{ss}]{t['status']}[/{ss}]")
            body = self._tool_details(t)
            widget = self._tool_widgets.get(key)
            if widget is None:
                # Новые инструменты ВСЕГДА свёрнуты.
                self._tools_expanded.discard(key)
                widget = Collapsible(Static(body), title=title,
                                     collapsed=True, id=tid)
                self._tool_widgets[key] = widget
                try:
                    self.tools_list.mount(widget, before=0)
                    widget.collapsed = True
                except Exception:
                    self._tool_widgets.pop(key, None)
                    continue
            else:
                try:
                    widget.title = title
                except Exception:
                    pass
                try:
                    # ВАЖНО: CollapsibleTitle — тоже Static, поэтому ищем тело
                    # строго внутри Contents, иначе апдейт перезапишет заголовок.
                    cont = widget.query_one(Collapsible.Contents)
                    cont.query_one(Static).update(body)
                except Exception:
                    pass

    def on_collapsible_toggled(self, event: Collapsible.Toggled) -> None:
        # Запоминаем, какие узлы инструментов раскрыты, чтобы не схлопывать их
        # при перерисовке панели (обновления статуса/размера).
        try:
            cid = event.collapsible.id or ""
            key = self._tool_id_to_key.get(cid)
            if key is None:
                return
            if event.collapsible.collapsed:
                self._tools_expanded.discard(key)
            else:
                self._tools_expanded.add(key)
        except Exception:
            pass

    def update_stats_display(self) -> None:
        if self.header_display:
            self._update_header()
        if self._stats_dirty:
            self._update_stats_panel()
            self._stats_dirty = False
        if self._tools_dirty:
            self._update_tools_panel()
            self._tools_dirty = False
        if self._footer_dirty:
            self._update_diag()
            self._footer_dirty = False

    _GGUF_TAG_RE = re.compile(r"(?:<\|[^\n\r]*?\|>|</?[^>\n\r]+?>)", re.IGNORECASE)
    _GGUF_QUOTE_RE = re.compile(r'<\|"|>', re.IGNORECASE)
    _KNOWN_TOOLS = {"code_editor", "shell_exec", "file_system", "web_search", "open_url",
                    "curl", "skills", "experience", "journal", "session_memory"}

    def _rich_escape(self, text: str) -> str:
        # Нормализуем ширину (табы, VS15/VS16, ZWJ, контролы), чтобы строки с
        # эмодзи/спецсимволами не «уезжали» на 1..N ячеек и не сдвигали панели.
        text = normalize_cells(text)
        return text.replace("[", r"\[")

    def load_history(self) -> None:
        history = []
        context_path = os.path.join(self.session_path, "context.json") if self.session_path else ""
        if context_path and os.path.exists(context_path):
            try:
                with open(context_path, "r", encoding="utf-8", errors="ignore") as f:
                    context = json.load(f)
                history = context.get("history", []) or []
            except Exception as e:
                self._add_static(f"[red]Ошибка загрузки истории: {e}[/red]")
        if history:
            for entry in history:
                if entry.get("role") == "user" and entry.get("content"):
                    ts = None
                    raw_ts = entry.get("timestamp")
                    if raw_ts:
                        try:
                            ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")).timestamp()
                        except Exception:
                            ts = None
                    self._record_diag(str(entry.get("content")), ts)
                self._render_history_entry(entry)
            self.chat.scroll_end()
        else:
            # Новая сессия: показываем баннер с логотипом (после раскладки,
            # чтобы знать ширину поля вывода и автомасштабировать арт).
            self.call_after_refresh(self._mount_banner)

    def _mount_banner(self) -> None:
        """Логотип + версия в начале новой сессии, с автоскейлом под ширину чата."""
        if self.chat is None:
            return
        art = None
        try:
            from core.image_ascii import image_to_fullcolor
            logo_path = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.png")
            if os.path.exists(logo_path):
                # Ширина поля вывода в символах; каждый пиксель арта = 2 символа.
                field_width = 0
                try:
                    field_width = self.chat.size.width or self.size.width or 0
                except Exception:
                    field_width = 0
                logo_width = max(16, min(80, (field_width - 6) // 2)) if field_width else 40
                text, _ = image_to_fullcolor(logo_path, logo_width)
                art = Text.from_ansi(text)
        except Exception:
            art = None
        try:
            if art is not None:
                self.chat.mount(Static(art, markup=False))
            ver = f"BOTINOK AGENT — Version {self.version}" if self.version else "BOTINOK AGENT"
            self.chat.mount(Static(f"[bold yellow]{ver}[/bold yellow]"))
            self.chat.mount(Static(""))
            self.chat.scroll_end(animate=False)
        except Exception:
            pass

    def _format_tool_call(self, name: str, args) -> str:
        """Тело раскрытого tool-call: команда через shfmt либо pretty-JSON.

        Именно это видно при клике по строке вызова в истории сессии.
        """
        try:
            if name == "shell_exec" and isinstance(args, dict) \
                    and isinstance(args.get("command"), str):
                return f"🔧 {name}\n\n" + format_shell_command(args["command"])
            if isinstance(args, dict):
                return f"🔧 {name}\n\n" + json.dumps(args, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return f"🔧 {name}"

    def _render_history_entry(self, entry: dict) -> None:
        role = entry.get("role", "")
        content = entry.get("content", "")
        thinking = entry.get("thinking", "")
        tool_calls = entry.get("tool_calls", [])
        timestamp = entry.get("timestamp", "")
        ts_str = ""
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                ts_str = dt.strftime("%H:%M:%S")
            except Exception:
                ts_str = str(timestamp)[:8]
        if role == "user":
            self._add_static(f"[dim]━━━ {ts_str} ━━━[/dim]")
            self._add_static(f"[bold blue]User:[/bold blue] {self._rich_escape(str(content))}")
            self._add_static("")
        elif role == "assistant":
            self._add_static("[bold green]Assistant:[/bold green]")
            if thinking:
                self._mount_spoiler(self._spoiler_title("Thinking", thinking), Static(self._rich_escape(thinking)), collapsed=True)
            if content:
                try:
                    self.chat.mount(Markdown(normalize_cells(str(content))))
                except Exception:
                    self._add_static(self._rich_escape(str(content)))
                self._add_static("")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "unknown")
                    try:
                        args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                    except Exception:
                        args = {}
                    args_json = json.dumps(args, ensure_ascii=False)
                    title = self._spoiler_title(name, args_json)
                    self._mount_spoiler(title, Static(self._format_tool_call(name, args),
                                                      markup=False))
        elif role == "tool":
            title = self._spoiler_title("Tool result", str(content)[:200])
            self._mount_spoiler(title, Static(f"[dim]{self._rich_escape(str(content)[:1000])}[/dim]"))
        elif role == "system":
            pass

    def append_user_message(self, content: str) -> None:
        self._record_diag(str(content))
        ts = datetime.now().strftime("%H:%M:%S")
        self._add_static(f"[dim]━━━ {ts} ━━━[/dim]")
        self._add_static(f"[bold blue]User:[/bold blue] {self._rich_escape(str(content))}")
        self._add_static("")
        self.chat.scroll_end(animate=False)

    def start_assistant_turn(self) -> None:
        self._flush_tool_spoilers()
        self._last_chunk_time = 0.0
        self.stream_static = Static("", markup=True)
        self.chat.mount(self.stream_static)
        self._stream_content = ""
        self._stream_thinking = ""
        self._last_tool_content = ""
        self.is_streaming = True
        self._stop_requested = False

    def _update_queue_placeholder(self) -> None:
        try:
            q = len(self._queued_inputs)
            inp = self.input_widget or self.query_one("#input", Composer)
            if q:
                inp.placeholder = f"[{q} queued] Введите ваш вопрос..."
            else:
                inp.placeholder = "Введите ваш вопрос (Enter — отправить, Shift+Enter — новая строка)..."
        except Exception:
            pass

    def _autosize_composer(self) -> None:
        """Подогнать высоту композера под число строк (1..8) + рамка."""
        c = self.input_widget
        if c is None:
            return
        try:
            lines = max(1, c.wrapped_document.height)
        except Exception:
            lines = 1
        try:
            c.styles.height = min(8, lines) + 2
        except Exception:
            pass

    def _composer_history(self, composer, direction: int) -> None:
        if not self._prompt_history:
            return
        self._history_idx = max(0, min(len(self._prompt_history), self._history_idx + direction))
        if self._history_idx >= len(self._prompt_history):
            composer.text = ""
        else:
            composer.text = self._prompt_history[self._history_idx]

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if self.input_widget is None or event.text_area is not self.input_widget:
            return
        # Детект «всплеска» ввода (вставка из буфера): защищает от Enter-ов
        # внутри вставки на терминалах без bracketed paste.
        now = time.time()
        c = self.input_widget
        new_len = len(c.text or "")
        delta = new_len - c._prev_len
        # Вставка: либо большой кусок за раз, либо «строчки» символов с
        # минимальным интервалом (терминалы без bracketed paste).
        if delta > 1 or (c._last_change > 0 and (now - c._last_change) < 0.03):
            c._paste_until = now + 0.25
        c._prev_len = new_len
        c._last_change = now
        self.call_after_refresh(self._autosize_composer)

    def on_composer_submitted(self, event: "Composer.Submitted") -> None:
        user_input = (event.value or "").strip()
        if not user_input:
            return
        if self.input_widget is not None:
            self.input_widget.text = ""
            self._autosize_composer()
        self._prompt_history.append(user_input)
        self._history_idx = len(self._prompt_history)
        self.current_prompt = user_input
        self._footer_dirty = True
        if user_input.startswith("/"):
            if self.on_slash_command:
                self.on_slash_command(user_input)
        elif self.is_streaming:
            self._queued_inputs.append(user_input)
            self._update_queue_placeholder()
            self._add_static(f"[dim]⏸ +{len(self._queued_inputs)}: {self._rich_escape(user_input)}[/dim]")
            self.chat.scroll_end(animate=False)
        elif self.on_submit:
            self._submit_text(user_input)
        self.update_stats_display()

    def request_stop(self) -> None:
        self._stop_requested = True

    def on_key(self, event) -> None:
        if event.key == "escape" and self.is_streaming:
            self.request_stop()
            self.append_log("[dim]⏹ Stop requested[/dim]")
            event.stop()

    @staticmethod
    def _collapse_newlines(text: str) -> str:
        return re.sub(r'\n{3,}', '\n\n', text)

    def append_assistant_chunk(self, content: str = "", thinking: str = "",
                                tool_stream_json: str = "") -> None:
        if thinking:
            self._stream_thinking += thinking
        if content:
            self._stream_content += content
        if tool_stream_json:
            self._last_tool_content = tool_stream_json
        if self.stream_static:
            parts = []
            if self._stream_thinking:
                t = self._collapse_newlines(self._rich_escape(self._stream_thinking))
                parts.append(f"[#555555]Thinking...[/#555555]\n[#555555]{t}[/#555555]")
            if tool_stream_json:
                tool_display = self._GGUF_TAG_RE.sub("", tool_stream_json)
                tool_display = self._GGUF_QUOTE_RE.sub('"', tool_display)
                tool_display = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', tool_display)
                tool_display = re.sub(r'[\x80-\x9f]', '', tool_display)
                tool_display = tool_display.replace("[", r"\[")
                if any(t in tool_display for t in self._KNOWN_TOOLS) or ("call:" in tool_display) or ("{" in tool_display and ":" in tool_display):
                    parts.append(f"[bold magenta]Tool Call:[/bold magenta]\n{tool_display}")
            if self._stream_content:
                t = self._collapse_newlines(self._rich_escape(self._stream_content))
                parts.append(f"[#555555]Response:[/#555555]\n[#555555]{t}[/#555555]")
            self.stream_static.update("\n\n".join(parts) if parts else "")

    def finalize_assistant_turn(self, content: str, thinking: str = "",
                                tool_calls: Optional[list] = None) -> None:
        final_content = content or self._stream_content

        # Рассуждение схлопывается в одну строку НА СВОЁМ МЕСТЕ: оно стримилось
        # первым и должно остаться над ответом (хронология не нарушается).
        final_thinking = thinking or self._stream_thinking
        if final_thinking:
            title = self._spoiler_title("Thinking", final_thinking)
            self._mount_spoiler(title, Static(self._rich_escape(final_thinking)), collapsed=True,
                                before=self.stream_static)

        # Ответ конвертируем на месте в Markdown — он идёт ниже рассуждения.
        # Рассуждение КАК УЖЕ убрано из stream_static (см. спойлер выше), поэтому
        # static всегда финализируем: есть ответ — Markdown, нет — очищаем, чтобы
        # сырой многострочный текст мышления не оставался мусором в общем потоке.
        if self.stream_static:
            if final_content:
                mounted_md = False
                try:
                    md = Markdown(normalize_cells(str(final_content)))
                    self.chat.mount(md, before=self.stream_static)
                    self.stream_static.remove()
                    mounted_md = True
                except Exception:
                    mounted_md = False
                if not mounted_md:
                    self.stream_static.update(self._rich_escape(final_content))
            else:
                self.stream_static.update("")
            self.stream_static = None

        self._last_tool_content = ""

        if tool_calls:
            for tc in tool_calls:
                name = tc.get("function", {}).get("name", "unknown")
                self._tool_items.append(f"🔧 {name}")

    def _flush_tool_spoilers(self) -> None:
        if self._tool_items:
            text = "\n".join(self._tool_items)
            title = self._spoiler_title("Tool calls", text)
            self._mount_spoiler(title, Static(f"[dim]{text}[/dim]"))
            self._tool_items = []

    def append_tool_result(self, tool_name: str, result: str) -> None:
        self._tool_items.append(f"  └ ✔ {tool_name}")
        # Сохраняем превью результата в карточку инструмента (раскрывается по клику).
        preview = normalize_cells(str(result))[:4000]
        for t in reversed(self.active_tools):
            if t["name"] == tool_name:
                t["result"] = preview
                break
        self._tools_dirty = True
        self.update_stats_display()

    def update_stats(self, status: str, elapsed: float, no_chunks: float, ttft,
                     thinking_tokens: int, response_tokens: int, stream_tool_tokens: int,
                     final_tool_tokens: int, tps: float, vram: str,
                     session_ctx: int, session_ctx_max: int,
                     last_req_ctx: int, last_req_ctx_max: int) -> None:
        self.stats_data = {
            "status": status, "elapsed": elapsed, "no_chunks": no_chunks,
            "ttft": ttft, "thinking_tokens": thinking_tokens,
            "response_tokens": response_tokens,
            "stream_tool_tokens": stream_tool_tokens,
            "final_tool_tokens": final_tool_tokens, "tps": tps, "vram": vram,
            "session_ctx": session_ctx, "session_ctx_max": session_ctx_max,
            "last_req_ctx": last_req_ctx, "last_req_ctx_max": last_req_ctx_max,
        }
        self._stats_dirty = True
        self.update_stats_display()

    def add_tool_activity(self, name: str, query: str, status: str = "running", size_kb: float = 0) -> None:
        self.active_tools.append({"name": name, "query": query, "status": status, "size_kb": size_kb, "start_time": time.time()})
        self._tools_dirty = True
        self.update_stats_display()

    def update_tool_activity(self, name: str, status: str = "completed", size_kb: float = 0, query: str = "") -> None:
        for t in reversed(self.active_tools):
            if t["name"] == name:
                t["status"] = status
                t["size_kb"] = size_kb
                if query:
                    t["query"] = query
                break
        self._tools_dirty = True
        self.update_stats_display()

    def flush_tool_buffer(self) -> None:
        self._flush_tool_spoilers()
        self.is_streaming = False
        self._last_chunk_time = 0.0
        if self._queued_inputs:
            text = "\n\n".join(self._queued_inputs)
            self._queued_inputs = []
            self._update_queue_placeholder()
            self.append_user_message(text)
            if self.on_submit:
                self.is_streaming = True
                self.on_submit(text)

    def append_log(self, text: str) -> None:
        if self.chat:
            self._add_static(self._rich_escape(text))
            self.chat.scroll_end(animate=False)

    def clear_log(self) -> None:
        if self.chat:
            self.chat.remove_children()

    def show_confirmation_prompt(self, tool_name: str, args_display: str, warn_text: str) -> None:
        self._confirmation_event = threading.Event()
        self._confirmation_result = False
        self._confirmation_reason = ""
        # По умолчанию — ВСТРОЕННОЕ подтверждение в окне вывода (не накрывает
        # правые панели). Модальный ConfirmationScreen — только запасной путь,
        # если inline-слот недоступен.
        widget = ConfirmInline(
            tool_name, args_display, warn_text,
            on_resolve=self._apply_confirmation,
        )
        if self.inline_confirm_container is not None:
            self.hide_inline_confirmation()
            try:
                self.inline_confirm_container.mount(widget)
                self.inline_confirm_container.add_class("active")
                self.inline_confirm_widget = widget
                return
            except Exception:
                self.inline_confirm_widget = None
        self.push_screen(ConfirmationScreen(
            tool_name, args_display, warn_text,
            on_resolve=self._apply_confirmation,
        ))

    def hide_inline_confirmation(self) -> None:
        """Убрать встроенное подтверждение (после выбора/таймаута)."""
        w = self.inline_confirm_widget
        if w is not None:
            try:
                w.remove()
            except Exception:
                pass
            self.inline_confirm_widget = None
        try:
            self.inline_confirm_container.remove_class("active")
        except Exception:
            pass
        self._keep_focus()

    def wait_for_confirmation(self, timeout: float = 300) -> bool:
        if self._confirmation_event:
            self._confirmation_event.wait(timeout=timeout)
            return self._confirmation_result
        return False

    def _restore_input_placeholder(self) -> None:
        self._update_queue_placeholder()

    def _apply_confirmation(self, confirmed: bool, reason: str = "") -> None:
        """Колбэк модального экрана — вызывается из UI-потока."""
        self._confirmation_result = confirmed
        self._confirmation_reason = reason
        self._restore_input_placeholder()
        self.update_stats_display()
        if self._confirmation_event:
            self._confirmation_event.set()

    def _submit_text(self, user_input: str) -> None:
        """Отправить реплику пользователя в агент (общий путь для ввода и CLI-промпта)."""
        if not self.on_submit:
            return
        self._start_time = time.time()
        self.append_user_message(user_input)
        self.on_submit(user_input)
