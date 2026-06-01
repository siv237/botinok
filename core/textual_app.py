"""
Textual приложение для Botinok с RichLog для истории и Input для ввода.
"""

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Header, Footer, Input, Static
from textual.containers import Vertical, Horizontal
from textual.geometry import Size
from rich.markdown import Markdown
from rich.panel import Panel
from typing import Optional, Callable, List
import json
import os
import time
from datetime import datetime


class BotinokTextualApp(App):
    """Textual приложение для Botinok."""

    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #left { width: 2fr; min-width: 40; }
    #right { width: 1fr; max-width: 30; }
    RichLog { height: 100%; }
    #right_panel { layout: vertical; height: 100%; }
    #status_line { height: auto; color: $text-muted; background: $surface-darken-1; padding: 0 1; }
    #stats { height: auto; }
    #tools { height: 1fr; }
    #ctx_bars { height: auto; padding: 0 1; background: $surface-darken-1; }
    Input:focus { border: tall $success; }
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
        self.ctx_bars: Optional[Static] = None
        self.status_line: Optional[Static] = None
        self.model_name = ""
        self.dangerous_mode = False
        self.is_proofreader = False
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield RichLog(markup=True, auto_scroll=True, wrap=True, highlight=True, min_width=0, id="content")
            with Vertical(id="right"):
                with Vertical(id="right_panel"):
                    self.status_line = Static("", id="status_line")
                    yield self.status_line
                    self.stats_display = Static(self._render_stats(), id="stats")
                    yield self.stats_display
                    self.ctx_bars = Static(self._render_ctx_bars(), id="ctx_bars")
                    yield self.ctx_bars
                    self.tools_display = Static(self._render_tools(), id="tools")
                    yield self.tools_display
        yield Input(placeholder="Введите ваш вопрос (exit = выход)...", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.rich_log = self.query_one(RichLog)
        self.load_history()
        try:
            self.set_focus(self.query_one("#input", Input))
        except Exception:
            pass
        if hasattr(self, '_vram_prep_fn') and self._vram_prep_fn:
            import threading
            t = threading.Thread(target=self._vram_prep_fn, daemon=True)
            t.start()
        self.set_interval(1, self._tick_stats)

    def set_model_info(self, model: str, dangerous: bool = False, proofreader: bool = False):
        self.model_name = model
        self.dangerous_mode = dangerous
        self.is_proofreader = proofreader
        self.update_stats_display()

    def report_chunk(self) -> None:
        self._last_chunk_time = time.time()

    def _tick_stats(self) -> None:
        now = time.time()
        active = ("Generating...", "Connecting...", "Processing tool calls...", "Checking Memory...")
        if self.stats_data["status"] in active:
            self.stats_data["elapsed"] = now - self._start_time
        if self._last_chunk_time > 0:
            self.stats_data["no_chunks"] = now - self._last_chunk_time
        self.update_stats_display()

    def _render_status_line(self) -> str:
        parts = []
        if self.is_proofreader:
            parts.append("[bold black on yellow]PROOFREADER[/bold black on yellow]")
        else:
            parts.append("[bold white on blue]BOTINOK[/bold white on blue]")
        if self.model_name:
            parts.append(f"[cyan]{self.model_name}[/cyan]")
        if self.dangerous_mode:
            parts.append("[bold red]⚠ DANGEROUS[/bold red]")
        return " ".join(parts)

    def _render_ctx_bars(self) -> str:
        s = self.stats_data
        session_pct = (s['session_ctx'] / s['session_ctx_max']) * 100 if s['session_ctx_max'] > 0 else 0
        bw = 20
        s_filled = int(bw * session_pct / 100)
        s_bar = "█" * s_filled + "░" * (bw - s_filled)
        s_style = "green" if session_pct < 70 else "yellow" if session_pct < 90 else "red"
        last_pct = (s['last_req_ctx'] / s['last_req_ctx_max']) * 100 if s['last_req_ctx_max'] > 0 else 0
        l_filled = int(bw * last_pct / 100)
        l_bar = "█" * l_filled + "░" * (bw - l_filled)
        l_style = "green" if last_pct < 70 else "yellow" if last_pct < 90 else "red"
        return f"[{s_style}]Session {s_bar}[/{s_style}] {session_pct:.0f}%\n[{l_style}]LastReq {l_bar}[/{l_style}] {last_pct:.0f}% {s['last_req_ctx']}"

    def _render_stats(self) -> str:
        s = self.stats_data
        lines = []
        lines.append(f"[bold cyan]Status:[/bold cyan] {s['status']}")
        lines.append(f"[bold cyan]Elapsed:[/bold cyan] {s['elapsed']:.1f}s")
        lines.append(f"[bold cyan]No chunks:[/bold cyan] {s['no_chunks']:.1f}s")
        lines.append(f"[bold cyan]TTFT:[/bold cyan] {s['ttft']}")
        lines.append(f"[bold cyan]Thinking:[/bold cyan] {s['thinking_tokens']}")
        lines.append(f"[bold cyan]Response:[/bold cyan] {s['response_tokens']}")
        lines.append(f"[bold cyan]StreamTool:[/bold cyan] {s['stream_tool_tokens']}")
        lines.append(f"[bold cyan]FinalTool:[/bold cyan] {s['final_tool_tokens']}")
        lines.append(f"[bold cyan]TPS:[/bold cyan] {s['tps']:.2f}")
        lines.append(f"[bold cyan]VRAM:[/bold cyan] {s['vram']}")
        return "\n".join(lines)

    def _render_tools(self) -> str:
        if not self.active_tools:
            return "[dim]No active tools[/dim]"
        result = ""
        for tool in reversed(self.active_tools):
            status_style = "yellow" if tool["status"] == "running" else "green" if tool["status"] == "completed" else "red"
            size_display = f"{tool['size_kb']:.1f}KB" if tool['size_kb'] > 0 else "..."
            query_short = tool['query'][:25] + "..." if len(tool['query']) > 25 else tool['query']
            tag = "►" if tool["status"] == "running" else "✓"
            result += f"[bold magenta]{tool['name']}[/bold magenta] [{status_style}]{tag}[/{status_style}] [green]{size_display}[/green]\n  [dim]{query_short}[/dim]\n"
        return result

    def update_stats_display(self) -> None:
        if self.status_line:
            self.status_line.update(self._render_status_line())
        if self.stats_display:
            self.stats_display.update(self._render_stats())
        if self.tools_display:
            self.tools_display.update(self._render_tools())
        if self.ctx_bars:
            self.ctx_bars.update(self._render_ctx_bars())

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
        self.rich_log.lines = self.rich_log.lines[:self._stream_start_index]
        max_width = 0
        for line in self.rich_log.lines:
            w = sum(segment.cell_length for segment in line)
            if w > max_width:
                max_width = w
        self.rich_log._widest_line_width = max_width
        self.rich_log.virtual_size = Size(max_width, len(self.rich_log.lines))
        self.rich_log._line_cache.clear()
        if self._stream_content_buffer:
            self._write_markdown(self._stream_content_buffer)
        self.rich_log.refresh()

    def append_assistant_chunk(self, content: str = "", thinking: str = "") -> None:
        if thinking:
            self._stream_thinking_buffer += thinking
        if content:
            self._stream_content_buffer += content
            self._refresh_live_content()

    def finalize_assistant_turn(self, content: str, thinking: str = "",
                                tool_calls: Optional[list] = None) -> None:
        if self.rich_log and self._stream_start_index >= 0:
            self.rich_log.lines = self.rich_log.lines[:self._stream_start_index]
            max_width = 0
            for line in self.rich_log.lines:
                w = sum(segment.cell_length for segment in line)
                if w > max_width:
                    max_width = w
            self.rich_log._widest_line_width = max_width
            self.rich_log.virtual_size = Size(max_width, len(self.rich_log.lines))
            self.rich_log._line_cache.clear()
            self._stream_start_index = -1

        final_thinking = thinking or self._stream_thinking_buffer
        if final_thinking:
            self.rich_log.write("[dim]─── thinking ───[/dim]")
            self.rich_log.write(f"[dim]{final_thinking}[/dim]")
            self.rich_log.write("")
        self._stream_thinking_buffer = ""
        self._stream_content_buffer = ""

        if content:
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
        self.update_stats_display()

    def add_tool_activity(self, name: str, query: str, status: str = "running", size_kb: float = 0) -> None:
        self.active_tools.append({
            "name": name, "query": query, "status": status,
            "size_kb": size_kb, "start_time": time.time()
        })
        self.update_stats_display()

    def update_tool_activity(self, name: str, status: str = "completed", size_kb: float = 0) -> None:
        for tool in reversed(self.active_tools):
            if tool["name"] == name:
                tool["status"] = status
                tool["size_kb"] = size_kb
                break
        self.update_stats_display()

    def clear_log(self) -> None:
        if self.rich_log:
            self.rich_log.clear()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value
        event.input.value = ""
        if user_input.startswith("/"):
            if self.on_slash_command:
                self.on_slash_command(user_input)
        elif self.on_submit:
            self._start_time = time.time()
            self.rich_log.write(f"[dim]━━━ {datetime.now().strftime('%H:%M:%S')} ━━━[/dim]")
            self.rich_log.write(f"[bold blue]User:[/bold blue] {user_input}")
            self.rich_log.write("")
            self.on_submit(user_input)
