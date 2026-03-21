import os
import sys
import time
import json
import threading
import queue
import requests
import argparse
from datetime import datetime
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from core.session_manager import SessionManager
from core.tool_manager import ToolManager

OLLAMA_CHAT_URL = "http://ollama.localnet:11434/api/chat"
OLLAMA_PS_URL = "http://ollama.localnet:11434/api/ps"

console = Console()

TOOL_OUTPUT_MAX_CHARS = 2000

def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(str(text)) // 4)

def _estimate_message_tokens(msg: dict) -> int:
    base = 8
    content = msg.get("content", "")
    t = base + _estimate_tokens(content)
    if "tool_calls" in msg and msg["tool_calls"]:
        try:
            t += _estimate_tokens(json.dumps(msg["tool_calls"], ensure_ascii=False))
        except Exception:
            t += _estimate_tokens(str(msg["tool_calls"]))
    return t

def _prepare_messages_for_ollama(sm: SessionManager, session_path: str, messages: list, num_ctx: int, reserve_tokens: int = 1200):
    """Trim message history to fit a conservative token budget.

    We keep all system messages, then include most recent messages until budget.
    Dropped messages are saved to session artifacts for audit.
    """
    if num_ctx <= 0:
        return messages

    budget = max(256, num_ctx - max(0, reserve_tokens))
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    kept = []
    used = sum(_estimate_message_tokens(m) for m in system_msgs)
    dropped = []

    for m in reversed(other_msgs):
        mt = _estimate_message_tokens(m)
        if used + mt <= budget:
            kept.append(m)
            used += mt
        else:
            dropped.append(m)

    kept.reverse()
    trimmed = system_msgs + kept

    if dropped:
        artifact_name = f"context_trim_{int(time.time())}.json"
        try:
            artifact_path = sm.save_artifact(session_path, artifact_name, json.dumps(list(reversed(dropped)), ensure_ascii=False, indent=2))
        except Exception:
            artifact_path = f"./artifacts/{artifact_name}"

        notice = {
            "role": "system",
            "content": (
                "Контекст был автоматически сокращён, чтобы избежать переполнения. "
                f"Старые сообщения сохранены в артефакт: {artifact_path}"
            )
        }
        trimmed = system_msgs + [notice] + kept

    return trimmed

