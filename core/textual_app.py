"""
Textual приложение для Botinok — стриминг в Static, спойлеры Collapsible в общем потоке.
"""

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Input, Static, Collapsible
from textual.containers import Vertical, Horizontal
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel as RichPanel
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

SPOILER_PREVIEW = 80


class BotinokTextualApp(App):
    """Textual приложение для Botinok."""

    CSS = """
    Screen { layout: vertical; }
    #header { height: 3; min-height: 3; max-height: 3; padding: 0; margin: 0; }
    #main { height: 1fr; }
    #content { width: 2fr; height: 1fr; padding: 0; }
    #content_title { height: 1; color: green; padding: 0 1; }
    #chat { height: 1fr; border: solid green; padding: 0 1; overflow-y: auto; }
    #right { width: 1fr; }
    #stats { height: 1fr; }
    #tools { height: 1fr; }
    #footer { height: 3; }
    Input { height: 3; }
    Collapsible { width: 1fr; height: auto; background: transparent; border: none; padding: 0; }
    CollapsibleTitle { color: $text-muted; padding: 0 1; width: 1fr; }
    """

    def __init__(self, session_path: str = "", on_submit: Optional[Callable] = None,
                 on_slash_command: Optional[Callable] = None, **kwargs):
        super().__init__(**kwargs)
        self.session_path = session_path
        self.on_submit = on_submit
        self.on_slash_command = on_slash_command
        self.chat: Optional[Vertical] = None
        self.stream_static: Optional[Static] = None
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
        self._stream_content = ""
        self._stream_thinking = ""
        self._last_tool_content = ""
        self._tool_items: List[str] = []
        self._pending_content = ""
        self._has_pending_content = False
        self._confirmation_event: Optional[threading.Event] = None
        self._confirmation_result: bool = False
        self._stats_dirty = True
        self._tools_dirty = True
        self._footer_dirty = True
        self._chat_widgets: List = []

    def _spoiler_title(self, label: str, text: str) -> str:
        preview = text[:SPOILER_PREVIEW].replace("\n", " ")
        if len(text) > SPOILER_PREVIEW:
            preview += "..."
        ts = datetime.now().strftime("%H:%M:%S")
        return f"{label}: {preview}  {ts}"

    def _mount_spoiler(self, title: str, *content_widgets):
        c = Collapsible(*content_widgets, title=title, collapsed=True, collapsed_symbol="", expanded_symbol="")
        self.chat.mount(c)
        self.chat.scroll_end(animate=False)

    def _add_static(self, content, markup=True):
        s = Static(content, markup=markup)
        self.chat.mount(s)
        return s

    def compose(self) -> ComposeResult:
        self.header_display = Static("", id="header")
        yield self.header_display
        with Horizontal(id="main"):
            self.content_container = Vertical(id="content")
            with self.content_container:
                self.content_title = Static("Response", id="content_title")
                yield self.content_title
                self.chat = Vertical(id="chat")
                yield self.chat
            with Vertical(id="right"):
                self.stats_display = Static("", id="stats")
                yield self.stats_display
                self.tools_display = Static("", id="tools")
                yield self.tools_display
        self.footer_display = Static("", id="footer")
        yield self.footer_display
        yield Input(placeholder="Введите ваш вопрос (exit = выход)...", id="input")

    def on_mount(self) -> None:
        self.load_history()
        try:
            self.set_focus(self.query_one("#input", Input))
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
        return RichPanel(
            Text(f"{agent_type}{danger_tag} | Model: {self.model_name} | Context: {ctx} | {vram}",
                 justify="center", style=header_style),
            style=panel_style,
        )

    def _render_footer(self) -> RichPanel:
        return RichPanel(
            Text(f"Prompt: {self.current_prompt}", overflow="ellipsis", style="dim"),
            title="[bold cyan]Diagnostic Log[/bold cyan]", border_style="cyan",
        )

    def _render_stats(self) -> RichPanel:
        s = self.stats_data
        table = Table(show_header=False, box=None, padding=(0, 1))
        active_statuses = [
            "Generating...", "Waiting for tool call...", "Calling Tools...",
            "Resuming generation...", "Checking Memory...", "Unloading Models...",
            "Forced VRAM Cleanup...", "Connecting...", "Tool-mode parsing..."
        ]
        activity = ""
        if s["status"] in active_statuses or "Tool:" in s["status"]:
            sp = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            activity = f"[bold magenta]{sp[int(time.time()*5)%len(sp)]}[/bold magenta]"
        table.add_row("[cyan]Status:[/cyan]", f"[bold]{s['status']}[/bold] {activity}")
        table.add_row("[cyan]Elapsed:[/cyan]", f"{s['elapsed']:.1f}s")
        table.add_row("[cyan]No chunks:[/cyan]", f"{s['no_chunks']:.1f}s")
        table.add_row("[cyan]TTFT:[/cyan]", f"[bold yellow]{s['ttft']}[/bold yellow]")
        table.add_row("[cyan]Thinking:[/cyan]", f"[bold yellow]{s['thinking_tokens']}[/bold yellow]")
        table.add_row("[cyan]Response:[/cyan]", f"[bold green]{s['response_tokens']}[/bold green]")
        table.add_row("[cyan]Stream Tool:[/cyan]", f"[bold magenta]{s['stream_tool_tokens']}[/bold magenta]")
        table.add_row("[cyan]Final Tool:[/cyan]", f"[bold magenta]{s['final_tool_tokens']}[/bold magenta]")
        table.add_row("[cyan]TPS:[/cyan]", f"[bold green]{s['tps']:.2f}[/bold green]")
        table.add_row("[cyan]VRAM:[/cyan]", f"[bold yellow]{s['vram']}[/bold yellow]")
        table.add_row("", "")
        ctx_max = s.get("session_ctx_max", 8192)
        ctx_used = s.get("session_ctx", 0)
        ctx_pct = (ctx_used / ctx_max * 100) if ctx_max else 0
        cs = "green" if ctx_pct < 70 else "yellow" if ctx_pct < 90 else "red"
        table.add_row("[cyan]SessionCtx:[/cyan]", f"[{cs}]{ctx_used}/{ctx_max} ({ctx_pct:.1f}%)[/{cs}]")
        lr_ctx = s.get("last_req_ctx", 0)
        lr_pct = (lr_ctx / ctx_max * 100) if ctx_max else 0
        lr_cs = "green" if lr_pct < 70 else "yellow" if lr_pct < 90 else "red"
        table.add_row("[cyan]LastReqCtx:[/cyan]", f"[{lr_cs}]{lr_ctx}/{ctx_max} ({lr_pct:.1f}%)[/{lr_cs}]")
        table.add_row("", "")
        table.add_row("[bold cyan]Context Window Fill:[/bold cyan]", "")
        progress = Progress(BarColumn(bar_width=None, complete_style=cs, finished_style=cs),
                            TextColumn("{task.percentage:>5.1f}%"), expand=True)
        progress.add_task("ctx", total=100.0, completed=float(ctx_pct))
        return RichPanel(Group(table, progress), title="[bold yellow]Performance[/bold yellow]",
                         border_style="yellow", expand=True)

    def _render_tools(self) -> RichPanel:
        if not self.active_tools:
            return RichPanel(Text("No active tools", style="dim"),
                             title="[bold cyan]Tools Activity[/bold cyan]", border_style="cyan")
        table = Table(show_header=True, header_style="bold yellow", box=None, padding=(0, 1), expand=True)
        table.add_column("Tool", style="cyan")
        table.add_column("Query", style="white", overflow="ellipsis")
        table.add_column("Status", style="yellow")
        table.add_column("Size", style="green")
        for t in reversed(self.active_tools):
            ss = "yellow" if t["status"] == "running" else "green" if t["status"] == "completed" else "red"
            sz = f"{t['size_kb']:.2f} KB" if t['size_kb'] > 0 else "..."
            q = t['query'][:20] + "..." if len(t['query']) > 20 else t['query']
            table.add_row(t["name"], q, f"[{ss}]{t['status']}[/{ss}]", sz)
        return RichPanel(table, title="[bold cyan]Tools Activity[/bold cyan]", border_style="cyan")

    def update_stats_display(self) -> None:
        if self.header_display:
            self.header_display.update(self._render_header())
        if self.content_title and self.content_container and self.chat and self._stats_dirty:
            try:
                h = self.content_container.size.height if self.content_container else 20
                self.content_title.update(f"Response (Lines: ~{h})")
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

    def _rich_escape(self, text: str) -> str:
        return text.replace("[", r"\[")

    def load_history(self) -> None:
        if not self.session_path:
            return
        context_path = os.path.join(self.session_path, "context.json")
        if not os.path.exists(context_path):
            return
        try:
            with open(context_path, "r", encoding="utf-8", errors="ignore") as f:
                context = json.load(f)
            for entry in context.get("history", []):
                self._render_history_entry(entry)
            self.chat.scroll_end()
        except Exception as e:
            self._add_static(f"[red]Ошибка загрузки истории: {e}[/red]")

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
            self._add_static(f"[bold blue]User:[/bold blue] {content}")
            self._add_static("")
        elif role == "assistant":
            if thinking:
                self._mount_spoiler(self._spoiler_title("Thinking", thinking), Static(thinking))
            self._add_static("[bold green]Assistant:[/bold green]")
            if content:
                self._add_static(RichMarkdown(content))
                self._add_static("")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "unknown")
                    try:
                        args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                    except Exception:
                        args = {}
                    title = self._spoiler_title(name, json.dumps(args, ensure_ascii=False))
                    self._mount_spoiler(title, Static(f"🔧 {name}({json.dumps(args, ensure_ascii=False)})"))
        elif role == "tool":
            title = self._spoiler_title("Tool result", str(content)[:200])
            self._mount_spoiler(title, Static(f"[dim]{str(content)[:1000]}[/dim]"))
        elif role == "system":
            pass

    def append_user_message(self, content: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._add_static(f"[dim]━━━ {ts} ━━━[/dim]")
        self._add_static(f"[bold blue]User:[/bold blue] {content}")
        self._add_static("")
        self.chat.scroll_end(animate=False)

    def start_assistant_turn(self) -> None:
        self._flush_tool_spoilers()
        self._add_static("[bold green]Assistant:[/bold green]")
        self.stream_static = Static("", markup=True)
        self.chat.mount(self.stream_static)
        self._stream_content = ""
        self._stream_thinking = ""
        self._last_tool_content = ""

    def append_assistant_chunk(self, content: str = "", thinking: str = "",
                                tool_stream_json: str = "") -> None:
        if thinking:
            self._stream_thinking += thinking
        if content:
            self._stream_content += content
            if self.stream_static:
                self.stream_static.update(self._rich_escape(self._stream_content))
        if tool_stream_json:
            self._last_tool_content = tool_stream_json
            if self.stream_static:
                self.stream_static.update(f"[bold magenta]Streaming Tool JSON...[/bold magenta]")

    def finalize_assistant_turn(self, content: str, thinking: str = "",
                                tool_calls: Optional[list] = None) -> None:
        final_thinking = thinking or self._stream_thinking
        if final_thinking:
            title = self._spoiler_title("Thinking", final_thinking)
            self._mount_spoiler(title, Static(final_thinking))

        if self._last_tool_content:
            title = self._spoiler_title("Tool JSON", self._last_tool_content)
            self._mount_spoiler(title, Static(f"[dim]{self._last_tool_content}[/dim]"))
            self._last_tool_content = ""

        final_content = content or self._stream_content
        if self.stream_static:
            self.stream_static.remove()
            self.stream_static = None

        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "unknown")
                try:
                    args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                except Exception:
                    args = {}
                args_str = json.dumps(args, ensure_ascii=False)[:80]
                self._tool_items.append(f"🔧 {name}({args_str})")

        self._pending_content = final_content
        self._has_pending_content = bool(final_content)

        if not tool_calls:
            self._write_pending_content()

    def _write_pending_content(self) -> None:
        if self._has_pending_content and self._pending_content:
            try:
                self._add_static(RichMarkdown(self._pending_content))
            except Exception:
                self._add_static(self._rich_escape(self._pending_content))
            self._add_static("")
        self._has_pending_content = False
        self._pending_content = ""

    def _flush_tool_spoilers(self) -> None:
        if self._tool_items:
            text = "\n".join(self._tool_items)
            title = self._spoiler_title("Tool calls", text)
            self._mount_spoiler(title, Static(f"[dim]{text}[/dim]"))
            self._tool_items = []
        self._write_pending_content()

    def append_tool_result(self, tool_name: str, result: str) -> None:
        self._tool_items.append(f"🔧 Tool: {tool_name}")
        for line in str(result).split('\n')[:5]:
            self._tool_items.append(line)
        if len(str(result).split('\n')) > 5:
            self._tool_items.append("...")
        self._tool_items.append("")

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

    def append_log(self, text: str) -> None:
        if self.chat:
            self._add_static(text)
            self.chat.scroll_end(animate=False)

    def clear_log(self) -> None:
        if self.chat:
            self.chat.remove_children()

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
        self._add_static(msg)
        input_widget = self.query_one("#input", Input)
        input_widget.placeholder = "подтвердите действие (y/n)..."

    def wait_for_confirmation(self, timeout: float = 300) -> bool:
        if self._confirmation_event:
            self._confirmation_event.wait(timeout=timeout)
            return self._confirmation_result
        return False

    def _restore_input_placeholder(self) -> None:
        try:
            self.query_one("#input", Input).placeholder = "Введите ваш вопрос (exit = выход)..."
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
            self._add_static(f"[dim]━━━ {datetime.now().strftime('%H:%M:%S')} ━━━[/dim]")
            self._add_static(f"[bold blue]User:[/bold blue] {user_input}")
            self._add_static("")
            self.on_submit(user_input)
        self.update_stats_display()
