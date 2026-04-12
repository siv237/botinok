"""
Textual UI для Botinok с поддержкой прокрутки через RichLog.

Использует Textual фреймворк для TUI с встроенной обработкой событий и прокруткой.
"""

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Header, Footer, Static
from textual.containers import Vertical, Horizontal
from rich.text import Text
from rich.markdown import Markdown
import json
import os
from datetime import datetime
from typing import Optional


class BotinokApp(App):
    """Textual приложение для Botinok с прокруткой истории."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main {
        height: 1fr;
    }
    RichLog {
        height: 1fr;
    }
    #stats {
        height: 20;
        dock: top;
    }
    """

    def __init__(self, session_path: str = "", **kwargs):
        super().__init__(**kwargs)
        self.session_path = session_path
        self.rich_log: Optional[RichLog] = None

    def compose(self) -> ComposeResult:
        """Создаем виджеты приложения."""
        yield Header()
        yield RichLog(markup=True, auto_scroll=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        """Вызывается при запуске приложения."""
        self.rich_log = self.query_one(RichLog)
        self.load_history()

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

            # Прокрутка в конец
            self.rich_log.scroll_end()
        except Exception as e:
            self.rich_log.write(f"[red]Ошибка загрузки истории: {e}[/red]")

    def _add_entry(self, role: str, content: str, thinking: str,
                   timestamp: str, tool_calls: Optional[list] = None) -> None:
        """Добавляет запись в RichLog с форматированием."""
        if not role:
            return

        # Форматируем timestamp
        ts_str = ""
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                ts_str = dt.strftime("%H:%M:%S")
            except Exception:
                ts_str = str(timestamp)[:8]

        if role == "user":
            self.rich_log.write(f"[dim]━━━ Turn ━━━ {ts_str} ━━━[/dim]")
            self.rich_log.write(f"[bold blue]User:[/bold blue] {content}")
            self.rich_log.write("")

        elif role == "assistant":
            # Thinking
            if thinking:
                self.rich_log.write("[dim]─── thinking ───[/dim]")
                self.rich_log.write(f"[dim]{thinking}[/dim]")
                self.rich_log.write("")

            # Content
            if content:
                self.rich_log.write("[bold green]Assistant:[/bold green]")
                self.rich_log.write(content)
                self.rich_log.write("")

            # Tool calls
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "unknown")
                    self.rich_log.write(f"[bold yellow]Tool: {tool_name}[/bold yellow]")

        elif role == "tool":
            # Показываем первые несколько строк результата
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
        # Для стриминга просто добавляем в конец
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

    def scroll_to_end(self) -> None:
        """Прокрутка в конец."""
        if self.rich_log:
            self.rich_log.scroll_end()

    def scroll_to_start(self) -> None:
        """Прокрутка в начало."""
        if self.rich_log:
            self.rich_log.scroll_home()


if __name__ == "__main__":
    app = BotinokApp(session_path="")
    app.run()