def _compact_tool_message(tool_name: str, tool_args: dict, result: str, artifact_path: str) -> str:
    res_str = "" if result is None else str(result)
    size_kb = len(res_str.encode('utf-8', errors='ignore')) / 1024
    shown = res_str[:TOOL_OUTPUT_MAX_CHARS]
    truncated = len(res_str) > TOOL_OUTPUT_MAX_CHARS
    args_preview = tool_args
    try:
        args_preview = json.dumps(tool_args, ensure_ascii=False)
    except Exception:
        args_preview = str(tool_args)

    msg = (
        f"TOOL_RESULT_SUMMARY\n"
        f"tool: {tool_name}\n"
        f"args: {args_preview}\n"
        f"artifact_path: {artifact_path}\n"
        f"size_kb: {size_kb:.2f}\n"
        f"truncated_in_context: {str(truncated).lower()}\n"
        f"content_preview:\n{shown}"
    )
    if truncated:
        msg += f"\n...[TRUNCATED {len(res_str) - TOOL_OUTPUT_MAX_CHARS} chars]"
    return msg

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
        self.tool_tokens = 0 # Новое поле для учета токенов от инструментов
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
        self.tool_tokens = 0
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
            "start_time": time.time(),
            "current_tokens": 0 # Текущее количество токенов для анимации
        })

    def update_tool_activity(self, name, status, size_kb=0):
        for tool in self.active_tools:
            if tool["name"] == name and tool["status"] == "running":
                tool["status"] = status
                tool["size_kb"] = size_kb
                break

    @property
    def total_tokens(self):
        return self.thinking_tokens + self.response_tokens + self.tool_tokens

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
        # Используем фиксированное время для синхронизации анимации
        spinner_index = int(time.time() * 5) % len(spinner_chars)
        spinner = spinner_chars[spinner_index]
        
        display_status = self.status
            
        activity = f"[bold magenta]{spinner}[/bold magenta]" if self.status in ["Generating...", "Calling Tools...", "Resuming generation...", "Checking Memory...", "Unloading Models...", "Forced VRAM Cleanup...", "Connecting..."] or "Tool:" in self.status else ""

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_row("[cyan]Status:[/cyan]", f"[bold]{display_status}[/bold] {activity}")
        table.add_row("[cyan]Elapsed:[/cyan]", f"{elapsed:.1f}s")
        table.add_row("[cyan]TTFT:[/cyan]", f"[bold yellow]{ttft}[/bold yellow]")
        table.add_row("[cyan]Thinking:[/cyan]", f"[bold yellow]{self.thinking_tokens}[/bold yellow]")
        table.add_row("[cyan]Response:[/cyan]", f"[bold green]{self.response_tokens}[/bold green]")
        table.add_row("[cyan]Tool Ctx:[/cyan]", f"[bold magenta]{self.tool_tokens}[/bold magenta]")
        table.add_row("[cyan]TPS:[/cyan]", f"[bold green]{tps:.2f}[/bold green]")
        
        # VRAM информация
        vram_pct = (self.current_vram_used / self.total_vram) * 100
        vram_style = "green" if vram_pct < 70 else "yellow" if vram_pct < 90 else "red"
        table.add_row("[cyan]VRAM:[/cyan]", f"[{vram_style}]{self.current_vram_used:.2f}GB ({vram_pct:.1f}%)[/{vram_style}]")
        
        # Context информация
        # prompt_eval_count и eval_count приходят от Ollama и отражают реальные токены модели.
        # Локальные счетчики thinking/response/tool - приблизительные и для диагностики UI.
        total_ctx_used = self.prompt_eval_count + self.eval_count
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

    with Live(layout, refresh_per_second=10, screen=False, auto_refresh=True) as live:
        # Асинхронная подготовка (VRAM, очистка) чтобы UI не висел
        prep_queue = queue.Queue()
        def background_prep():
            try:
                if "qwen3.5:9b" in model:
                    vis.status = "Forced VRAM Cleanup..."
                    sm.unload_models()
                    time.sleep(1)
                
                vis.status = "Checking Memory..."
                vis.update_vram(sm)
                
                status = sm.get_ollama_status()
                if status and "models" in status:
                    for m in status["models"]:
                        vram = m.get("size_vram", 0) / (1024**3)
                        if vram > 7.0 or (m['name'] != model and len(status['models']) > 0):
                            vis.status = "Unloading Models..."
                            sm.unload_models()
                            break
                prep_queue.put("done")
            except Exception as e:
                prep_queue.put(f"error: {str(e)}")

        prep_thread = threading.Thread(target=background_prep)
        prep_thread.start()

        # Ожидание подготовки с живой анимацией
        while prep_thread.is_alive():
            layout["header"].update(vis.get_header())
            layout["stats"].update(vis.get_stats_panel())
            time.sleep(0.1)

        vis.status = "Connecting..."
        # Первичная отрисовка всех панелей
        layout["header"].update(vis.get_header())
        layout["stats"].update(vis.get_stats_panel())
        layout["tools_panel"].update(vis.get_tools_panel())
        layout["footer"].update(vis.get_footer())
        
        # Записываем заголовки файлов
        sm.write_file_header(session_path, "thinking.md", model, num_ctx, prompt)
        sm.write_file_header(session_path, "response.md", model, num_ctx, prompt)
        
        OLLAMA_CHAT_URL = f"{sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')}/api/chat"
        
        try:
            # Цикл для обработки потенциальных вызовов инструментов
            while True:
                payload["messages"] = _prepare_messages_for_ollama(sm, session_path, messages, num_ctx=num_ctx)
                # Создаем поток для выполнения POST запроса, чтобы не блокировать UI на этапе 'Connecting'
                response_queue = queue.Queue()
                def make_request():
                    try:
                        res = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300))
                        response_queue.put(("success", res))
                    except Exception as e:
                        response_queue.put(("error", str(e)))

                req_thread = threading.Thread(target=make_request)
                req_thread.start()

                # Ждем установки соединения, обновляя UI
                response = None
                while req_thread.is_alive():
                    layout["stats"].update(vis.get_stats_panel())
                    time.sleep(0.1)
                
                status, req_result = response_queue.get()
                if status == "error":
                    vis.status = f"Connection Error: {req_result}"
                    layout["stats"].update(vis.get_stats_panel())
                    time.sleep(5)
                    return messages
                
                response = req_result
                
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
                            
                            # Обновляем реальные счетчики токенов Ollama, если они присутствуют в чанке
                            if "prompt_eval_count" in chunk:
                                vis.prompt_eval_count = chunk.get("prompt_eval_count", 0)
                            if "eval_count" in chunk:
                                vis.eval_count = chunk.get("eval_count", 0)

                            if not vis.first_token_time:
                                vis.first_token_time = time.time()
                            
                            if vis.total_tokens % 50 == 0:
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

                            # Обновляем только то, что реально меняется
                            # layout["header"] и layout["footer"] теперь не обновляются в цикле токенов
                            main_height = console.size.height - 12
                            main_width = int(console.size.width * 0.66)
                            layout["content"].update(vis.get_content_panel(width=main_width, height=max(5, main_height)))
                            layout["stats"].update(vis.get_stats_panel())
                            
                            # Обновляем панель инструментов только если есть активные инструменты
                            if tool_calls or vis.active_tools:
                                layout["tools_panel"].update(vis.get_tools_panel())
                            
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
                    
                    sm.log_tool_call(session_path, func_name, func_args, "STARTED", status="running")
                    
                    # Асинхронный запуск инструмента для предотвращения фриза UI
                    result_queue = queue.Queue()
                    def run_tool():
                        try:
                            # Для инструментов, поддерживающих стриминг или порционную отдачу,
                            # здесь можно было бы реализовать колбэк. Но пока сделаем имитацию
                            # живого набора токенов во время ожидания.
                            res = tm.call_tool(func_name, func_args, session_path=session_path)
                            result_queue.put(("success", res))
                        except Exception as e:
                            result_queue.put(("error", str(e)))

                    tool_thread = threading.Thread(target=run_tool)
                    tool_thread.start()

                    # Ожидание результата с анимацией спиннера и "живым" счетчиком
                    result = None
                    simulated_tokens = 0
                    while tool_thread.is_alive():
                        # Имитируем постепенный рост токенов во время ожидания (например, поиск/загрузка)
                        # Это дает визуальную обратную связь, что данные "текут"
                        if simulated_tokens < 500: # Ограничим имитацию до получения реальных данных
                            simulated_tokens += 5
                            vis.tool_tokens += 5
                            if vis.active_tools:
                                vis.active_tools[-1]["current_tokens"] = simulated_tokens
                        
                        layout["stats"].update(vis.get_stats_panel())
                        layout["tools_panel"].update(vis.get_tools_panel())
                        time.sleep(0.1)

                    status, tool_output = result_queue.get()
                    
                    # Убираем имитированные токены перед добавлением реальных
                    vis.tool_tokens -= simulated_tokens
                    
                    if status == "error":
                        result = f"Error calling tool: {tool_output}"
                    else:
                        result = tool_output

                    artifact_file = f"tool_{func_name}_{tool_call.get('id', int(time.time()))}.txt"
                    artifact_path = sm.save_artifact(session_path, artifact_file, str(result))

                    compact_msg = _compact_tool_message(func_name, func_args, result, artifact_path)

                    # Считаем Tool Ctx по тому, что реально пойдет в контекст (compact_msg)
                    res_tokens = len(str(compact_msg)) // 4
                    vis.tool_tokens += res_tokens
                    if vis.active_tools:
                        vis.active_tools[-1]["current_tokens"] = res_tokens
                    
                    res_size = len(str(result).encode('utf-8')) / 1024
                    vis.update_tool_activity(func_name, "completed", res_size)
                    vis.status = f"[bold green]Tool Done:[/bold green] {func_name} ([bold white]{res_size:.2f} KB[/bold white])"
                    layout["tools_panel"].update(vis.get_tools_panel())
                    time.sleep(1)
                    
                    sm.log_tool_call(session_path, func_name, func_args, result, status="completed")
                    
                    messages.append({
                        "role": "tool",
                        "content": compact_msg,
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

            # Финальный ответ сохраняется в контекст в месте фактического завершения генерации
            
            final_stats = {
                "total_tokens": vis.total_tokens,
                "thinking_tokens": vis.thinking_tokens,
                "response_tokens": vis.response_tokens,
                "tps": vis.total_tokens / (time.time() - vis.first_token_time) if vis.first_token_time else 0,
                "ttft": vis.first_token_time - vis.start_time if vis.first_token_time else 0,
                "duration": time.time() - vis.start_time
            }
            sm.log_step(session_path, f"step_{step_num}", payload, {"response": full_response, "thinking": full_thinking}, metrics)
            return messages # Возвращаем обновленную историю сообщений
            
        except Exception as e:
            vis.status = f"Error: {str(e)}"
            layout["stats"].update(vis.get_stats_panel())
            time.sleep(5)

def ask_ollama_stealth(model, messages, session_path, step_num, num_ctx=8192):
    sm = SessionManager()
    tm = ToolManager()
    
    prompt = messages[-1]["content"] if messages else ""
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

    sm.write_file_header(session_path, "thinking.md", model, num_ctx, prompt)
    sm.write_file_header(session_path, "response.md", model, num_ctx, prompt)
    
    ollama_base_url = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
    OLLAMA_CHAT_URL = f"{ollama_base_url}/api/chat"
    
    try:
        while True:
            payload["messages"] = _prepare_messages_for_ollama(sm, session_path, messages, num_ctx=num_ctx)
            response = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300))
            
            if response.status_code != 200:
                return messages

            full_response = ""
            full_thinking = ""
            tool_calls = []
            
            sm.update_context(session_path, "user", prompt)
            
            for line in response.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        msg = chunk.get("message", {})
                        
                        thought = msg.get("thinking", "")
                        if thought:
                            full_thinking += thought
                            sm.log_chunk(session_path, "thinking", thought)
                        
                        token = msg.get("content", "")
                        if token:
                            full_response += token
                            sm.log_chunk(session_path, "response", token)

                        if msg.get("tool_calls"):
                            tool_calls.extend(msg.get("tool_calls"))
                            
                        if chunk.get("done"):
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

            if not tool_calls:
                sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
                messages.append({"role": "assistant", "content": full_response})
                break

            messages.append({"role": "assistant", "content": full_response, "tool_calls": tool_calls})
            sm.update_context(session_path, "assistant", full_response, thinking=full_thinking, tool_calls=tool_calls)
            
            for tool_call in tool_calls:
                func_name = tool_call["function"]["name"]
                func_args = tool_call["function"]["arguments"]
                
                sm.log_tool_call(session_path, func_name, func_args, "STARTED", status="running")
                
                try:
                    result = tm.call_tool(func_name, func_args, session_path=session_path)
                except Exception as e:
                    result = f"Error calling tool: {str(e)}"

                artifact_file = f"tool_{func_name}_{tool_call.get('id', int(time.time()))}.txt"
                artifact_path = sm.save_artifact(session_path, artifact_file, str(result))
                compact_msg = _compact_tool_message(func_name, func_args, result, artifact_path)
                
                sm.log_tool_call(session_path, func_name, func_args, result, status="completed")
                
                messages.append({
                    "role": "tool",
                    "content": compact_msg,
                    "tool_call_id": tool_call.get("id")
                })
                
                sm.log_step(session_path, f"tool_{func_name}_{int(time.time())}", tool_call, {"result": result}, {})

            payload["messages"] = messages
            
        return messages
            
    except Exception:
        return messages

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
    parser.add_argument("--wizard", action="store_true", help="Запустить мастер настройки")
    parser.add_argument("--stealth", action="store_true", help="Минимальный вывод, только ответ")
    
    args = parser.parse_args()
    
    if args.wizard:
        from core.config_wizard import ConfigWizard
        wizard = ConfigWizard()
        wizard.run()
        return
    
    # Определяем параметры из аргументов или конфига
    arg_prompt = args.prompt if args.prompt else args.prompt_pos
    model = args.model
    num_ctx = args.ctx
    stealth_mode = args.stealth or not sys.stdin.isatty()

    # Если есть данные в stdin (Pipe mode), добавляем их к промпту
    stdin_data = ""
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            if arg_prompt:
                arg_prompt = f"{stdin_data}\n\n{arg_prompt}"
            else:
                arg_prompt = stdin_data

    session_path = sm.create_session("visual_run" if not stealth_mode else "stealth_run")
    
    # Подготовка начальных сообщений
    now = datetime.now().astimezone()
    system_time_msg = (
        "Текущее системное время (локальная таймзона): "
        f"{now.isoformat()} (tzname={now.tzname()})"
    )
    tool_policy_msg = (
        "Политика инструментов:\n"
        "- Для systemd journal/journalctl используй инструмент 'journal' (а не file_system).\n"
        "- file_system предназначен для файлов/директорий/grep и чтения файлов."
    )
    messages = [
        {"role": "system", "content": system_time_msg},
        {"role": "system", "content": tool_policy_msg},
    ]
    
    vis = BotVisualizer(model, "", num_ctx)
    step_num = 1

    # Вывод ASCII арта и версии (только если не stealth_mode)
    if not stealth_mode:
        ascii_art = """
    [bold blue]
                                                           ^^:.                                     
                                                          !~.~!7^:::::....                          
                                                        ^?7^7!~~~7~~~~~~!!!!!!~~^^                  
                                                       :J7:J^!7~ ^           ..:~P^                 
                                                       7J !?:^~:~^::::........  !Y.                 
                                                      ~Y::J!!7..~      ........:J?                  
                                                     ~?7!?!:~!.^.              :Y!                  
                                                    ~J~!?7!!: ^:               ^5~                  
                                                  .!?!??~.~!:^:                !Y!                  
                                                .^???77!?! .^.                 7?7                  
                                              .~?J7??~.:~^::                   ?!?.                 
                                           .^7J5J7^:7?~.::.                 .:^J77!                 
                                         ^!7Y?~~7?! .:::.               :^!!~~^.  ?.                
                                       .?7J7!?! .^^::.               :~!~^.       !~                
                                   .:^~~^.?~:~^  ^.                 !7^.          .?                
                    .:::::::::^^~7~^^.    ~?: ..:~.:::....         7!              ?:               
                 .~~^:::::::::...!?        !?~~~~7!~!!~~~^::.     ^?.              7:               
                 7:               !7        ^^::.......:^~!!^::   !7               ?.               
               .~?..              .?^                      ^7~:^..J!.::::^^^^~~~~!!J!               
               J7!7!!!~^::..       ~?                 ..:^^~7?777!?777777777!7!!!!~^J:              
              ^7:::^~!!!!7!7!7!!~~^~J~:^:::::^^^^~~!!7777!!!!~~^^^^::.........      !^              
              .^!~^!^.:~::^^^^~~!!~!!7!7!7!7!7!7!!!!~^~^^^^~~~^!7^?                 !~              
    [/bold blue]
    [bold yellow]BOTINOK AGENT - Version 0.1[/bold yellow]
    """
        console.print(Panel(Text.from_markup(ascii_art), border_style="blue"))

    try:
        while True:
            if arg_prompt:
                prompt = arg_prompt
                arg_prompt = None # Используем только один раз
            else:
                if stealth_mode:
                    # В stealth mode без начального промпта и без tty выходим
                    break
                # В интерактивном режиме запрашиваем ввод
                console.print(Panel(Text("Введите ваш вопрос (или 'exit' для выхода):", style="bold cyan"), border_style="cyan"))
                prompt = console.input("[bold green]> [/bold green]")
                
                if prompt.lower() in ["exit", "quit", "выход"]:
                    break
                if not prompt.strip():
                    continue

            turn_start_idx = len(messages)
            messages.append({"role": "user", "content": prompt})
            
            # Запускаем генерацию
            if stealth_mode:
                # В тихом режиме используем упрощенную логику вывода
                messages = ask_ollama_stealth(model, messages, session_path, step_num, num_ctx)
            else:
                messages = ask_ollama_stream(model, messages, session_path, step_num, num_ctx, vis)
            
            # Получаем последний ответ ассистента строго в рамках текущего turn,
            # чтобы не печатать ответ из предыдущего turn при раннем выходе/ошибке.
            last_assistant_message = ""
            for m in reversed(messages[turn_start_idx:]):
                if m.get("role") == "assistant" and m.get("content"):
                    last_assistant_message = m["content"]
                    break
            
            if last_assistant_message:
                if not stealth_mode:
                    console.print("\n[bold green]Final Response:[/bold green]")
                    console.print(Markdown(last_assistant_message))
                    console.print("\n" + "─" * console.width + "\n")
                else:
                    # В stealth mode используем Markdown для красивого вывода
                    console.print(Markdown(last_assistant_message))
                    break
            else:
                if not stealth_mode:
                    console.print("\n[bold red]Final Response отсутствует: текущий turn завершился без нового ответа ассистента (возможно ошибка или ранний выход).[/bold red]")
                    console.print("\n" + "─" * console.width + "\n")
            
            step_num += 1
            
    except KeyboardInterrupt:
        console.print("\n[bold red]Interrupted by user[/bold red]")
    finally:
        if not stealth_mode:
            console.print(f"\n[bold blue]Session saved to: {session_path}[/bold blue]")

if __name__ == "__main__":
    main()
