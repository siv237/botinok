"""
Textual приложение для Botinok с RichLog для истории и Input для ввода.

Заменяет Rich Live на полноценное Textual приложение.
"""

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Header, Footer, Input, Static, ProgressBar
from textual.containers import Vertical, Horizontal, Container
from rich.text import Text
from rich.markdown import Markdown
import json
import os
import time
import threading
import queue
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
    }
    #right {
        width: 1fr;
    }
    RichLog {
        height: 100%;
    }
    #right_panel {
        layout: vertical;
        height: 100%;
    }
    #stats {
        height: 1fr;
    }
    #tools {
        height: 1fr;
    }
    Static {
        height: auto;
    }
    ProgressBar {
        height: 1;
    }
    """

    def __init__(self, session_path: str = "", on_submit: Optional[Callable] = None, **kwargs):
        super().__init__(**kwargs)
        self.session_path = session_path
        self.on_submit = on_submit
        self.rich_log: Optional[RichLog] = None
        self.stats_display: Optional[Static] = None
        self.tools_display: Optional[Static] = None
        self.ctx_progress: Optional[ProgressBar] = None
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

    def compose(self) -> ComposeResult:
        """Создаем виджеты приложения."""
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield RichLog(markup=True, auto_scroll=True, wrap=True, id="content")
            with Vertical(id="right"):
                with Vertical(id="right_panel"):
                    self.stats_display = Static(self._render_stats(), id="stats")
                    yield self.stats_display
                    self.ctx_progress = ProgressBar(show_percentage=True, id="ctx_progress")
                    yield self.ctx_progress
                    self.tools_display = Static(self._render_tools(), id="tools")
                    yield self.tools_display
        yield Input(placeholder="Введите ваш вопрос...", id="input")
        yield Footer()

    def on_mount(self) -> None:
        """Вызывается при запуске приложения."""
        self.rich_log = self.query_one(RichLog)
        self.load_history()

    def _render_stats(self) -> str:
        """Рендерит статистику."""
        s = self.stats_data
        session_ctx_pct = (s['session_ctx'] / s['session_ctx_max']) * 100 if s['session_ctx_max'] > 0 else 0
        last_req_ctx_pct = (s['last_req_ctx'] / s['last_req_ctx_max']) * 100 if s['last_req_ctx_max'] > 0 else 0
        
        return f"""[bold cyan]Status:[/bold cyan] {s['status']}
[bold cyan]Elapsed:[/bold cyan] {s['elapsed']:.1f}s
[bold cyan]No chunks:[/bold cyan] {s['no_chunks']:.1f}s
[bold cyan]TTFT:[/bold cyan] {s['ttft']}
[bold cyan]Thinking:[/bold cyan] {s['thinking_tokens']}
[bold cyan]Response:[/bold cyan] {s['response_tokens']}
[bold cyan]Stream Tool:[/bold cyan] {s['stream_tool_tokens']}
[bold cyan]Final Tool:[/bold cyan] {s['final_tool_tokens']}
[bold cyan]TPS:[/bold cyan] {s['tps']:.2f}
[bold cyan]VRAM:[/bold cyan] {s['vram']}

