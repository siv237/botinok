import os
import sys
import json
import time
import requests
import argparse
from datetime import datetime
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from core.session_manager import SessionManager
from core.tool_manager import ToolManager

OLLAMA_CHAT_URL = "http://ollama.localnet:11434/api/chat"
OLLAMA_PS_URL = "http://ollama.localnet:11434/api/ps"

console = Console()

def create_layout():
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3)
    )
    layout["main"].split_row(
        Layout(name="content", ratio=2),
        Layout(name="right", ratio=1)
    )
    layout["right"].split_column(
        Layout(name="stats", size=12),
        Layout(name="tools_panel", ratio=1)
    )
    return layout

class BotVisualizer:
    def __init__(self, model, prompt, num_ctx):
        self.model = model
        self.prompt = prompt
        self.num_ctx = num_ctx
        self.response_text = ""
        self.start_time = time.time()
        self.first_token_time = None
        self.thinking_tokens = 0
        self.response_tokens = 0
        self.status = "Initializing..."
        self.vram_info = "Checking VRAM..."
        self.current_vram_used = 0
        self.total_vram = 8.0
        self.prompt_eval_count = 0
        self.eval_count = 0
        self.active_tools = [] # Список текущих вызовов инструментов
        
    def reset(self, prompt):
        self.prompt = prompt
        self.response_text = ""
        self.start_time = time.time()
        self.first_token_time = None
        self.thinking_tokens = 0
        self.response_tokens = 0
        self.status = "Initializing..."
        self.prompt_eval_count = 0
        self.eval_count = 0
        self.active_tools = []

    def add_tool_activity(self, name, query, status="running", size_kb=0):
        self.active_tools.append({
            "name": name,
            "query": query,
            "status": status,
            "size_kb": size_kb,
            "start_time": time.time()
        })

    def update_tool_activity(self, name, status, size_kb=0):
        for tool in self.active_tools:
            if tool["name"] == name and tool["status"] == "running":
                tool["status"] = status
                tool["size_kb"] = size_kb
                break

    @property
    def total_tokens(self):
        return self.thinking_tokens + self.response_tokens

    def update_vram(self, sm):
        status = sm.get_ollama_status()
        if status and "models" in status:
            info = []
            for m in status["models"]:
                vram = m.get("size_vram", 0) / (1024**3)
                self.current_vram_used = vram
                info.append(f"{m['name']}: {vram:.2f}GB")
            self.vram_info = " | ".join(info)
        else:
            self.vram_info = "No models loaded"
            self.current_vram_used = 0

    def get_header(self):
        return Panel(
            Text(f"BOTINOK AGENT | Model: {self.model} | Context: {self.num_ctx} | {self.vram_info}", justify="center", style="bold white on blue"),
            style="blue"
        )

    def get_content_panel(self, width=80, height=20):
        # Используем встроенный механизм Rich для замера строк с учетом переносов
        text_obj = Text(self.response_text, style="bold white")
        # console.render_lines делает всю магию учета переносов
        lines = list(text_obj.wrap(console, width - 4)) 
        
        if len(lines) > height:
            # Берем последние height строк, чтобы видеть актуальный вывод
            display_text = Text("\n").join(lines[-height:])
        else:
            display_text = Text("\n").join(lines)

        return Panel(
            display_text,
            title=f"[bold green]Response (Lines: {len(lines)}/{height})[/bold green]",
            border_style="green",
            expand=True,
            padding=(1, 1)
        )

    def get_stats_panel(self):
        elapsed = time.time() - self.start_time
        ttft = f"{self.first_token_time - self.start_time:.2f}s" if self.first_token_time else "..."
        # Считаем TPS на основе общего количества токенов (thinking + response)
        tps = self.total_tokens / (time.time() - self.first_token_time) if self.first_token_time and (time.time() - self.first_token_time) > 0 else 0
        
        # Индикатор активности (спиннер)
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        spinner = spinner_chars[int(time.time() * 10) % len(spinner_chars)]
        activity = f"[bold magenta]{spinner}[/bold magenta]" if self.status == "Generating..." else ""

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_row("[cyan]Status:[/cyan]", f"[bold]{self.status}[/bold] {activity}")
        table.add_row("[cyan]Elapsed:[/cyan]", f"{elapsed:.1f}s")
        table.add_row("[cyan]TTFT:[/cyan]", f"[bold yellow]{ttft}[/bold yellow]")
        table.add_row("[cyan]Thinking:[/cyan]", f"[bold yellow]{self.thinking_tokens}[/bold yellow]")
        table.add_row("[cyan]Response:[/cyan]", f"[bold green]{self.response_tokens}[/bold green]")
        table.add_row("[cyan]TPS:[/cyan]", f"[bold green]{tps:.2f}[/bold green]")
        
        # VRAM информация
        vram_pct = (self.current_vram_used / self.total_vram) * 100
        vram_style = "green" if vram_pct < 70 else "yellow" if vram_pct < 90 else "red"
        table.add_row("[cyan]VRAM:[/cyan]", f"[{vram_style}]{self.current_vram_used:.2f}GB ({vram_pct:.1f}%)[/{vram_style}]")
        
        # Context информация
        total_ctx_used = self.prompt_eval_count + self.total_tokens
        ctx_pct = (total_ctx_used / self.num_ctx) * 100 if self.num_ctx > 0 else 0
        ctx_style = "green" if ctx_pct < 70 else "yellow" if ctx_pct < 90 else "red"
        table.add_row("[cyan]Context:[/cyan]", f"[{ctx_style}]{total_ctx_used}/{self.num_ctx} ({ctx_pct:.1f}%)[/{ctx_style}]")
        
        return Panel(table, title="[bold yellow]Performance[/bold yellow]", border_style="yellow")

    def get_tools_panel(self):
        if not self.active_tools:
            return Panel(Text("No active tools", style="dim"), title="[bold magenta]Tools Activity[/bold magenta]", border_style="magenta")
        
        table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 1), expand=True)
        table.add_column("Tool", style="cyan")
        table.add_column("Query", style="white", overflow="ellipsis")
        table.add_column("Status", style="yellow")
        table.add_column("Size", style="green")

        for tool in reversed(self.active_tools):
            status_style = "yellow" if tool["status"] == "running" else "green" if tool["status"] == "completed" else "red"
            size_display = f"{tool['size_kb']:.2f} KB" if tool["size_kb"] > 0 else "..."
            table.add_row(
                tool["name"],
                tool["query"][:20] + "..." if len(tool["query"]) > 20 else tool["query"],
                f"[{status_style}]{tool['status']}[/{status_style}]",
                size_display
            )
        
        return Panel(table, title="[bold magenta]Tools Activity[/bold magenta]", border_style="magenta")

    def get_footer(self):
        return Panel(
            Text(f"Prompt: {self.prompt}", overflow="ellipsis", style="dim"),
            title="[bold cyan]Diagnostic Log[/bold cyan]",
            border_style="cyan"
        )

