"""
Textual приложение для Botinok с RichLog для истории и Input для ввода.
"""

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Header, Footer, Input, Static
from textual.containers import Vertical, Horizontal
from rich.markdown import Markdown
import json
import os
import re
import time
from datetime import datetime
from typing import Optional, Callable, List


class BotinokTextualApp(App):
    """Textual приложение для Botinok."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main {
        height: 1fr;
    }
    #left {
        width: 2fr;
        min-width: 40;
    }
    #right {
        width: 1fr;
        max-width: 30;
    }
    RichLog {
        height: 100%;
    }
    #right_panel {
        layout: vertical;
        height: 100%;
    }
    #stats {
        height: auto;
    }
    #tools {
        height: 1fr;
    }
    #ctx_bar {
        height: auto;
        color: cyan;
        background: $surface-darken-1;
        padding: 0 1;
    }
    Input:focus {
        border: tall $success;
    }
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
        self.ctx_bar: Optional[Static] = None
        self.stats_data = {
            "status": "Ready",
            "elapsed": 0.0,
            "no_chunks": 0.0,
            "ttft": "...",
            "thinking_tokens": 0,
            "response_tokens": 0,
            "stream_tool_tokens": 0,
            "final_tool_tokens": 0,
            "tps": 0.0,
            "vram": "...",
            "session_ctx": 0,
            "session_ctx_max": 8192,
            "last_req_ctx": 0,
            "last_req_ctx_max": 8192
        }
        self.active_tools: List[dict] = []
        self._stream_content_buffer = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield RichLog(markup=True, auto_scroll=True, wrap=True, highlight=True, id="content")
            with Vertical(id="right"):
                with Vertical(id="right_panel"):
                    self.stats_display = Static(self._render_stats(), id="stats")
                    yield self.stats_display
                    self.ctx_bar = Static(self._render_ctx_bar(), id="ctx_bar")
                    yield self.ctx_bar
                    self.tools_display = Static(self._render_tools(), id="tools")
                    yield self.tools_display
        yield Input(placeholder="Введите ваш вопрос (exit = выход)...", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.rich_log = self.query_one(RichLog)
        self.load_history()
        try:
            input_widget = self.query_one("#input", Input)
            self.set_focus(input_widget)
        except Exception:
            pass
        if hasattr(self, '_vram_prep_fn') and self._vram_prep_fn:
            import threading
            t = threading.Thread(target=self._vram_prep_fn, daemon=True)
            t.start()

    def _render_ctx_bar(self) -> str:
        s = self.stats_data
        pct = (s['session_ctx'] / s['session_ctx_max']) * 100 if s['session_ctx_max'] > 0 else 0
        bar_width = 20
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        style = "green" if pct < 70 else "yellow" if pct < 90 else "red"
        return f"[{style}]{bar}[/{style}] {pct:.1f}% ({s['session_ctx']}/{s['session_ctx_max']})"

    def _render_stats(self) -> str:
        s = self.stats_data
        return f"""[bold cyan]Status:[/bold cyan] {s['status']}
[bold cyan]TTFT:[/bold cyan] {s['ttft']}
[bold cyan]Thinking:[/bold cyan] {s['thinking_tokens']}
[bold cyan]Response:[/bold cyan] {s['response_tokens']}
[bold cyan]TPS:[/bold cyan] {s['tps']:.2f}
[bold cyan]VRAM:[/bold cyan] {s['vram']}"""

    def _render_tools(self) -> str:
        if not self.active_tools:
            return "[dim]No active tools[/dim]"
        result = ""
        for tool in reversed(self.active_tools[-5:]):
            status_style = "yellow" if tool["status"] == "running" else "green" if tool["status"] == "completed" else "red"
            size_display = f"{tool['size_kb']:.1f}KB" if tool['size_kb'] > 0 else "..."
            query_short = tool['query'][:25] + "..." if len(tool['query']) > 25 else tool['query']
            result += f"[bold magenta]{tool['name']}[/bold magenta] [{status_style}]{tool['status']}[/{status_style}] [green]{size_display}[/green]\n  [dim]{query_short}[/dim]\n"
        return result

    def update_stats_display(self) -> None:
        if self.stats_display:
            self.stats_display.update(self._render_stats())
        if self.tools_display:
            self.tools_display.update(self._render_tools())
        if self.ctx_bar:
            self.ctx_bar.update(self._render_ctx_bar())

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
                ts = entry.get("timestamp", "")
                self._add_entry(
                    entry.get("role", ""),
                    entry.get("content", ""),
                    entry.get("thinking", ""),
                    ts,
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

    def append_assistant_chunk(self, content: str = "", thinking: str = "") -> None:
        if content:
            self._stream_content_buffer += content
            escaped = self._rich_escape_tags(content)
            self.rich_log.write(escaped, width=self.size.width - 35 if hasattr(self, 'size') else 60)
        if thinking:
            self.rich_log.write(f"[dim]{thinking}[/dim]")

    def finalize_assistant_turn(self, content: str, thinking: str = "",
                                tool_calls: Optional[list] = None) -> None:
        self._stream_content_buffer = ""
        now = datetime.now().isoformat()
        self._add_entry("assistant", content, thinking, now, tool_calls)

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
            "status": status,
            "elapsed": elapsed,
            "no_chunks": no_chunks,
            "ttft": ttft,
            "thinking_tokens": thinking_tokens,
            "response_tokens": response_tokens,
            "stream_tool_tokens": stream_tool_tokens,
            "final_tool_tokens": final_tool_tokens,
            "tps": tps,
            "vram": vram,
            "session_ctx": session_ctx,
            "session_ctx_max": session_ctx_max,
            "last_req_ctx": last_req_ctx,
            "last_req_ctx_max": last_req_ctx_max
        }
        self.update_stats_display()

    def add_tool_activity(self, name: str, query: str, status: str = "running", size_kb: float = 0) -> None:
        self.active_tools.append({
            "name": name,
            "query": query,
            "status": status,
            "size_kb": size_kb,
            "start_time": time.time()
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
            self.rich_log.write(f"[dim]━━━ {datetime.now().strftime('%H:%M:%S')} ━━━[/dim]")
            self.rich_log.write(f"[bold blue]User:[/bold blue] {user_input}")
            self.rich_log.write("")
            self.on_submit(user_input)
