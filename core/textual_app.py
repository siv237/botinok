"""
Textual приложение для Botinok — стриминг в Static, спойлеры Collapsible в общем потоке.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (Input, Static, Collapsible, OptionList, Button,
                             Markdown, ProgressBar, TextArea, Checkbox)
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
from core.text_width import normalize_cells, cell_truncate, cell_width
from core.shell_screen import format_shell_command
from core.file_kinds import syntax_renderable
import core.net_meter as net_meter

# Ленивая загрузка истории: сразу рисуем только хвост сессии, остальное — по
# кнопке/прокрутке. На длинной сессии полная отрисовка — десятки секунд и
# подвешивает UI (тысячи виджетов x CSS Textual).
HISTORY_INITIAL_ENTRIES = 200
HISTORY_BATCH_ENTRIES = 200

try:
    from core import process_control as _pc
except Exception:  # pragma: no cover
    _pc = None

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
                 on_resolve: Optional[Callable] = None, kind: str = "confirm", **kwargs):
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.args_display = args_display
        self.warn_text = warn_text
        self.on_resolve = on_resolve
        self.kind = kind
        self._switch_kind = (kind == "switch")
        self._reason_mode = False
        self._body: Optional[Static] = None
        self._options: Optional[OptionList] = None
        self._auto: Optional[Checkbox] = None

    def _esc(self, text: str) -> str:
        return str(text or "").replace("[", r"\[")

    def compose(self) -> ComposeResult:
        warn = f"{self._esc(self.warn_text)}\n" if self.warn_text else ""
        if self._switch_kind:
            title = "[bold red]🔓 ТРЕБУЕТСЯ DANGEROUS MODE[/bold red]"
            lead = ("[bold yellow]Инструмент[/bold yellow] "
                    f"{self._esc(self.tool_name)} хочет выполнить действие вне сессии.\n"
                    "[dim]Переключиться в dangerous mode и выполнить?[/dim]")
        else:
            title = "[bold red]⚠️  ПОДТВЕРДИТЕ ОПАСНОЕ ДЕЙСТВИЕ[/bold red]"
            lead = (f"[bold yellow]Инструмент:[/bold yellow] {self._esc(self.tool_name)}\n"
                    f"[bold yellow]Аргументы:[/bold yellow] {self._esc(self.args_display)}")
        self._body = Static(
            f"{title}\n{lead}\n{warn}"
            f"[dim]y — да · n/esc — нет · ↑↓ — выбор · Enter — подтвердить[/dim]",
            id="confirm_body")
        yield self._body
        if self._switch_kind:
            opts = [
                Option("✅ Да, переключить и выполнить", id="yes"),
                Option("❌ Нет, отменить", id="no"),
            ]
        else:
            opts = [
                Option("✅ Да, выполнить", id="yes"),
                Option("❌ Нет, отменить", id="no"),
                Option("✏️  Отменить с причиной", id="no_reason"),
            ]
        self._options = OptionList(*opts, id="confirm_options")
        with Horizontal(id="confirm_choice_row"):
            yield self._options
            if not self._switch_kind:
                self._auto = Checkbox("Автосогласие на сессию (a)", id="confirm_auto")
                yield self._auto

    def on_mount(self) -> None:
        if self._options:
            self._options.focus()

    def _auto_checked(self) -> bool:
        try:
            return bool(self._auto and self._auto.value)
        except Exception:
            return False

    def _resolve(self, choice: str, reason: str = "") -> None:
        confirmed = (choice == "yes")
        final_reason = reason if (choice == "no_reason" and reason) else ""
        try:
            if self.on_resolve:
                self.on_resolve(confirmed, final_reason, self._auto_checked())
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
        elif k in ("a", "ф"):
            if self._auto is not None:
                self._auto.value = not self._auto.value
            event.stop()


class ConfirmInline(Vertical):
    """Встроенное в окно вывода подтверждение опасного действия.

    Не накрывает правые панели (в отличие от модального ConfirmationScreen):
    живёт в `#content` над терминалом/чатом. Логика та же: y/д — да,
    n/esc — нет, ↑↓ + Enter — выбор, «Отменить с причиной» — мини-инпут.
    """

    BINDINGS = []

    def __init__(self, tool_name: str, args_display: str, warn_text: str = "",
                 on_resolve: Optional[Callable] = None, kind: str = "confirm", **kwargs):
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.args_display = args_display
        self.warn_text = warn_text
        self.on_resolve = on_resolve
        self.kind = kind
        self._switch_kind = (kind == "switch")
        self._reason_mode = False
        self._body: Optional[Static] = None
        self._options: Optional[OptionList] = None
        self._auto: Optional[Checkbox] = None
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

    def _args_block(self):
        """Тело для показа: команда (развёрнутая) либо pretty-JSON аргументов.

        Возвращает Rich-renderable с подсветкой синтаксиса (bash/json) либо
        обычную строку, если язык неизвестен.
        """
        cmd = self._command()
        if cmd is not None:
            return syntax_renderable(format_shell_command(cmd), "bash")
        if isinstance(self._args, dict):
            try:
                return syntax_renderable(
                    json.dumps(self._args, ensure_ascii=False, indent=2)[:4000], "json")
            except Exception:
                pass
        return str(self.args_display or "")[:4000]

    def compose(self) -> ComposeResult:
        warn = f"{self._esc(self.warn_text)}\n" if self.warn_text else ""
        has_cmd = self._command() is not None
        label = "Команда:" if has_cmd else "Аргументы:"
        if self._switch_kind:
            title = "[bold red]🔓 ТРЕБУЕТСЯ DANGEROUS MODE[/bold red]"
            lead = (f"[bold yellow]Инструмент[/bold yellow] {self._esc(self.tool_name)} "
                    "хочет выполнить действие вне сессии.\n"
                    "[dim]Переключиться в dangerous mode и выполнить?[/dim]")
        else:
            title = "[bold red]⚠️  ПОДТВЕРДИТЕ ОПАСНОЕ ДЕЙСТВИЕ[/bold red]"
            lead = (f"[bold yellow]Инструмент:[/bold yellow] {self._esc(self.tool_name)}\n"
                    f"[bold yellow]{label}[/bold yellow]")
        self._body = Static(
            f"{title}\n{lead}\n{warn}"
            f"[dim]y — да · n/esc — нет · ↑↓ — выбор · Enter — подтвердить[/dim]",
            id="inline_confirm_body")
        yield self._body
        # Развёрнутая команда/аргументы — в прокручиваемом блоке, чтобы
        # длинную команду было удобно читать глазами прямо в подтверждении.
        yield VerticalScroll(
            Static(self._args_block(), markup=False, id="inline_confirm_cmd"),
            id="inline_confirm_cmd_scroll")
        if self._switch_kind:
            opts = [
                Option("✅ Да, переключить и выполнить", id="yes"),
                Option("❌ Нет, отменить", id="no"),
            ]
        else:
            opts = [
                Option("✅ Да, выполнить", id="yes"),
                Option("❌ Нет, отменить", id="no"),
                Option("✏️  Отменить с причиной", id="no_reason"),
            ]
        self._options = OptionList(*opts, id="inline_confirm_options")
        with Horizontal(id="inline_confirm_choice_row"):
            yield self._options
            if not self._switch_kind:
                self._auto = Checkbox("Автосогласие на сессию (a)", id="inline_confirm_auto")
                yield self._auto

    def on_mount(self) -> None:
        if self._options:
            self._options.focus()

    def _auto_checked(self) -> bool:
        try:
            return bool(self._auto and self._auto.value)
        except Exception:
            return False

    def _resolve(self, choice: str, reason: str = "") -> None:
        confirmed = (choice == "yes")
        final_reason = reason if (choice == "no_reason" and reason) else ""
        try:
            if self.on_resolve:
                self.on_resolve(confirmed, final_reason, self._auto_checked())
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
        elif k in ("a", "ф") and not self._switch_kind:
            if self._auto is not None:
                self._auto.value = not self._auto.value
            event.stop()


class Composer(TextArea):
    """Многострочный композер ввода.

    Enter — отправка, Alt+Enter — новая строка (работает в любом терминале),
    Ctrl+J — тоже новая строка, Shift+Enter — там, где терминал его различает.
    Esc — очистить, Alt+↑/↓ — история. Вставка из буфера (bracketed paste)
    вставляет текст целиком и НЕ отправляет; дополнительно есть защита от
    «всплеска» ввода на терминалах без bracketed paste (Enter внутри вставки
    становится переводом строки, а не отправкой).
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
        # Ctrl+Enter (если терминал его различает) — отправка, как обычный Enter.
        if key in ("enter", "ctrl+enter"):
            event.stop()
            event.prevent_default()
            if time.time() < self._paste_until:
                # Похоже на вставку из буфера — не отправляем.
                self.insert("\n")
            else:
                self.action_submit()
            return
        # Новая строка: Alt+Enter — универсально (VTE/xterm/VS Code), Ctrl+J —
        # везде, Shift+Enter — там, где терминал умеет его различать.
        if key in ("alt+enter", "shift+enter", "ctrl+j"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        if key == "escape":
            event.stop()
            event.prevent_default()
            # Во время генерации Esc — сигнал остановки, а не очистка ввода.
            # Composer держит фокус и не даёт клавише всплыть до App.on_key,
            # поэтому останавливаем сессию прямо здесь.
            app = self.app
            if app.turn_in_progress():
                try:
                    app.request_stop()
                    app._log_stop_once()
                except Exception:
                    pass
                return
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
    #header_row { height: 1; min-height: 1; max-height: 1; padding: 0; margin: 0;
                  background: #0055aa; }
    #header_row.dangerous { background: red; }
    #header_row.proofreader { background: yellow; }
    #header { width: 1fr; height: 1; padding: 0; margin: 0;
              content-align: center middle; background: transparent; color: white; text-style: bold; }
    /* Флаг автосогласия в шапке: виден только когда включён; клик — отключить. */
    #auto_flag { width: auto; height: 1; padding: 0 1; margin: 0; display: none;
                 background: #cc8800; color: black; text-style: bold; }
    #auto_flag.on { display: block; }
    #main { height: 1fr; }
    #content { width: 2fr; height: 1fr; padding: 0; }
    #diag { height: auto; max-height: 16; width: 1fr; background: transparent; border: none; padding: 0; }
    #diag CollapsibleTitle { width: 1fr; padding: 0; color: cyan; }
    #diag_scroll { height: auto; max-height: 14; }
    #diag_list { height: auto; }
    #diag_list .diag_row { height: auto; width: 1fr; }
    #diag_list .diag_prefix { width: auto; height: auto; }
    #diag_list .diag_text { width: 1fr; height: auto; }
    #diag_list Collapsible { width: 1fr; height: auto; background: transparent;
                             border: none; padding: 0; }
    #diag_list CollapsibleTitle { padding: 0; width: 1fr; }
    #inline_confirm { height: auto; max-height: 60%; display: none;
                      border: solid red; padding: 0 1; background: $surface; }
    #inline_confirm.active { display: block; }
    #inline_confirm ConfirmInline { height: auto; }
    #inline_confirm_body { height: auto; padding: 0 1; }
    #inline_confirm_cmd_scroll { height: auto; max-height: 12; overflow-y: auto; }
    #inline_confirm_cmd { height: auto; background: #0f0f0f; color: #d0d0d0; padding: 0 1;
                         border: round #5f87af; }
    #inline_confirm_options { height: auto; max-height: 10; border: none;
                              padding: 0; background: transparent; width: 1fr; }
    #inline_confirm_options:focus { border: none; }
    #inline_confirm_reason { height: 3; }
    /* Строка выбора согласия + галочка автосогласия на сессию. */
    #inline_confirm_choice_row, #confirm_choice_row { height: auto; }
    #inline_confirm_auto, #confirm_auto { width: auto; height: auto; margin: 0 0 0 2; }
    /* Запасной модальный вариант: без вложенной рамки OptionList. */
    #confirm_options { border: none; padding: 0; background: transparent; width: 1fr; }
    #inline_shell { height: 50%; display: none; border: solid cyan; padding: 0; }
    #inline_shell.active { display: block; }
    #inline_shell ShellInline { height: 1fr; }
    #inline_shell_title { height: 1; background: cyan; color: black;
                          text-style: bold; padding: 0 1; }
    #inline_shell_cmd, #shell_cmd { height: auto; max-height: 40%; display: none;
                                    background: #0f0f0f; color: #d0d0d0;
                                    padding: 0 1; border: none; }
    #inline_shell_cmd.show, #shell_cmd.show { display: block; }
    /* Раскрытая команда отделена рамкой (без цветного фона), чтобы визуально
       отличать её от результата под ней. */
    #inline_shell_cmd.show, #shell_cmd.show { background: #0f0f0f; color: #d0d0d0;
                                              border: round #5f87af; }
    /* Когда команда раскрыта — сокращённая (title) не показывается. */
    ShellInline.cmd-open #inline_shell_title { display: none; }
    ShellScreen.cmd-open #shell_title { display: none; }
    #inline_shell_log { height: 1fr; border: none; padding: 0 1; background: #0c0c0c; }
    #inline_shell_hint { height: 1; color: $text-muted; padding: 0 1; }
    #inline_shell_bottom { height: 3; }
    #inline_shell_input { height: 3; width: 1fr; }
    #inline_shell_buttons { height: 3; width: auto; align: right middle; }
    #inline_shell_buttons Button { min-width: 12; height: 3; margin: 0 1; }
    #chat { height: 1fr; min-height: 3; border: solid green; padding: 0 1; overflow-y: auto; }
    #load_older { width: 1fr; height: 1; min-height: 1; margin: 0; padding: 0 1;
                  background: transparent; border: none; color: cyan; }
    #load_older:hover { background: $primary 30%; }
    .history_batch { height: auto; width: 1fr; }
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
    #stats { height: auto; border: round yellow; border-title-color: yellow;
             border-title-style: bold; padding: 0 1; }
    #stats_rows { height: auto; }
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
    /* Очередь «мыслей»: висит внизу над полем ввода, у каждой — крестик отмены. */
    #thought_queue { height: auto; max-height: 8; display: none;
                     background: $surface; border-top: solid $panel; padding: 0 1; }
    #thought_queue.-visible { display: block; }
    .thought_chip { height: 1; }
    .thought_text { width: 1fr; color: $text-muted; }
    .thought_del { width: 3; min-width: 3; height: 1; border: none; padding: 0;
                   background: transparent; color: red; }
    .thought_del:hover { background: $error 30%; }
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
        self.header_row: Optional[Horizontal] = None
        self.auto_flag: Optional[Static] = None
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
            "status": "Готов к работе", "elapsed": 0.0, "no_chunks": 0.0,
            "ttft": "...", "thinking_tokens": 0, "response_tokens": 0,
            "stream_tool_tokens": 0, "final_tool_tokens": 0, "tps": 0.0,
            "vram": "...", "session_ctx": 0, "session_ctx_max": 8192,
            "last_req_ctx": 0, "last_req_ctx_max": 8192,
            "server": "ollama", "retries": 0, "retry_wait": 0.0,
        }
        self.active_tools: List[dict] = []
        self._tools_expanded: set = set()  # ключи раскрытых узлов Tools Activity
        self._tool_id_to_key: dict = {}
        self._tool_widgets: dict = {}
        self._tools_placeholder: Optional[Static] = None
        self._start_time = time.time()
        self._last_chunk_time = 0.0
        # Живые метрики текущего потока: когда начался поток, когда пришёл
        # первый фрагмент и когда сменилась фаза (для таймеров на панели).
        self._stream_started_at = 0.0
        self._first_token_at: Optional[float] = None
        # Активное время потока (сумма интервалов между данными, без пауз):
        # скорость считается по нему, чтобы простой не занижал среднюю.
        self._stream_active_time = 0.0
        self._prev_chunk_at: Optional[float] = None
        self._stream_ui_last = 0.0
        self._stats_lines = -1
        self._render_target = None
        self._history_all: list = []
        self._history_from = 0
        self._load_older_button = None
        self._loading_older = False
        self._loading_widget = None
        self._phase_status = ""
        self._phase_started_at = time.time()
        self._stream_content = ""
        self._stream_thinking = ""
        self._last_tool_content = ""
        self._tool_items: List[str] = []
        self.is_streaming = False
        self._stop_requested = False
        self._stop_logged = False
        self._user_scrolled_away = False
        self._last_scroll_y: Optional[float] = None
        self._queued_inputs: List[str] = []
        self.input_widget: Optional[Composer] = None
        self._prompt_history: List[str] = []
        self._history_idx = 0
        self._confirmation_event: Optional[threading.Event] = None
        self._confirmation_started_at = 0.0
        self._confirmation_result: bool = False
        self._confirmation_kind: str = "confirm"
        # Автосогласие на опасные действия до конца сессии (галочка в окне
        # подтверждения dangerous mode).
        self.dangerous_auto_confirm = False
        # Пользователь отказался переключаться в dangerous mode — больше не
        # спрашиваем в этой сессии, агент должен искать другие пути.
        self.dangerous_switch_denied = False
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
        # Заголовок Collapsible парсится как Rich-markup, поэтому экранируем
        # '[' — иначе JSON-массив в аргументах (edits:[{...]) роняет рендер
        # истории с MarkupError.
        return f"{self._rich_escape(label)}: {self._rich_escape(preview)}  {ts}"

    def _mount_spoiler(self, title: str, *content_widgets, collapsed: bool = False,
                       before=None, target=None):
        if self._last_open_spoiler:
            try:
                self._last_open_spoiler.collapsed = True
            except Exception:
                pass
        c = Collapsible(*content_widgets, title=title, collapsed=collapsed, collapsed_symbol="", expanded_symbol="")
        self._last_open_spoiler = c
        dst = target if target is not None else (self._render_target or self.chat)
        if before is not None:
            try:
                dst.mount(c, before=before)
            except Exception:
                dst.mount(c)
        else:
            dst.mount(c)
        if dst is self.chat:
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

    def _add_static(self, content, markup=True, target=None):
        # Единая точка вставки в чат: нормализуем ширину для строк, чтобы
        # вариационные селекторы/ZWJ/табы не сдвигали границы панелей.
        if isinstance(content, str):
            content = normalize_cells(content)
        s = Static(content, markup=markup)
        dst = target if target is not None else (self._render_target or self.chat)
        dst.mount(s)
        if dst is self.chat:
            self._keep_focus()
        return s

    def compose(self) -> ComposeResult:
        self.header_row = Horizontal(id="header_row")
        self.header_display = Static("", id="header")
        self.auto_flag = Static("АВТОСОГЛАСИЕ: ВКЛ ✕", id="auto_flag")
        with self.header_row:
            yield self.header_display
            yield self.auto_flag
        with Horizontal(id="main"):
            self.content_container = Vertical(id="content")
            with self.content_container:
                self.diag_list = Vertical(id="diag_list")
                self.diag_scroll = VerticalScroll(self.diag_list, id="diag_scroll")
                self.diag = Collapsible(self.diag_scroll, title="📝 Запрос:", collapsed=True, id="diag")
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
                with Vertical(id="stats"):
                    self.stats_rows = Static("", id="stats_rows")
                    yield self.stats_rows
                    self.ctx_bar = ProgressBar(total=100, show_eta=False, id="ctx_bar")
                    yield self.ctx_bar
                with Vertical(id="tools"):
                    self.tools_list = Vertical(id="tools_list")
                    yield self.tools_list
                # Терминалы — ВНИЗУ колонки: растут вниз, сжимая инструменты,
                # а не панель метрик.
                self.shells_display = VerticalScroll(id="shells")
                yield self.shells_display
        self.thought_queue = Vertical(id="thought_queue")
        yield self.thought_queue
        self.input_widget = Composer(
            id="input",
            placeholder="Введите ваш вопрос (Enter — отправить, Alt+Enter — новая строка)...",
        )
        yield self.input_widget

    def on_mount(self) -> None:
        # Перехват трафика модели включаем до первых запросов (в т.ч. до
        # фоновой проверки памяти, которая стартует ниже).
        try:
            net_meter.install()
        except Exception:
            pass
        self.load_history()
        # Заголовки панелей и колонки таблицы инструментов — нативные средства Textual.
        try:
            self.query_one("#stats").border_title = "Производительность"
            self.query_one("#tools").border_title = "Инструменты"
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

    def set_model_info(self, model: str, dangerous: bool = False, proofreader: bool = False,
                       server: Optional[str] = None):
        self.model_name = model
        if server:
            self.stats_data["server"] = server
        self.dangerous_mode = dangerous
        if dangerous:
            # Режим включён вручную — отказ от переключения больше не актуален.
            self.dangerous_switch_denied = False
        else:
            # Выключение dangerous mode сбрасывает автосогласие сессии.
            self.dangerous_auto_confirm = False
        self.is_proofreader = proofreader
        self._stats_dirty = True
        self._tools_dirty = True
        self._footer_dirty = True
        self.update_stats_display()

    def report_chunk(self) -> None:
        now = time.time()
        # Копим ТОЛЬКО активное время: пауза (долгий разрыв между данными)
        # в знаменатель скорости не попадает и не занижает среднюю.
        if self._prev_chunk_at is not None:
            gap = now - self._prev_chunk_at
            if 0 < gap <= 1.0:
                self._stream_active_time += gap
        self._prev_chunk_at = now
        self._last_chunk_time = now

    _IDLE_STATUSES = ("Готов к работе", "Ready", "Ответ готов", "Done", "",
                      "Ошибка связи", "Ошибка сервера", "Обрыв потока")

    def _task_active(self) -> bool:
        """Идёт ли работа прямо сейчас (для живого таймера и детектора зависаний)."""
        try:
            if self.is_streaming:
                return True
            if any(t.get("status") == "running" for t in self.active_tools):
                return True
            return self.stats_data.get("status", "") not in self._IDLE_STATUSES
        except Exception:
            return False

    @staticmethod
    def _ru_status(status: str, printing: bool = False) -> str:
        """Технический статус → понятная русская фраза для пользователя."""
        s = (status or "").strip()
        table = {
            "Ready": "Готов к работе",
            "Готов к работе": "Готов к работе",
            "Generating...": "Модель печатает ответ…" if printing else "Модель думает…",
            "Waiting for tool call...": "Жду ответа модели…",
            "Calling Tools...": "Выполняю команды…",
            "Processing tool calls...": "Обрабатываю вызовы…",
            "Resuming generation...": "Продолжаю генерацию…",
            "Checking Memory...": "Проверяю память…",
            "Unloading Models...": "Освобождаю память…",
            "Forced VRAM Cleanup...": "Чищу видеопамять…",
            "Connecting...": "Подключаюсь к модели…",
            "Tool-mode parsing...": "Разбираю вызов инструмента…",
            "Streaming Tool JSON...": "Готовлю команду…",
            "Done": "Ответ готов",
            "Chat-only mode (no tools)": "Режим без инструментов",
            "Connection Error": "Нет связи с сервером",
            "Ollama Error": "Ошибка сервера",
            "Stream Error": "Обрыв потока",
            "Proofreader is thinking...": "Корректор проверяет…",
        }
        return table.get(s, s)

    @staticmethod
    def _fmt_bytes_raw(n) -> str:
        """Сырой объём в байтах с разрядами: каждый байт двигает число."""
        try:
            return f"{int(n):,}".replace(",", " ") + " Б"
        except Exception:
            return "0 Б"

    @staticmethod
    def _fmt_secs(secs) -> str:
        secs = int(max(0, secs or 0))
        if secs < 60:
            return f"{secs} с"
        if secs < 3600:
            return f"{secs // 60} мин {secs % 60:02d} с"
        return f"{secs // 3600} ч {(secs % 3600) // 60:02d} мин"

    def _tick_stats(self) -> None:
        now = time.time()
        # Раз в 30 секунд обновляем относительное время у вопросов в Diagnostic Log.
        if now - self._diag_last_refresh > 30:
            self._footer_dirty = True
        # Панель «живёт» только пока задача не завершена: иначе в простое мы бы
        # перерисовывали её 10 раз в секунду впустую и грели CPU (шум вентилятора).
        # Метрики «живут» 10 раз в секунду, пока ход активен (стрим, инструменты,
        # переждание сервера). В покое метрикам нечего менять — не гоняем полную
        # пересборку Textual впустую (это и грело CPU). Раньше поведение было
        # именно таким: dirty выставлялся только при активном статусе.
        waiting_human = (self._confirmation_event is not None
                         and not self._confirmation_event.is_set())
        metrics_active = (self._task_active() or waiting_human
                          or bool(self.stats_data.get("retries", 0))
                          or bool(self.stats_data.get("retry_wait", 0)))
        if metrics_active:
            self._stats_dirty = True
        status = self.stats_data.get("status", "")
        if status != self._phase_status:
            self._phase_status = status
            self._phase_started_at = now
        if self._last_chunk_time > 0:
            self.stats_data["no_chunks"] = now - self._last_chunk_time
        # Длительность хода растёт, пока задача активна (стрим, инструменты,
        # фазы подключения/памяти). В покое таймер стоит на месте.
        if self._task_active():
            self.stats_data["elapsed"] = now - self._start_time
        if self.chat:
            # Отслеживаем изменение позиции: если scroll_y уменьшился — это
            # намеренный скролл вверх (колесо/клавиши), сразу отключаем прилипание.
            cur_y = self.chat.scroll_y or 0
            if self._last_scroll_y is not None and cur_y < self._last_scroll_y - 0.5:
                self._user_scrolled_away = True
            self._last_scroll_y = cur_y
            # Догружаем более раннюю историю, когда пользователь домотал вверх.
            if (cur_y <= 1.0 and self._history_from > 0 and not self._loading_older
                    and self._user_scrolled_away):
                self._load_older_history()

            if self._user_scrolled_away:
                # Пользователь листает сам: не прилипаем, пока он явно не
                # докрутит до самого низа (тогда прилипание вернётся).
                if self._is_at_bottom():
                    self._user_scrolled_away = False
            else:
                if metrics_active:
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
        if bid == "load_older":
            event.stop()
            self._load_older_history()
            return
        if bid.startswith("thought_del_"):
            event.stop()
            try:
                idx = int(bid.rsplit("_", 1)[1])
            except Exception:
                return
            self._remove_queued(idx)
            return
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
        self.header_display.update(self._render_header_text(), layout=False)
        # Цвет шапки — CSS-классы (см. CSS).
        try:
            row = self.header_row or self.header_display
            row.set_class(self.dangerous_mode, "dangerous")
            row.set_class(self.is_proofreader, "proofreader")
        except Exception:
            pass
        # Флаг автосогласия в шапке.
        try:
            if self.auto_flag is not None:
                show = self.dangerous_auto_confirm
                self.auto_flag.set_class(show, "on")
                self.auto_flag.update("АВТОСОГЛАСИЕ: ВКЛ ✕" if show else "", layout=False)
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

    def _record_diag(self, text: str, ts: Optional[float] = None, kind: str = "prompt",
                     index: Optional[int] = None) -> None:
        text = normalize_cells(str(text)).strip()
        if not text:
            return
        if ts is None:
            ts = time.time()
        # Не плодим дубликаты при повторном рендере одного и того же запроса.
        if self.diag_entries:
            last = self.diag_entries[-1]
            if last["text"] == text and last.get("kind") == kind and abs(ts - last["ts"]) < 3:
                return
        key = f"{ts:.3f}:{len(self.diag_entries)}"
        # index — позиция записи в истории сессии (для будущего клика «перейти/
        # откатиться»); текст храним ПОЛНОСТЬЮ, обрезка только при отрисовке.
        self.diag_entries.append({"ts": ts, "text": text, "key": key,
                                  "kind": kind, "index": index})
        self._footer_dirty = True

    def _diag_row_parts(self, entry: dict):
        """(префикс, текст) строки панели запросов.

        Префикс — время и метка («📝 Запрос» / «💭 Мысль», разный цвет).
        Перенос длинного текста делает сам Textual во второй колонке, поэтому
        продолжение всегда выровнено под текстом и ничего не «уезжает».
        """
        text = str(entry["text"]).replace("\n", " ")
        try:
            head = datetime.fromtimestamp(entry["ts"]).strftime("%d.%m %H:%M")
        except Exception:
            head = "--.-- --:--"
        rel = self._rel_time(entry["ts"])
        is_thought = entry.get("kind") == "thought"
        label = "💭 Мысль: " if is_thought else "📝 Запрос: "
        color = "magenta" if is_thought else "cyan"
        prefix = f"[dim]{head} · {rel}  [/dim][{color}]{label}[/{color}]"
        body = f"[{color}]{self._rich_escape(text)}[/{color}]"
        return prefix, body

    def _update_diag(self) -> None:
        if self.diag is None:
            return
        # Заголовок «выпадающего окна» — последний запрос/мысль (обрезанный).
        if self.diag_entries:
            latest = self.diag_entries[-1]
            width = 0
            try:
                width = self.diag.size.width or 0
            except Exception:
                width = 0
            try:
                is_thought = latest.get("kind") == "thought"
                label = "💭 Мысль: " if is_thought else "📝 Запрос: "
                avail = (width - 2) if width else 60
                budget = max(8, avail - cell_width(label))
                latest_text = self._rich_escape(
                    cell_truncate(str(latest['text']).replace("\n", " "), budget))
                if is_thought:
                    self.diag.title = f"[bold magenta]💭 Мысль:[/bold magenta] [dim]{latest_text}[/dim]"
                else:
                    self.diag.title = f"[bold cyan]📝 Запрос:[/bold cyan] [dim]{latest_text}[/dim]"
            except Exception:
                pass
        else:
            try:
                self.diag.title = "📝 Запрос:"
            except Exception:
                pass
        # Строки в две колонки (префикс + текст), свежие СВЕРХУ.
        if self.diag_list is not None:
            for entry in self.diag_entries:
                key = entry["key"]
                prefix, body = self._diag_row_parts(entry)
                refs = self._diag_widgets.get(key)
                if refs is None:
                    cid = self._diag_id(key)
                    self._diag_id_to_key[cid] = key
                    p = Static(prefix, markup=True, classes="diag_prefix")
                    t = Static(body, markup=True, classes="diag_text")
                    row = Horizontal(p, t, classes="diag_row", id=cid)
                    self._diag_widgets[key] = (row, p, t)
                    try:
                        # Новые строки кладём наверх, чтобы свежая была первой.
                        self.diag_list.mount(row, before=0)
                    except Exception:
                        self._diag_widgets.pop(key, None)
                        self._diag_id_to_key.pop(cid, None)
                else:
                    try:
                        refs[1].update(prefix)
                        refs[2].update(body)
                    except Exception:
                        pass
        self._diag_last_refresh = time.time()

    def _update_stats_panel(self) -> None:
        if not self.stats_rows:
            return
        s = self.stats_data
        now = time.time()
        server = s.get("server", "ollama")
        full = (server != "openai")  # профиль Ollama (расширенный набор метрик)

        activity = ""
        if self._task_active():
            sp = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            activity = f" [bold magenta]{sp[int(now*5) % len(sp)]}[/bold magenta]"

        # Живые значения текущего потока: считаем по уже пришедшему тексту,
        # поэтому они растут прямо во время генерации, а не только в конце.
        thinking_len = len(getattr(self, "_stream_thinking", "") or "")
        response_len = len(getattr(self, "_stream_content", "") or "")
        tool_len = len(getattr(self, "_last_tool_content", "") or "")
        printing = response_len > 0

        if self._first_token_at:
            first_val = f"{self._first_token_at - self._stream_started_at:.1f} с"
        elif self._task_active() and self._stream_started_at:
            first_val = f"Жду… ({self._fmt_secs(now - self._stream_started_at)})"
        else:
            first_val = "—"

        speed_val = 0.0
        if self._stream_active_time > 0:
            speed_val = (thinking_len + response_len + tool_len) / max(self._stream_active_time, 0.1)

        # Что именно ждём: данные модели, возврат инструмента или решение
        # человека. «Молчание модели» капает ТОЛЬКО когда ждём ответ модели;
        # во время работы инструмента и ожидания кнопки это не «зависание».
        running_tools = [t for t in self.active_tools if t.get("status") == "running"]
        waiting_human = bool(self._confirmation_event is not None
                             and not self._confirmation_event.is_set())
        tool_hang = False
        tool_info = None
        if running_tools:
            t = max(running_tools, key=lambda x: now - x.get("start_time", now))
            tdur = now - t.get("start_time", now)
            if tdur >= 300:
                tcs, tword = "red", "слишком долго"
            elif tdur >= 60:
                tcs, tword = "yellow", "долго"
            else:
                tcs, tword = "green", "работает"
            tool_hang = tdur >= 300
            tool_info = (tcs, f"{normalize_cells(t.get('name', ''))}, "
                         f"{self._fmt_secs(tdur)} ({tword})")

        model_silence = 0.0
        retry_wait = s.get("retry_wait", 0) or 0
        retries = s.get("retries", 0) or 0
        waiting_server = bool(retries or retry_wait)
        if waiting_human:
            hdur = now - (self._confirmation_started_at or now)
            wait_label = "Ждём вас:"
            wait_value = f"[bold yellow]{self._fmt_secs(hdur)} — нужно ваше решение[/bold yellow]"
        elif running_tools:
            wait_label = "Модель молчит:"
            wait_value = "[dim]— (идёт инструмент)[/dim]"
        elif waiting_server:
            # Переждание сервера (сетевые повторы/504): это НЕ «молчание модели»
            # и не повод кричать «зависло».
            wait_label = "Ждём сервер:"
            wait_value = (f"[bold yellow]{self._fmt_secs(retry_wait)}"
                          f" — попытка {retries}[/bold yellow]")
        else:
            if self._last_chunk_time > 0:
                model_silence = now - self._last_chunk_time
            elif self._task_active() and self._stream_started_at:
                model_silence = now - self._stream_started_at
            if model_silence >= 30:
                sil_cs, sil_word = "red", "долго молчит"
            elif model_silence >= 10:
                sil_cs, sil_word = "yellow", "подозрительно"
            else:
                sil_cs, sil_word = "green", "норма"
            wait_label = "Модель молчит:"
            wait_value = f"[{sil_cs}]{model_silence:.1f} с — {sil_word}[/{sil_cs}]"

        L = 18  # ширина колонки подписей (моноширинный шрифт)
        def row(label: str, value: str) -> str:
            return f"[cyan]{label:<{L}}[/cyan]{value}"

        status_ru = self._ru_status(s.get("status", ""), printing=printing)
        lines = [
            row("Сервер:", "OpenAI-совместимый" if not full else "Ollama (локальный)"),
            row("Что сейчас:", f"[bold]{status_ru}[/bold]{activity}"),
            row("Всего прошло:", self._fmt_secs(s.get("elapsed", 0))),
            row("Этап:", self._fmt_secs(now - self._phase_started_at)),
            "",
            row("Размышляет:", f"[bold yellow]{thinking_len} Б[/bold yellow]"),
            row("Написал ответ:", f"[bold green]{response_len} Б[/bold green]"),
        ]
        if full:
            lines.append(row("Готовит команду:", f"[bold magenta]{tool_len} Б[/bold magenta]"))
        lines += [
            row("Скорость:", f"[bold green]{speed_val:.1f} Б/с[/bold green]"),
            row("Первый ответ:", f"[bold yellow]{first_val}[/bold yellow]"),
            row(wait_label, wait_value),
        ]

        # Работающий инструмент: растущий счётчик времени (детектор зависаний).
        if tool_info is not None:
            lines.append(row("Инструмент:", f"[{tool_info[0]}]{tool_info[1]}[/{tool_info[0]}]"))
        lines.append("")

        # Видеопамять — только у Ollama; OpenAI её не сообщает, поэтому строку
        # не показываем, чтобы не вводить в заблуждение.
        if full:
            vram = normalize_cells(s.get("vram", "..."))
            if vram and vram not in ("No models loaded", "..."):
                lines.append(row("Видеопамять:", f"[bold yellow]{vram}[/bold yellow]"))
            else:
                lines.append(row("Видеопамять:", "[dim]нет данных[/dim]"))

        ctx_max = s.get("session_ctx_max", 8192)
        ctx_used = s.get("session_ctx", 0)
        ctx_pct = (ctx_used / ctx_max * 100) if ctx_max else 0
        cs = "green" if ctx_pct < 70 else "yellow" if ctx_pct < 90 else "red"
        lines.append(row("Диалог занял:", f"[{cs}]{ctx_used}/{ctx_max} ({ctx_pct:.1f}%)[/{cs}]"))
        lines.append(row("Объём запроса:", f"{s.get('last_req_ctx', 0)} токенов"))
        lines.append("")

        # Сырой обмен с моделью: «АПИ отдано» / «АПИ принято» (за запрос и всего).
        snap = net_meter.snapshot()
        rate = net_meter.recv_rate()
        lines.append(row("АПИ отдано:", self._fmt_bytes_raw(snap['sent_turn'])))
        lines.append(row("АПИ принято:", self._fmt_bytes_raw(snap['recv_turn'])))
        lines.append(row("АПИ отдано всего:", self._fmt_bytes_raw(snap['sent_total'])))
        lines.append(row("АПИ принято всего:", self._fmt_bytes_raw(snap['recv_total'])))
        lines.append(row("Скорость приёма:", f"{int(rate)} Б/с"))
        lines.append(row("Обращений:", f"{snap['req_turn']}   (всего {snap['req_total']})"))
        lines.append("")
        lines.append("[bold cyan]Заполнено памяти диалога:[/bold cyan]")

        if model_silence >= 30 or tool_hang:
            lines.append("[bold red]⚠ Похоже, зависло. Нажмите Esc, чтобы остановить "
                         "и продолжить с места.[/bold red]")

        # layout обновляем ТОЛЬКО когда меняется число строк (редко). Иначе
        # layout=False: не инвалидируем дерево и не «перерисовываем» чат на
        # каждом тике, но метрики обновляются 10 раз в секунду.
        text = "\n".join(lines)
        need_layout = (len(lines) != getattr(self, "_stats_lines", -1))
        self._stats_lines = len(lines)
        self.stats_rows.update(text, layout=need_layout)
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
        query = self._rich_escape(t.get("query", ""))
        if query:
            lines += ["", "[bold cyan]Запрос:[/bold cyan]", query]
        result = self._rich_escape(t.get("result", ""))
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
        # Надёжная загрузка: context.json → context.json.bak → messages.json
        # (битый context.json больше не роняет историю; см. SessionManager).
        if self.session_path:
            try:
                from core.session_manager import SessionManager
                history = SessionManager().load_history_entries(self.session_path) or []
            except Exception as e:
                self._add_static(f"[red]Ошибка загрузки истории: {e}[/red]")
        if history:
            # Панель запросов — по ВСЕЙ истории (дёшево). А тяжёлый рендер
            # виджетов делаем лениво: на длинной сессии это десятки секунд.
            for _idx, entry in enumerate(history):
                if entry.get("role") == "user" and entry.get("content"):
                    ts = None
                    raw_ts = entry.get("timestamp")
                    if raw_ts:
                        try:
                            ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")).timestamp()
                        except Exception:
                            ts = None
                    content = str(entry.get("content"))
                    # Мысль, ушедшая в поток, сохранена с пометкой в начале —
                    # восстанавливаем её вид (облачко + время отправки), чтобы
                    # после перезапуска она не выглядела обычным запросом.
                    if content.lstrip().startswith("(во время работы)"):
                        shown = content.replace("(во время работы)", "", 1).strip()
                        self._record_diag(shown, ts, kind="thought", index=_idx)
                    else:
                        self._record_diag(content, ts, index=_idx)
            self._history_all = history
            self._history_from = max(0, len(history) - HISTORY_INITIAL_ENTRIES)
            # Индикатор: рендер отложен, поэтому «Загрузка…» успевает показаться.
            self._loading_widget = self._add_static("[dim]⏳ Загрузка сессии…[/dim]")
            self.call_after_refresh(self._render_initial_history)
        else:
            # Новая сессия: показываем баннер с логотипом (после раскладки,
            # чтобы знать ширину поля вывода и автомасштабировать арт).
            self.call_after_refresh(self._mount_banner)

    def _remove_loading_widget(self) -> None:
        w = getattr(self, "_loading_widget", None)
        if w is not None:
            try:
                w.remove()
            except Exception:
                pass
            self._loading_widget = None

    def _render_initial_history(self) -> None:
        """Отрисовать только хвост истории; раннее — по кнопке/прокрутке."""
        try:
            self._render_history_range(self._history_from, len(self._history_all))
            if self._history_from > 0:
                self._ensure_load_older_button()
        finally:
            self._remove_loading_widget()
        self._auto_scroll_chat(animate=False)

    def _render_history_range(self, start: int, end: int) -> None:
        for entry in self._history_all[start:end]:
            self._render_history_entry(entry)

    def _ensure_load_older_button(self) -> None:
        if getattr(self, "_load_older_button", None) is not None:
            try:
                self._load_older_button.label = f"⤒ Показать более раннее ({self._history_from})"
            except Exception:
                pass
            return
        try:
            btn = Button(f"⤒ Показать более раннее ({self._history_from})", id="load_older")
            self._load_older_button = btn
            self.chat.mount(btn, before=0)
        except Exception:
            self._load_older_button = None

    def _load_older_history(self) -> None:
        """Догрузить предыдущую порцию истории наверх (без блокировки UI)."""
        if getattr(self, "_loading_older", False):
            return
        if self._history_from <= 0:
            return
        self._loading_older = True
        end = self._history_from
        start = max(0, end - HISTORY_BATCH_ENTRIES)
        btn = getattr(self, "_load_older_button", None)
        if btn is not None:
            try:
                btn.label = "⏳ Загрузка…"
            except Exception:
                pass
        container = Vertical(classes="history_batch")
        # mount асинхронный: рендерим в контейнер после следующего refresh,
        # когда он уже реально в дереве.
        try:
            if btn is not None:
                self.chat.mount(container, after=btn)
            else:
                self.chat.mount(container, before=0)
        except Exception:
            try:
                self.chat.mount(container)
            except Exception:
                pass
        self.call_after_refresh(self._render_older_batch, container, start, end, btn)

    def _render_older_batch(self, container, start: int, end: int, btn) -> None:
        try:
            self._render_target = container
            try:
                self._render_history_range(start, end)
            finally:
                self._render_target = None
            self._history_from = start
            if self._history_from <= 0:
                if btn is not None:
                    try:
                        btn.remove()
                    except Exception:
                        pass
                self._load_older_button = None
            else:
                self._ensure_load_older_button()
        finally:
            self._loading_older = False

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

    def _tool_call_code(self, name: str, args):
        """(code, kind) для подсветки тела вызова; (None, None) если нечего."""
        try:
            if name == "shell_exec" and isinstance(args, dict) \
                    and isinstance(args.get("command"), str):
                return format_shell_command(args["command"]), "bash"
            if isinstance(args, dict):
                return json.dumps(args, ensure_ascii=False, indent=2), "json"
        except Exception:
            pass
        return None, None

    def _tool_call_widgets(self, name: str, args):
        """Заголовок + подсвеченное тело вызова для спойлера истории сессии."""
        widgets = [Static(f"🔧 {name}", markup=False)]
        code, kind = self._tool_call_code(name, args)
        if code:
            widgets.append(Static(syntax_renderable(code, kind), markup=False))
        return widgets

    def _mount_widget(self, w):
        """Смонтировать виджет в чат или в текущую ленивую цель истории."""
        dst = self._render_target or self.chat
        dst.mount(w)
        if dst is self.chat:
            self._keep_focus()
        return w

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
            raw = str(content)
            self._add_static(f"[dim]━━━ {ts_str} ━━━[/dim]")
            if raw.lstrip().startswith("(во время работы)"):
                # Мысль, ушедшая в поток (после перезапуска) — показываем как мысль.
                shown = raw.replace("(во время работы)", "", 1).strip()
                self._add_static(
                    f"[bold blue]💭 Моя мысль (во время работы):[/bold blue] "
                    f"{self._rich_escape(shown)}")
            else:
                self._add_static(f"[bold blue]User:[/bold blue] {self._rich_escape(raw)}")
            self._add_static("")
        elif role == "assistant":
            self._add_static("[bold green]Assistant:[/bold green]")
            if thinking:
                self._mount_spoiler(self._spoiler_title("Thinking", thinking), Static(self._rich_escape(thinking)), collapsed=True)
            if content:
                try:
                    self._mount_widget(Markdown(normalize_cells(str(content))))
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
                    # В истории спойлеры СВЁРНУТЫ — раскрывать по клику.
                    self._mount_spoiler(title, *self._tool_call_widgets(name, args),
                                        collapsed=True)
        elif role == "tool":
            title = self._spoiler_title("Tool result", str(content)[:200])
            self._mount_spoiler(title, Static(f"[dim]{self._rich_escape(str(content)[:1000])}[/dim]"),
                                collapsed=True)
        elif role == "system":
            pass

    def append_user_message(self, content: str) -> None:
        self._record_diag(str(content))
        ts = datetime.now().strftime("%H:%M:%S")
        self._add_static(f"[dim]━━━ {ts} ━━━[/dim]")
        self._add_static(f"[bold blue]User:[/bold blue] {self._rich_escape(str(content))}")
        self._add_static("")
        self.chat.scroll_end(animate=False)

    def deliver_thought_block(self, text: str) -> None:
        """Мысль ушла в поток: показать её в чате как сообщение пользователя и
        отметить в панели промтов облачком с меткой времени отправки."""
        text = normalize_cells(str(text)).strip()
        if not text:
            return
        self._record_diag(text, kind="thought")
        ts = datetime.now().strftime("%H:%M:%S")
        self._add_static(f"[dim]━━━ {ts} ━━━[/dim]")
        self._add_static(
            f"[bold blue]💭 Моя мысль (во время работы):[/bold blue] {self._rich_escape(text)}")
        self._add_static("")
        try:
            self._update_diag()
            # Свежая строка теперь СВЕРХУ — прокручиваем список к началу.
            if self.diag_scroll is not None:
                self.diag_scroll.scroll_home(animate=False)
        except Exception:
            pass
        self.chat.scroll_end(animate=False)

    def reset_turn_state(self) -> None:
        """Сброс состояния, которое не должно переживать запрос пользователя.

        Вызывается ОДИН раз на запрос пользователя (не на каждую итерацию цикла
        инструментов). Сбрасывает отказ от повышения прав и флаг остановки:
        иначе Esc, зажатый между итерациями, затирался бы и модель продолжала
        генерировать.
        """
        self.dangerous_switch_denied = False
        self._stop_requested = False
        self._stop_logged = False
        if _pc is not None:
            _pc.clear_stop()

    def start_assistant_turn(self) -> None:
        self._flush_tool_spoilers()
        self._last_chunk_time = 0.0
        self._stream_started_at = time.time()
        self._first_token_at = None
        self._stream_active_time = 0.0
        self._prev_chunk_at = None
        self._stream_ui_last = 0.0
        self.stream_static = Static("", markup=True)
        self.chat.mount(self.stream_static)
        self._stream_content = ""
        self._stream_thinking = ""
        self._last_tool_content = ""
        self.is_streaming = True
        # ВАЖНО: здесь НЕ сбрасываем _stop_requested/clear_stop — функция
        # вызывается на каждой итерации цикла инструментов, и сброс гасил Esc.

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

    def _render_thought_queue(self) -> None:
        """Перерисовать нижнюю панель «мыслей»: чип + крестик отмены на каждую."""
        try:
            container = getattr(self, "thought_queue", None)
            if container is None:
                return
            container.remove_children()
            if not self._queued_inputs:
                container.remove_class("-visible")
                return
            container.add_class("-visible")
            chips = []
            for i, text in enumerate(self._queued_inputs):
                label = (text.splitlines()[0] if text else "").strip()
                if len(label) > 140:
                    label = label[:137] + "…"
                chips.append(Horizontal(
                    Static(f"💭 {label}", classes="thought_text"),
                    Button("✕", id=f"thought_del_{i}", classes="thought_del"),
                    classes="thought_chip",
                ))
            container.mount(*chips)
        except Exception:
            pass

    def take_queued_thoughts(self) -> str:
        """Атомарно забрать все мысли одним блоком (вызывать в UI-потоке).

        Возвращает склеенный текст (пустая строка, если мыслей нет) и очищает
        очередь вместе с панелью. Мысль не может уйти в поток дважды.
        """
        if not self._queued_inputs:
            return ""
        text = "\n\n".join(self._queued_inputs)
        self._queued_inputs = []
        self._render_thought_queue()
        self._update_queue_placeholder()
        return text

    def _remove_queued(self, idx: int) -> None:
        """Убрать мысль из очереди по крестику (до отправки в поток)."""
        try:
            if 0 <= idx < len(self._queued_inputs):
                self._queued_inputs.pop(idx)
        except Exception:
            return
        self._render_thought_queue()
        self._update_queue_placeholder()

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
            self._render_thought_queue()
            self.chat.scroll_end(animate=False)
        elif self.on_submit:
            self._submit_text(user_input)
        self.update_stats_display()

    def request_stop(self) -> None:
        """Мягкая остановка по Esc: только флаг, без убийства процессов.

        Сессия не должна умирать: запущенный через `process_control.run()`
        инструмент сам увидит флаг и аккуратно завершит своё дерево, а цикл хода
        штатно финализирует ответ и вернёт UI в покой. Никакого `kill_all` из
        обработчика клавиши — он гоняется с записью `context.json` и рвёт сессию.
        """
        self._stop_requested = True
        if _pc is not None:
            _pc.signal_stop()

    def turn_in_progress(self) -> bool:
        """Идёт ли ход: стрим модели ИЛИ работающий инструмент.

        Esc должен прерывать и во время инструмента, а не только во время
        генерации — раньше проверялся лишь `is_streaming`.
        """
        if getattr(self, "is_streaming", False):
            return True
        try:
            return any(t.get("status") == "running" for t in self.active_tools)
        except Exception:
            return False

    def _log_stop_once(self) -> None:
        if not self._stop_logged:
            self._stop_logged = True
            self.append_log("[dim]⏹ Остановлено. Прерываю действие и завершаю ход…[/dim]")

    def on_key(self, event) -> None:
        if event.key == "escape" and self.turn_in_progress():
            self.request_stop()
            self._log_stop_once()
            event.stop()

    def on_click(self, event) -> None:
        # Клик по флагу автосогласия в шапке — выключить его.
        try:
            if getattr(event, "widget", None) is self.auto_flag and self.dangerous_auto_confirm:
                self.dangerous_auto_confirm = False
                self.append_log("[yellow]Автосогласие отключено.[/yellow]")
                self._update_header()
                event.stop()
        except Exception:
            pass

    @staticmethod
    def _collapse_newlines(text: str) -> str:
        return re.sub(r'\n{3,}', '\n\n', text)

    def append_assistant_chunk(self, content: str = "", thinking: str = "",
                                tool_stream_json: str = "") -> None:
        if (content or thinking) and self._first_token_at is None:
            self._first_token_at = time.time()
        if thinking:
            self._stream_thinking += thinking
        if content:
            self._stream_content += content
        if tool_stream_json:
            self._last_tool_content = tool_stream_json
        # Троттлинг: не пересобираем ВЕСЬ накопленный текст на каждом чанке
        # (это O(n²) и насыщает UI — из-за этого воркер вис на call_from_thread
        # и не успевал среагировать на Esc). Текст копится всегда, а в Static
        # выводим не чаще ~10 раз в секунду.
        now = time.time()
        first_paint = self._stream_ui_last == 0.0
        if self.stream_static and (first_paint or now - self._stream_ui_last >= 0.1):
            self._stream_ui_last = now
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

    def update_stats(self, **data) -> None:
        # Принимаем весь набор полей из stats_data плюс любые дополнения
        # (server, retries и т.п.) без жёсткой сигнатуры.
        self.stats_data.update(data)
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
        stopped = self._stop_requested
        self.is_streaming = False
        self._last_chunk_time = 0.0
        if not self._queued_inputs:
            return
        if stopped:
            # Esc: НЕ продолжаем диалог сами. Возвращаем всю очередь мыслей в
            # поле ввода одним блоком и ждём, пока пользователь сам отправит.
            pending = "\n\n".join(self._queued_inputs)
            self._queued_inputs = []
            self._render_thought_queue()
            self._update_queue_placeholder()
            try:
                if self.input_widget is not None:
                    self.input_widget.text = pending
                    self._autosize_composer()
            except Exception:
                pass
            self.append_log("[dim]⏹ Остановлено. Мысли возвращены в строку ввода.[/dim]")
            return
        # Мысли, не успевшие попасть в поток на границе раунда, отдаём следующим
        # ходом одним блоком с нейтральной пометкой.
        joined = "\n\n".join(self._queued_inputs)
        self._queued_inputs = []
        self._render_thought_queue()
        self._update_queue_placeholder()
        self.deliver_thought_block(joined)
        text = "(во время работы)\n" + joined
        if self.on_submit:
            self.is_streaming = True
            self.on_submit(text)

    def append_log(self, text: str) -> None:
        # Текст лога приходит с rich-разметкой ([yellow]…[/yellow]) — не
        # экранируем скобки, иначе теги видны как обычный текст. Динамические
        # значения в этих строках экранируют вызывающие при необходимости.
        if self.chat:
            self._add_static(text)
            self.chat.scroll_end(animate=False)

    def clear_log(self) -> None:
        if self.chat:
            self.chat.remove_children()

    def show_confirmation_prompt(self, tool_name: str, args_display: str, warn_text: str = "",
                                 kind: str = "confirm") -> None:
        self._confirmation_event = threading.Event()
        self._confirmation_started_at = time.time()
        self._confirmation_result = False
        self._confirmation_reason = ""
        self._confirmation_kind = kind
        # Автосогласие действует только для подтверждений внутри dangerous mode,
        # не для запросов на переключение режима.
        if kind == "confirm" and self.dangerous_auto_confirm:
            self._confirmation_result = True
            self._confirmation_event.set()
            return
        # По умолчанию — ВСТРОЕННОЕ подтверждение в окне вывода (не накрывает
        # правые панели). Модальный ConfirmationScreen — только запасной путь,
        # если inline-слот недоступен.
        widget = ConfirmInline(
            tool_name, args_display, warn_text,
            on_resolve=self._apply_confirmation,
            kind=kind,
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
            kind=kind,
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

    def _apply_confirmation(self, confirmed: bool, reason: str = "", auto: bool = False) -> None:
        """Колбэк окна подтверждения — вызывается из UI-потока."""
        self._confirmation_result = confirmed
        self._confirmation_reason = reason
        kind = getattr(self, "_confirmation_kind", "confirm")
        if kind == "switch" and not confirmed:
            # Отказ от переключения фиксируем: повторно не спрашиваем.
            self.dangerous_switch_denied = True
        if confirmed and auto and kind == "confirm":
            self.dangerous_auto_confirm = True
            try:
                self.append_log("[yellow]⚠️ Автосогласие на опасные действия включено до конца сессии (флаг в шапке — клик, чтобы выключить).[/yellow]")
            except Exception:
                pass
        self._update_header()
        self._restore_input_placeholder()
        self.update_stats_display()
        if self._confirmation_event:
            self._confirmation_event.set()

    def _submit_text(self, user_input: str) -> None:
        """Отправить реплику пользователя в агент (общий путь для ввода и CLI-промпта)."""
        if not self.on_submit:
            return
        self._start_time = time.time()
        self._phase_started_at = time.time()
        self._stream_started_at = 0.0
        self._first_token_at = None
        self._stream_active_time = 0.0
        self._prev_chunk_at = None
        # Счётчики «за текущий запрос» обнуляем; сессионные остаются.
        self.stats_data["retries"] = 0
        self.stats_data["retry_wait"] = 0.0
        try:
            net_meter.reset_turn()
        except Exception:
            pass
        self.append_user_message(user_input)
        self.on_submit(user_input)