def ask_ollama_stream(model, messages, session_path, step_num, num_ctx=8192, vis=None):
    sm = SessionManager()
    tm = ToolManager()
    
    # Если визуализатор не передан, создаем новый (для первого запуска)
    prompt = messages[-1]["content"] if messages else ""
    if vis is None:
        vis = BotVisualizer(model, prompt, num_ctx)
    else:
        vis.reset(prompt)

    layout = create_layout()
    
    # Подготовка инструментов
    tools = tm.get_tool_definitions()
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "tools": tools,
        "options": {
            "num_ctx": num_ctx,
        }
    }

    with Live(layout, refresh_per_second=4, screen=False) as live:
        # Принудительная очистка перед запуском qwen3.5:9b
        if "qwen3.5:9b" in model:
            vis.status = "Forced VRAM Cleanup..."
            live.refresh()
            sm.unload_models()
            time.sleep(2)

        vis.status = "Checking Memory..."
        vis.update_vram(sm)
        layout["header"].update(vis.get_header())
        layout["stats"].update(vis.get_stats_panel())
        layout["tools_panel"].update(vis.get_tools_panel())
        layout["footer"].update(vis.get_footer())
        live.refresh()
        
        # Memory pressure check
        status = sm.get_ollama_status()
        if status and "models" in status:
            for m in status["models"]:
                vram = m.get("size_vram", 0) / (1024**3)
                if vram > 7.0 or (m['name'] != model and len(status['models']) > 0):
                    vis.status = "Unloading Models..."
                    live.refresh()
                    sm.unload_models()
                    break

        vis.status = "Connecting..."
        live.refresh()
        
        # Записываем заголовки файлов
        sm.write_file_header(session_path, "thinking.md", model, num_ctx, prompt)
        sm.write_file_header(session_path, "response.md", model, num_ctx, prompt)
        
        OLLAMA_CHAT_URL = f"{sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')}/api/chat"
        
        try:
            # Цикл для обработки потенциальных вызовов инструментов
            while True:
                response = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300))
                
                if response.status_code != 200:
                    error_msg = response.json().get("error", "Unknown Error")
                    vis.status = f"Ollama Error: {error_msg}"
                    layout["stats"].update(vis.get_stats_panel())
                    live.refresh()
                    time.sleep(10)
                    return messages

                vis.status = "Generating..."
                live.refresh()
                
                full_response = ""
                full_thinking = ""
                tool_calls = []
                metrics = {}
                
                sm.update_context(session_path, "user", prompt)
                
                thinking_ended = False
                
                for line in response.iter_lines():
                    if line:
                        try:
                            decoded_line = line.decode('utf-8')
                            chunk = json.loads(decoded_line)
                            
                            msg = chunk.get("message", {})
                            
                            if not vis.first_token_time:
                                vis.first_token_time = time.time()
                                vis.prompt_eval_count = chunk.get("prompt_eval_count", 0)
                            
                            if vis.total_tokens % 20 == 0:
                                vis.update_vram(sm)
                            
                            # Обработка процесса мышления
                            thought = msg.get("thinking", "")
                            if thought:
                                full_thinking += thought
                                vis.response_text = f"[dim]Thinking...[/dim]\n{full_thinking}\n\n[bold white]Response:[/bold white]\n{full_response}"
                                vis.thinking_tokens += 1
                                sm.log_chunk(session_path, "thinking", thought)
                            
                            # Обработка основного ответа
                            token = msg.get("content", "")
                            if token:
                                if not thinking_ended:
                                    thinking_ended = True
                                    thinking_stats = {
                                        "total_tokens": vis.thinking_tokens,
                                        "thinking_tokens": vis.thinking_tokens,
                                        "response_tokens": 0,
                                        "tps": vis.thinking_tokens / (time.time() - vis.first_token_time) if vis.first_token_time else 0,
                                        "ttft": vis.first_token_time - vis.start_time if vis.first_token_time else 0,
                                        "duration": time.time() - vis.start_time
                                    }
                                    sm.write_file_footer(session_path, "thinking.md", thinking_stats)

                                full_response += token
                                vis.response_text = f"[dim]Thinking...[/dim]\n{full_thinking}\n\n[bold white]Response:[/bold white]\n{full_response}"
                                vis.response_tokens += 1
                                sm.log_chunk(session_path, "response", token)

                            # Сбор вызовов инструментов
                            if msg.get("tool_calls"):
                                tool_calls.extend(msg.get("tool_calls"))
                            
                            layout["header"].update(vis.get_header())
                            main_height = console.size.height - 12
                            main_width = int(console.size.width * 0.66)
                            layout["content"].update(vis.get_content_panel(width=main_width, height=max(5, main_height)))
                            layout["stats"].update(vis.get_stats_panel())
                            layout["tools_panel"].update(vis.get_tools_panel())
                            live.refresh()
                            
                            if chunk.get("done"):
                                vis.status = "Done"
                                metrics = {
                                    "total_duration_ms": chunk.get("total_duration", 0) / 1_000_000,
                                    "load_duration_ms": chunk.get("load_duration", 0) / 1_000_000,
                                    "prompt_eval_count": chunk.get("prompt_eval_count", 0),
                                    "eval_count": chunk.get("eval_count", 0),
                                    "eval_duration_ms": chunk.get("eval_duration", 0) / 1_000_000,
                                }
                                sm.log_chunk(session_path, "metrics", "", metrics=metrics)
                        except json.JSONDecodeError:
                            continue

                # Если нет вызовов инструментов, выходим из цикла генерации
                if not tool_calls:
                    # Сохраняем финальный ответ этой итерации
                    sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
                    messages.append({"role": "assistant", "content": full_response})
                    break

                # Обработка вызовов инструментов
                vis.status = "Calling Tools..."
                live.refresh()
                
                # Добавляем ответ ассистента с вызовами инструментов в историю
                messages.append({"role": "assistant", "content": full_response, "tool_calls": tool_calls})
                sm.update_context(session_path, "assistant", full_response, thinking=full_thinking, tool_calls=tool_calls)
                
                for tool_call in tool_calls:
                    func_name = tool_call["function"]["name"]
                    func_args = tool_call["function"]["arguments"]
                    
                    query_display = func_args.get('query', str(func_args))
                    vis.add_tool_activity(func_name, query_display, "running")
                    vis.status = f"[bold yellow]Tool: {func_name}[/bold yellow] ([cyan]{query_display}[/cyan])"
                    layout["tools_panel"].update(vis.get_tools_panel())
                    live.refresh()
                    
                    sm.log_tool_call(session_path, func_name, func_args, "STARTED", status="running")
                    
                    for i in range(3):
                        vis.status = f"[bold yellow]Tool: {func_name}[/bold yellow] ([cyan]{query_display}[/cyan]) {'.' * (i+1)}"
                        live.refresh()
                        time.sleep(0.5)

                    result = tm.call_tool(func_name, func_args, session_path=session_path)
                    
                    res_size = len(str(result).encode('utf-8')) / 1024
                    vis.update_tool_activity(func_name, "completed", res_size)
                    vis.status = f"[bold green]Tool Done:[/bold green] {func_name} ([bold white]{res_size:.2f} KB[/bold white])"
                    layout["tools_panel"].update(vis.get_tools_panel())
                    live.refresh()
                    time.sleep(1)
                    
                    sm.log_tool_call(session_path, func_name, func_args, result, status="completed")
                    
                    messages.append({
                        "role": "tool",
                        "content": result,
                        "tool_call_id": tool_call.get("id")
                    })
                    
                    sm.log_step(session_path, f"tool_{func_name}_{int(time.time())}", tool_call, {"result": result}, {})

                # Обновляем payload для следующей итерации
                payload["messages"] = messages
                vis.status = "Resuming generation..."
                live.refresh()
            
            vis.status = "Done"
            layout["stats"].update(vis.get_stats_panel())
            live.refresh()

            # Сохраняем финальный ответ
            sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
            
            final_stats = {
                "total_tokens": vis.total_tokens,
                "thinking_tokens": vis.thinking_tokens,
                "response_tokens": vis.response_tokens,
                "tps": vis.total_tokens / (time.time() - vis.first_token_time) if vis.first_token_time else 0,
                "ttft": vis.first_token_time - vis.start_time if vis.first_token_time else 0,
                "duration": time.time() - vis.start_time
            }
            sm.write_file_footer(session_path, "response.md", final_stats)
            sm.log_step(session_path, f"step_{step_num}", payload, {"response": full_response, "thinking": full_thinking}, metrics)
            return messages # Возвращаем обновленную историю сообщений
            
        except Exception as e:
            vis.status = f"Error: {str(e)}"
            layout["stats"].update(vis.get_stats_panel())
            time.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="BOTINOK AGENT - Interactive AI Assistant")
    
    sm = SessionManager()
    default_model = sm.config.get('Ollama', 'DefaultModel', fallback='qwen3.5:9b')
    default_ctx = sm.config.getint('Ollama', 'DefaultContext', fallback=8192)
    ollama_base_url = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
    OLLAMA_CHAT_URL = f"{ollama_base_url}/api/chat"

    parser.add_argument("prompt_pos", nargs="?", help="Initial prompt (optional)")
    parser.add_argument("-p", "--prompt", help="Initial prompt")
    parser.add_argument("-m", "--model", default=default_model, help=f"Model name (default: {default_model})")
    parser.add_argument("-c", "--ctx", type=int, default=default_ctx, help=f"Context size (default: {default_ctx})")
    
    args = parser.parse_args()
    
    # Определяем параметры из аргументов или конфига
    arg_prompt = args.prompt if args.prompt else args.prompt_pos
    model = args.model
    num_ctx = args.ctx
    
    session_path = sm.create_session("visual_run")
    
    # Подготовка начальных сообщений
    now = datetime.now().astimezone()
    system_time_msg = (
        "Текущее системное время (локальная таймзона): "
        f"{now.isoformat()} (tzname={now.tzname()})"
    )
    messages = [{"role": "system", "content": system_time_msg}]
    
    vis = BotVisualizer(model, "", num_ctx)
    step_num = 1

    try:
        while True:
            if arg_prompt:
                prompt = arg_prompt
                arg_prompt = None # Используем только один раз
            else:
                # В интерактивном режиме запрашиваем ввод
                console.print(Panel(Text("Введите ваш вопрос (или 'exit' для выхода):", style="bold cyan"), border_style="cyan"))
                prompt = console.input("[bold green]> [/bold green]")
                
                if prompt.lower() in ["exit", "quit", "выход"]:
                    break
                if not prompt.strip():
                    continue

            messages.append({"role": "user", "content": prompt})
            
            # Запускаем генерацию
            messages = ask_ollama_stream(model, messages, session_path, step_num, num_ctx, vis)
            
            # Получаем последний ответ ассистента для красивого вывода
            last_assistant_message = next((m["content"] for m in reversed(messages) if m["role"] == "assistant"), "")
            
            if last_assistant_message:
                from rich.markdown import Markdown
                console.print("\n[bold green]Final Response:[/bold green]")
                console.print(Markdown(last_assistant_message))
                console.print("\n" + "─" * console.width + "\n")
            
            step_num += 1
            
    except KeyboardInterrupt:
        console.print("\n[bold red]Interrupted by user[/bold red]")
    finally:
        console.print(f"\n[bold blue]Session saved to: {session_path}[/bold blue]")

if __name__ == "__main__":
    main()
