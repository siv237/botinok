"""
Textual History Viewer - просмотр истории с прокруткой.

Запускается отдельно для просмотра истории сессии.
"""

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Header, Footer
from rich.text import Text
import json
import os
from datetime import datetime
from typing import Optional


class HistoryViewerApp(App):
    """Textual приложение для просмотра истории сессии."""

    CSS = """
    Screen {
        layout: vertical;
    }
    RichLog {
        height: 1fr;
    }
    """

    def __init__(self, session_path: str = "", **kwargs):
        super().__init__(**kwargs)
        self.session_path = session_path
        self.rich_log: Optional[RichLog] = None

    def compose(self) -> ComposeResult:
        """Создаем виджеты приложения."""
        yield Header()
        yield RichLog(markup=True, auto_scroll=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        """Вызывается при запуске приложения."""
        self.rich_log = self.query_one(RichLog)
        self.load_history()
        self.rich_log.scroll_end()

    def load_history(self) -> None:
        """Загружает историю сессии из context.json."""
        if not self.session_path:
            self.rich_log.write("[yellow]No session path specified[/yellow]")
            return

        context_path = os.path.join(self.session_path, "context.json")
        if not os.path.exists(context_path):
            self.rich_log.write(f"[red]Session not found: {context_path}[/red]")
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

            self.rich_log.write(f"\n[dim]Total: {len(history)} messages[/dim]")
        except Exception as e:
            self.rich_log.write(f"[red]Error loading history: {e}[/red]")

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
            lines = content_str.split('\n')[:10]  # Показываем больше строк
            for line in lines:
                self.rich_log.write(f"[dim]{line}[/dim]")
            if len(content_str.split('\n')) > 10:
                self.rich_log.write("[dim]...[/dim]")
            self.rich_log.write("")


def view_history(session_path: str):
    """Запускает просмотр истории сессии."""
    app = HistoryViewerApp(session_path=session_path)
    app.run()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        view_history(sys.argv[1])
    else:
        print("Usage: python textual_history_viewer.py <session_path>")
