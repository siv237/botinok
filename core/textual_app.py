"""
Textual приложение для Botinok с RichLog для истории и Input для ввода.
Стилизовано максимально близко к старому Rich Live интерфейсу (BotVisualizer).
"""

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Input, Static
from textual.containers import Vertical, Horizontal
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn
from rich.console import Group
from rich.text import Text
from typing import Optional, Callable, List
import json
import os
import time
import threading
from datetime import datetime


class BotinokTextualApp(App):
    """Textual приложение для Botinok, стилизованное под старый Rich Live UI."""

    CSS = """
    Screen { layout: vertical; }
    #header { height: 3; min-height: 3; max-height: 3; padding: 0; margin: 0; }
    #main { height: 1fr; }
    #content { width: 2fr; height: 1fr; padding: 0; }
    #content_title { height: 1; color: green; padding: 0 1; }
    #content_log { height: 1fr; border: solid green; padding: 0 1; }
    #right { width: 1fr; }
    #stats { height: 1fr; }
    #tools { height: 1fr; }
    #footer { height: 3; }
    Input { height: 3; }
    """

    def __init__(self, session_path: str = "", on_submit: Optional[Callable] = None,
                 on_slash_command: Optional[Callable] = None, **kwargs):
        super().__init__(**kwargs)
        self.session_path = session_path
        self.on_submit = on_submit
        self.on_slash_command = on_slash_command
        self.rich_log: Optional[RichLog] = None
        self.stats_display: Optional[Static] = None
        self.tools_display: Optional[Static] = None
        self.header_display: Optional[Static] = None
        self.footer_display: Optional[Static] = None
        self.content_container: Optional[Vertical] = None
        self.content_title: Optional[Static] = None
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
        self._start_time = time.time()
        self._last_chunk_time = 0.0
        self._stream_content_buffer = ""
        self._stream_thinking_buffer = ""
        self._stream_start_index = -1
        self._confirmation_event: Optional[threading.Event] = None
        self._confirmation_result: bool = False
        self._last_refresh_time = 0.0
        self._REFRESH_INTERVAL = 0.03
        self._refresh_pending = False
        self._stats_dirty = True
        self._tools_dirty = True
        self._footer_dirty = True

    def compose(self) -> ComposeResult:
        self.header_display = Static("", id="header")
        yield self.header_display
        with Horizontal(id="main"):
            self.content_container = Vertical(id="content")
            with self.content_container:
                self.content_title = Static("Response", id="content_title")
                yield self.content_title
                yield RichLog(markup=True, auto_scroll=True, wrap=True, highlight=True, min_width=0, id="content_log")
            with Vertical(id="right"):
                self.stats_display = Static("", id="stats")
                yield self.stats_display
                self.tools_display = Static("", id="tools")
                yield self.tools_display
        self.footer_display = Static("", id="footer")
        yield self.footer_display
        yield Input(placeholder="Введите ваш вопрос (exit = выход)...", id="input")

    def on_mount(self) -> None:
        self.rich_log = self.query_one("#content_log", RichLog)
        self.load_history()
        try:
            self.set_focus(self.query_one("#input", Input))
        except Exception:
            pass
        if hasattr(self, '_vram_prep_fn') and self._vram_prep_fn:
            import threading
            t = threading.Thread(target=self._vram_prep_fn, daemon=True)
            t.start()
        self.set_interval(self._REFRESH_INTERVAL, self._flush_refresh)
        self.set_interval(0.1, self._tick_stats)
        self._stats_dirty = True
        self._tools_dirty = True
        self._footer_dirty = True
        self.update_stats_display()

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
        active = ("Generating...", "Connecting...", "Processing tool calls...", "Checking Memory...")
        if self.stats_data["status"] in active:
            self.stats_data["elapsed"] = now - self._start_time
            self._stats_dirty = True
        if self._last_chunk_time > 0:
            new_val = now - self._last_chunk_time
            if abs(new_val - self.stats_data["no_chunks"]) > 0.1:
                self.stats_data["no_chunks"] = new_val
                self._stats_dirty = True
        if self._stats_dirty or self._tools_dirty or self._footer_dirty:
            self.update_stats_display()

    def _render_header(self):
        danger_tag = " | DANGEROUS MODE: ON" if self.dangerous_mode else ""
        agent_type = "PROOFREADER AGENT" if self.is_proofreader else "BOTINOK AGENT"
        BLUE_BG = "#0055aa"
        if self.dangerous_mode:
            header_style = "bold white on red"
            panel_style = "red"
        elif self.is_proofreader:
            header_style = "bold black on yellow"
            panel_style = "yellow"
        else:
            header_style = f"bold white on {BLUE_BG}"
            panel_style = BLUE_BG
        vram = self.stats_data.get("vram", "...")
        ctx = self.stats_data.get("session_ctx_max", 8192)
        return Panel(
            Text(
                f"{agent_type}{danger_tag} | Model: {self.model_name} | Context: {ctx} | {vram}",
                justify="center",
                style=header_style,
            ),
            style=panel_style,
        )

    def _render_footer(self) -> Panel:
        return Panel(
            Text(f"Prompt: {self.current_prompt}", overflow="ellipsis", style="dim"),
            title="[bold cyan]Diagnostic Log[/bold cyan]",
            border_style="cyan",
        )

    def _render_stats(self) -> Panel:
        s = self.stats_data
        elapsed = s.get("elapsed", 0.0)
        no_chunks = s.get("no_chunks", 0.0)
        ttft = s.get("ttft", "...")
        tps = s.get("tps", 0.0)
        vram = s.get("vram", "...")
        thinking_tokens = s.get("thinking_tokens", 0)
        response_tokens = s.get("response_tokens", 0)
        stream_tool_tokens = s.get("stream_tool_tokens", 0)
        final_tool_tokens = s.get("final_tool_tokens", 0)
        status = s.get("status", "Ready")

        table = Table(show_header=False, box=None, padding=(0, 1))

        active_statuses = [
            "Generating...", "Waiting for tool call...", "Calling Tools...",
            "Resuming generation...", "Checking Memory...", "Unloading Models...",
            "Forced VRAM Cleanup...", "Connecting...", "Tool-mode parsing..."
        ]
        activity = ""
        if status in active_statuses or "Tool:" in status:
            spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            spinner_index = int(time.time() * 5) % len(spinner_chars)
            activity = f"[bold magenta]{spinner_chars[spinner_index]}[/bold magenta]"

        table.add_row("[cyan]Status:[/cyan]", f"[bold]{status}[/bold] {activity}")
        table.add_row("[cyan]Elapsed:[/cyan]", f"{elapsed:.1f}s")
        table.add_row("[cyan]No chunks:[/cyan]", f"{no_chunks:.1f}s")
        table.add_row("[cyan]TTFT:[/cyan]", f"[bold yellow]{ttft}[/bold yellow]")
        table.add_row("[cyan]Thinking:[/cyan]", f"[bold yellow]{thinking_tokens}[/bold yellow]")
        table.add_row("[cyan]Response:[/cyan]", f"[bold green]{response_tokens}[/bold green]")
        table.add_row("[cyan]Stream Tool:[/cyan]", f"[bold magenta]{stream_tool_tokens}[/bold magenta]")
        table.add_row("[cyan]Final Tool:[/cyan]", f"[bold magenta]{final_tool_tokens}[/bold magenta]")
        table.add_row("[cyan]TPS:[/cyan]", f"[bold green]{tps:.2f}[/bold green]")
        table.add_row("[cyan]VRAM:[/cyan]", f"[bold yellow]{vram}[/bold yellow]")
        table.add_row("", "")

        session_ctx_max = s.get("session_ctx_max", 8192)
        session_ctx = s.get("session_ctx", 0)
        session_ctx_pct = (session_ctx / session_ctx_max) * 100 if session_ctx_max > 0 else 0
        session_ctx_style = "green" if session_ctx_pct < 70 else "yellow" if session_ctx_pct < 90 else "red"
        table.add_row("[cyan]SessionCtx:[/cyan]", f"[{session_ctx_style}]{session_ctx}/{session_ctx_max} ({session_ctx_pct:.1f}%)[/{session_ctx_style}]")

        last_req_ctx = s.get("last_req_ctx", 0)
        last_req_ctx_pct = (last_req_ctx / session_ctx_max) * 100 if session_ctx_max > 0 else 0
        last_req_ctx_style = "green" if last_req_ctx_pct < 70 else "yellow" if last_req_ctx_pct < 90 else "red"
        table.add_row("[cyan]LastReqCtx:[/cyan]", f"[{last_req_ctx_style}]{last_req_ctx}/{session_ctx_max} ({last_req_ctx_pct:.1f}%)[/{last_req_ctx_style}]")

        table.add_row("", "")
        table.add_row("[bold cyan]Context Window Fill:[/bold cyan]", "")

        progress = Progress(
            BarColumn(bar_width=None, complete_style=session_ctx_style, finished_style=session_ctx_style),
            TextColumn("{task.percentage:>5.1f}%"),
            expand=True,
        )
        progress.add_task("ctx", total=100.0, completed=float(session_ctx_pct))

        return Panel(
            Group(table, progress),
            title="[bold yellow]Performance[/bold yellow]",
            border_style="yellow",
            expand=True,
        )

    def _render_tools(self) -> Panel:
        if not self.active_tools:
            return Panel(
                Text("No active tools", style="dim"),
                title="[bold cyan]Tools Activity[/bold cyan]",
                border_style="cyan",
            )

        table = Table(show_header=True, header_style="bold yellow", box=None, padding=(0, 1), expand=True)
        table.add_column("Tool", style="cyan")
        table.add_column("Query", style="white", overflow="ellipsis")
        table.add_column("Status", style="yellow")
        table.add_column("Size", style="green")

        for tool in reversed(self.active_tools):
            status_style = "yellow" if tool["status"] == "running" else "green" if tool["status"] == "completed" else "red"
            size_display = f"{tool['size_kb']:.2f} KB" if tool['size_kb'] > 0 else "..."
            query_short = tool['query'][:20] + "..." if len(tool['query']) > 20 else tool['query']
            table.add_row(
                tool["name"],
                query_short,
                f"[{status_style}]{tool['status']}[/{status_style}]",
                size_display
            )
        return Panel(
            table,
            title="[bold cyan]Tools Activity[/bold cyan]",
            border_style="cyan",
        )

    def update_stats_display(self) -> None:
        if self.header_display:
            self.header_display.update(self._render_header())
        if self.content_title and self.content_container and self.rich_log and self._stats_dirty:
            try:
                h = self.content_container.size.height if self.content_container else 20
                lines_count = len(self.rich_log.lines) if self.rich_log else 0
                self.content_title.update(f"Response (Lines: {lines_count}/{max(h, 1)})")
            except Exception:
                self.content_title.update("Response")
        if self.stats_display and self._stats_dirty:
            self.stats_display.update(self._render_stats())
            self._stats_dirty = False
        if self.tools_display and self._tools_dirty:
            self.tools_display.update(self._render_tools())
            self._tools_dirty = False
        if self.footer_display and self._footer_dirty:
            self.footer_display.update(self._render_footer())
            self._footer_dirty = False

    def load_history(self) -> None:
        if not self.session_path:
            return
        context_path = os.path.join(self.session_path, "context.json")
        if not os.path.exists(context_path):
            return
        try:
            with open(context_path, "r", encoding="utf-8", errors="ignore") as f:
                context = json.load(f)
            history = context.get("history", [])
            self.rich_log.clear()
            for entry in history:
                self._add_entry(
                    entry.get("role", ""),
                    entry.get("content", ""),
                    entry.get("thinking", ""),
                    entry.get("timestamp", ""),
                    entry.get("tool_calls", []),
                )
            self.rich_log.scroll_end()
        except Exception as e:
            self.rich_log.write(f"[red]Ошибка загрузки истории: {e}[/red]")

    def _rich_escape_tags(self, text: str) -> str:
        return text.replace("[", r"\[")

    def _write_markdown(self, text: str) -> None:
        if not text:
            return
        try:
            self.rich_log.write(Markdown(text))
        except Exception:
            self.rich_log.write(self._rich_escape_tags(text))

    def _add_entry(self, role: str, content: str, thinking: str,
                   timestamp: str, tool_calls: Optional[list] = None) -> None:
        if not role:
            return
        ts_str = ""
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                ts_str = dt.strftime("%H:%M:%S")
            except Exception:
                ts_str = str(timestamp)[:8]
        if role == "user":
            self.rich_log.write(f"[dim]━━━ {ts_str} ━━━[/dim]")
            self.rich_log.write(f"[bold blue]User:[/bold blue] ")
            self.rich_log.write(content)
            self.rich_log.write("")
        elif role == "assistant":
            if thinking:
                self.rich_log.write("[dim]─── thinking ───[/dim]")
                self.rich_log.write(f"[dim]{thinking}[/dim]")
                self.rich_log.write("")
            if content:
                self.rich_log.write("[bold green]Assistant:[/bold green]")
                self._write_markdown(content)
                self.rich_log.write("")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "unknown")
                    try:
                        args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                    except Exception:
                        args = {}
                    args_str = json.dumps(args, ensure_ascii=False)[:80]
                    self.rich_log.write(f"[bold yellow]🔧 {tool_name}({args_str})[/bold yellow]")
        elif role == "tool":
            content_str = str(content)
            lines = content_str.split('\n')[:5]
            for line in lines:
                self.rich_log.write(f"[dim]{line}[/dim]")
            if len(content_str.split('\n')) > 5:
                self.rich_log.write("[dim]...[/dim]")
            self.rich_log.write("")
        elif role == "system":
            pass

    def append_user_message(self, content: str) -> None:
        now = datetime.now().isoformat()
        self._add_entry("user", content, "", now)

    def start_assistant_turn(self) -> None:
        self.rich_log.write("[bold green]Assistant:[/bold green]")
        self._stream_start_index = len(self.rich_log.lines)
        self._stream_content_buffer = ""
        self._stream_thinking_buffer = ""

    def _refresh_live_content(self) -> None:
        if not self.rich_log or self._stream_start_index < 0:
            return
        now = time.time()
        if now - self._last_refresh_time < self._REFRESH_INTERVAL:
            self._refresh_pending = True
            return
        self._last_refresh_time = now
        self._refresh_pending = False
        self._do_refresh()

    def _flush_refresh(self) -> None:
        if self._refresh_pending:
            self._last_refresh_time = time.time()
            self._refresh_pending = False
            self._do_refresh()

    def _do_refresh(self):
        self.rich_log.lines = self.rich_log.lines[:self._stream_start_index]
        self.rich_log._line_cache.clear()
        if self._stream_content_buffer:
            self.rich_log.write(self._rich_escape_tags(self._stream_content_buffer))
        self.rich_log.refresh()

    def append_assistant_chunk(self, content: str = "", thinking: str = "",
                                tool_stream_json: str = "") -> None:
        if thinking:
            self._stream_thinking_buffer += thinking
        if content:
            self._stream_content_buffer += content
            self._refresh_live_content()
        if tool_stream_json:
            now = datetime.now().strftime("%H:%M:%S")
            self.rich_log.write(f"[dim]{now}[/dim] [bold yellow]Tool JSON:[/bold yellow]")
            self.rich_log.write(f"[dim]{tool_stream_json}[/dim]")

    def finalize_assistant_turn(self, content: str, thinking: str = "",
                                tool_calls: Optional[list] = None) -> None:
        if self.rich_log and self._stream_start_index >= 0:
            self.rich_log.lines = self.rich_log.lines[:self._stream_start_index]
            self.rich_log._line_cache.clear()
            self._stream_start_index = -1

        final_thinking = thinking or self._stream_thinking_buffer
        if final_thinking:
            self.rich_log.write("[dim]─── thinking ───[/dim]")
            self.rich_log.write(f"[dim]{final_thinking}[/dim]")
            self.rich_log.write("")
        self._stream_thinking_buffer = ""

        final_content = content or self._stream_content_buffer
        self._stream_content_buffer = ""
        if final_content:
            self._write_markdown(final_content)
            self.rich_log.write("")

        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "unknown")
                try:
                    args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                except Exception:
                    args = {}
                args_str = json.dumps(args, ensure_ascii=False)[:80]
                self.rich_log.write(f"[bold yellow]🔧 {tool_name}({args_str})[/bold yellow]")

    def append_tool_result(self, tool_name: str, result: str) -> None:
        self.rich_log.write(f"[bold yellow]🔧 Tool: {tool_name}[/bold yellow]")
        content_str = str(result)
        lines = content_str.split('\n')[:5]
        for line in lines:
            self.rich_log.write(f"[dim]{line}[/dim]")
        if len(content_str.split('\n')) > 5:
            self.rich_log.write("[dim]...[/dim]")
        self.rich_log.write("")

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
        self.active_tools.append({
            "name": name, "query": query, "status": status,
            "size_kb": size_kb, "start_time": time.time()
        })
        self._tools_dirty = True
        self.update_stats_display()

    def update_tool_activity(self, name: str, status: str = "completed", size_kb: float = 0, query: str = "") -> None:
        for tool in reversed(self.active_tools):
            if tool["name"] == name:
                tool["status"] = status
                tool["size_kb"] = size_kb
                if query:
                    tool["query"] = query
                break
        self._tools_dirty = True
        self.update_stats_display()

    def clear_log(self) -> None:
        if self.rich_log:
            self.rich_log.clear()

    def show_confirmation_prompt(self, tool_name: str, args_display: str, warn_text: str) -> None:
        self._confirmation_event = threading.Event()
        self._confirmation_result = False
        msg = (
            f"\n[bold red]⚠️  ПОДТВЕРДИТЕ ОПАСНОЕ ДЕЙСТВИЕ[/bold red]\n"
            f"[bold yellow]Инструмент:[/bold yellow] {tool_name}\n"
            f"[bold yellow]Аргументы:[/bold yellow] {args_display}\n"
            f"{warn_text}\n"
            f"[bold cyan]Введите 'y' для подтверждения или 'n' для отмены:[/bold cyan]"
        )
        self.rich_log.write(msg)
        self.rich_log.write("")
        input_widget = self.query_one("#input", Input)
        input_widget.placeholder = "подтвердите действие (y/n)..."

    def wait_for_confirmation(self, timeout: float = 300) -> bool:
        if self._confirmation_event:
            self._confirmation_event.wait(timeout=timeout)
            return self._confirmation_result
        return False

    def _restore_input_placeholder(self) -> None:
        try:
            input_widget = self.query_one("#input", Input)
            input_widget.placeholder = "Введите ваш вопрос (exit = выход)..."
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value
        event.input.value = ""
        self.current_prompt = user_input
        self._footer_dirty = True
        if self._confirmation_event and self._confirmation_event.is_set() is False:
            self._confirmation_result = user_input.strip().lower() in ("y", "yes", "д", "да")
            self._confirmation_event.set()
            self._restore_input_placeholder()
            self.update_stats_display()
            return
        if user_input.startswith("/"):
            if self.on_slash_command:
                self.on_slash_command(user_input)
        elif self.on_submit:
            self._start_time = time.time()
            self.rich_log.write(f"[dim]━━━ {datetime.now().strftime('%H:%M:%S')} ━━━[/dim]")
            self.rich_log.write(f"[bold blue]User:[/bold blue] {user_input}")
            self.rich_log.write("")
            self.on_submit(user_input)
        self.update_stats_display()