[dim]────────────────────────────────────[/dim]
[bold cyan]SessionCtx:[/bold cyan] {s['session_ctx']}/{s['session_ctx_max']} ({session_ctx_pct:.1f}%)
[bold cyan]LastReqCtx:[/bold cyan] {s['last_req_ctx']}/{s['last_req_ctx_max']} ({last_req_ctx_pct:.1f}%)"""

    def _render_tools(self) -> str:
        """Рендерит активные инструменты."""
        if not self.active_tools:
            return "[dim]No active tools[/dim]"
        
        result = ""
        for tool in reversed(self.active_tools):
            status_style = "yellow" if tool["status"] == "running" else "green" if tool["status"] == "completed" else "red"
            size_display = f"{tool['size_kb']:.2f} KB" if tool['size_kb'] > 0 else "..."
            result += f"[bold magenta]{tool['name']}[/bold magenta] [cyan]{tool['query'][:20]}...[/cyan] [{status_style}]{tool['status']}[/{status_style}] [green]{size_display}[/green]\n"
        return result

    def update_stats_display(self) -> None:
        """Обновляет отображение статистики."""
        if self.stats_display:
            self.stats_display.update(self._render_stats())
        if self.tools_display:
            self.tools_display.update(self._render_tools())
        if self.ctx_progress:
            session_ctx_pct = (self.stats_data['session_ctx'] / self.stats_data['session_ctx_max']) * 100 if self.stats_data['session_ctx_max'] > 0 else 0
            self.ctx_progress.progress = session_ctx_pct / 100

    def load_history(self) -> None:
        """Загружает историю сессии из context.json."""
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
                role = entry.get("role", "")
                content = entry.get("content", "")
                thinking = entry.get("thinking", "")
                timestamp = entry.get("timestamp", "")
                tool_calls = entry.get("tool_calls", [])

                self._add_entry(role, content, thinking, timestamp, tool_calls)

            self.rich_log.scroll_end()
        except Exception as e:
            self.rich_log.write(f"[red]Ошибка загрузки истории: {e}[/red]")

    def _add_entry(self, role: str, content: str, thinking: str,
                   timestamp: str, tool_calls: Optional[list] = None) -> None:
        """Добавляет запись в RichLog с форматированием."""
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
            self.rich_log.write(f"[bold blue]User:[/bold blue] {content}")
            self.rich_log.write("")

        elif role == "assistant":
            if thinking:
                self.rich_log.write("[dim]─── thinking ───[/dim]")
                self.rich_log.write(f"[dim]{thinking}[/dim]")
                self.rich_log.write("")

            if content:
                self.rich_log.write("[bold green]Assistant:[/bold green]")
                self.rich_log.write(content)
                self.rich_log.write("")

            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "unknown")
                    self.rich_log.write(f"[bold yellow]Tool: {tool_name}[/bold yellow]")

        elif role == "tool":
            content_str = str(content)
            lines = content_str.split('\n')[:5]
            for line in lines:
                self.rich_log.write(f"[dim]{line}[/dim]")
            if len(content_str.split('\n')) > 5:
                self.rich_log.write("[dim]...[/dim]")
            self.rich_log.write("")

    def append_user_message(self, content: str) -> None:
        """Добавляет сообщение пользователя."""
        now = datetime.now().isoformat()
        self._add_entry("user", content, "", now)

    def append_assistant_chunk(self, content: str = "", thinking: str = "") -> None:
        """Добавляет чанк от ассистента (во время стриминга)."""
        if content:
            self.rich_log.write(content)
        if thinking:
            self.rich_log.write(f"[dim]{thinking}[/dim]")

    def finalize_assistant_turn(self, content: str, thinking: str = "",
                                tool_calls: Optional[list] = None) -> None:
        """Финализирует turn ассистента."""
        now = datetime.now().isoformat()
        self._add_entry("assistant", content, thinking, now, tool_calls)

    def append_tool_result(self, tool_name: str, result: str) -> None:
        """Добавляет результат инструмента."""
        self.rich_log.write(f"[bold yellow]Tool: {tool_name}[/bold yellow]")
        content_str = str(result)
        lines = content_str.split('\n')[:5]
        for line in lines:
            self.rich_log.write(f"[dim]{line}[/dim]")
        if len(content_str.split('\n')) > 5:
            self.rich_log.write("[dim]...[/dim]")
        self.rich_log.write("")

    def update_stats(self, status: str, elapsed: float, no_chunks: float, ttft: float,
                     thinking_tokens: int, response_tokens: int, stream_tool_tokens: int,
                     final_tool_tokens: int, tps: float, vram: str,
                     session_ctx: int, session_ctx_max: int,
                     last_req_ctx: int, last_req_ctx_max: int) -> None:
        """Обновляет статистику."""
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
        """Добавляет активный инструмент."""
        self.active_tools.append({
            "name": name,
            "query": query,
            "status": status,
            "size_kb": size_kb,
            "start_time": time.time()
        })
        self.update_stats_display()

    def update_tool_activity(self, name: str, status: str = "completed", size_kb: float = 0) -> None:
        """Обновляет статус инструмента."""
        for tool in reversed(self.active_tools):
            if tool["name"] == name:
                tool["status"] = status
                tool["size_kb"] = size_kb
                break
        self.update_stats_display()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Обрабатывает ввод текста."""
        user_input = event.value
        self.rich_log.write(f"[bold blue]User:[/bold blue] {user_input}")
        self.rich_log.write("")
        event.input.value = ""  # Очищаем поле ввода

        if self.on_submit:
            self.on_submit(user_input)


if __name__ == "__main__":
    def on_submit(text: str):
        print(f"Submitted: {text}")

    app = BotinokTextualApp(session_path="", on_submit=on_submit)
    app.run()
