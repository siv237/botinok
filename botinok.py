import os
import sys
import time
import json
import threading
import queue
import requests
import argparse
import re
from datetime import datetime
import inquirer
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich.prompt import Confirm
from core.session_manager import SessionManager
from core.tool_manager import ToolManager

import subprocess

def _get_version_info():
    """Получает версию из файла .version (если установлен) или из git."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    version_file = os.path.join(script_dir, ".version")
    
    # Сначала пробуем прочитать из файла (для установленных версий)
    try:
        if os.path.exists(version_file):
            with open(version_file, "r") as f:
                version = f.read().strip()
                if version:
                    # Парсим формат: "0.2 | DD.MM.YYYY | HASH"
                    parts = version.split(" | ")
                    if len(parts) >= 3:
                        return parts[1], parts[2]
                    return "unknown", "????"
    except Exception:
        pass
    
    # Fallback на git (для разработки)
    try:
        # Проверяем что git доступен
        git_check = subprocess.run(
            ['git', '--version'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        if git_check.returncode != 0:
            return "unknown", "????"
        
        # Дата последнего коммита в формате DD.MM.YYYY
        date_result = subprocess.run(
            ['git', 'log', '-1', '--format=%cd', '--date=format:%d.%m.%Y'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        commit_date = date_result.stdout.strip() if date_result.returncode == 0 else "unknown"
        
        # Первые 4 символа хэша коммита
        hash_result = subprocess.run(
            ['git', 'log', '-1', '--format=%h'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        commit_hash = hash_result.stdout.strip()[:4] if hash_result.returncode == 0 else "????"
        
        return commit_date, commit_hash
    except Exception:
        return "unknown", "????"


def _check_remote_version():
    """Проверяет есть ли обновления в удаленном репозитории."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    try:
        # Проверяем что это git репозиторий
        git_check = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        if git_check.returncode != 0:
            return None, "Not a git repository"
        
        # Получаем текущий хэш
        local_hash = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        if local_hash.returncode != 0:
            return None, "Failed to get local version"
        local_hash = local_hash.stdout.strip()
        
        # Получаем информацию об удаленном origin
        remote_url = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        if remote_url.returncode != 0:
            return None, "No remote origin configured"
        
        # Fetch с удаленного репозитория (без изменения локальных файлов)
        fetch_result = subprocess.run(
            ['git', 'fetch', 'origin', '--quiet'],
            capture_output=True, text=True, cwd=script_dir, timeout=30
        )
        if fetch_result.returncode != 0:
            return None, f"Failed to fetch: {fetch_result.stderr}"
        
        # Получаем хэш последнего коммита на origin/main (или origin/master)
        for branch in ['main', 'master']:
            remote_hash = subprocess.run(
                ['git', 'rev-parse', f'origin/{branch}'],
                capture_output=True, text=True, cwd=script_dir, timeout=5
            )
            if remote_hash.returncode == 0:
                remote_hash = remote_hash.stdout.strip()
                break
        else:
            return None, "Could not find origin/main or origin/master"
        
        # Получаем дату и хэш удаленной версии для отображения
        remote_info = subprocess.run(
            ['git', 'log', '-1', '--format=%cd | %h', '--date=format:%d.%m.%Y', remote_hash],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        remote_display = remote_info.stdout.strip() if remote_info.returncode == 0 else "unknown"
        
        # Проверяем отличаются ли хэши
        if local_hash != remote_hash:
            # Проверяем можно ли сделать fast-forward (без конфликтов)
            merge_base = subprocess.run(
                ['git', 'merge-base', 'HEAD', remote_hash],
                capture_output=True, text=True, cwd=script_dir, timeout=5
            )
            if merge_base.returncode == 0:
                merge_base = merge_base.stdout.strip()
                if merge_base == local_hash:
                    return {
                        'has_update': True,
                        'local_hash': local_hash[:8],
                        'remote_hash': remote_hash[:8],
                        'remote_display': remote_display,
                        'can_fast_forward': True,
                        'local_date': _COMMIT_DATE,
                    }, None
                else:
                    # Есть отхождения от main
                    return {
                        'has_update': True,
                        'local_hash': local_hash[:8],
                        'remote_hash': remote_hash[:8],
                        'remote_display': remote_display,
                        'can_fast_forward': False,
                        'local_date': _COMMIT_DATE,
                    }, None
            else:
                return None, "Failed to check merge status"
        else:
            return {'has_update': False, 'local_date': _COMMIT_DATE, 'remote_display': remote_display}, None
            
    except Exception as e:
        return None, str(e)


def _perform_update():
    """Выполняет git pull для обновления."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    try:
        # Определяем текущую ветку
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"
        
        # Делаем pull
        pull_result = subprocess.run(
            ['git', 'pull', 'origin', current_branch],
            capture_output=True, text=True, cwd=script_dir, timeout=60
        )
        
        if pull_result.returncode == 0:
            return True, pull_result.stdout
        else:
            return False, pull_result.stderr
    except Exception as e:
        return False, str(e)


# Получаем версию при запуске
_COMMIT_DATE, _COMMIT_HASH = _get_version_info()
_BOTINOK_VERSION = f"0.2 | {_COMMIT_DATE} | {_COMMIT_HASH}"

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_PS_URL = "http://localhost:11434/api/ps"

console = Console()

TOOL_OUTPUT_MAX_CHARS = 100000
STREAM_TOOL_TEXT_MAX_CHARS = 12000

HARD_CTX_PCT = 0.90
REPEAT_LINE_WINDOW = 40
REPEAT_LINE_MIN_OCCURRENCES = 6
MAX_TOOL_ROUNDS_PER_TURN = 80
MAX_AUTO_RECOVERIES_PER_TURN = 2
MISSING_FINAL_AUTO_CONTINUE_MAX = 2

# Models that are known to not support the `tools` field in Ollama /api/chat.
MODELS_NO_TOOLS = set()

def _ollama_error_indicates_no_tools(error_msg: str) -> bool:
    if not error_msg:
        return False
    msg = str(error_msg).lower()
    return (
        "does not support tools" in msg
        or "doesn't support tools" in msg
        or "not support tools" in msg
    )

def _ensure_chat_only_system_message(messages: list) -> None:
    if not messages:
        return
    marker = "CHAT_ONLY_MODE"
    for m in messages:
        if m.get("role") == "system" and marker in str(m.get("content", "")):
            return
    messages.append({
        "role": "system",
        "content": (
            f"{marker}\n"
            "В этом режиме инструменты недоступны (tool-calling отключён). "
            "Не предлагай и не описывай использование инструментов, файловых операций или команд. "
            "Отвечай только текстом и, если нужно, проси пользователя выполнить действия вручную."
        ),
    })

_TOOL_STREAM_TAG_RE = re.compile(
    r"(?:<\|[^\n\r]*?\|>|</?[^>\n\r]+?>)",
    re.IGNORECASE,
)

def _trim_tail(text: str, max_chars: int) -> str:
    if not text or max_chars <= 0:
        return "" if not text else str(text)
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]

def _tool_stream_has_payload(text: str) -> bool:
    """True если стриминг инструмента содержит хоть что-то кроме пробелов/тегов."""
    if not text:
        return False
    s = str(text)
    # Remove known special/model tags like <|...|>, <tool_call>, </tool_call>, etc.
    s = _TOOL_STREAM_TAG_RE.sub("", s)
    # Remove punctuation that often appears as scaffolding.
    s = s.replace("{", "").replace("}", "").replace("[", "").replace("]", "")
    s = s.replace("\"", "").replace("'", "").replace(":", "").replace(",", "")
    s = "".join(ch for ch in s if not ch.isspace())
    # If there's at least one alnum, consider it real payload.
    return any(ch.isalnum() for ch in s)

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

def _estimate_messages_tokens(msgs: list) -> int:
    if not msgs:
        return 0
    return sum(_estimate_message_tokens(m) for m in msgs)

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
        safe_args = tool_args
        if tool_name == "code_editor" and isinstance(tool_args, dict):
            safe_args = dict(tool_args)
            for k in ("content", "old_text", "new_text"):
                if k in safe_args and safe_args[k] is not None:
                    try:
                        safe_args[k] = f"<omitted:{len(str(safe_args[k]))} chars>"
                    except Exception:
                        safe_args[k] = "<omitted>"
        args_preview = json.dumps(safe_args, ensure_ascii=False)
    except Exception:
        args_preview = str(tool_args)

    extra_lines = ""
    if tool_name == "code_editor":
        try:
            parsed = json.loads(res_str)
            if isinstance(parsed, dict):
                p = parsed.get("path")
                changed = parsed.get("changed")
                if p is not None:
                    extra_lines += f"\nfile_path: {p}"
                if changed is not None:
                    extra_lines += f"\nchanged: {str(bool(changed)).lower()}"
        except Exception:
            pass

    msg = (
        f"TOOL_RESULT_SUMMARY\n"
        f"tool: {tool_name}\n"
        f"args: {args_preview}\n"
        f"artifact_path: {artifact_path}\n"
        f"size_kb: {size_kb:.2f}\n"
        f"truncated_in_context: {str(truncated).lower()}\n"
        f"content_preview:\n{shown}"
        f"{extra_lines}"
    )
    if truncated:
        msg += f"\n...[TRUNCATED {len(res_str) - TOOL_OUTPUT_MAX_CHARS} chars]"
    return msg


def _session_project_dir(session_path: str) -> str:
    return os.path.join(session_path, "project")


def _resolve_code_editor_target_path(session_path: str, raw_path: str) -> str:
    if os.path.isabs(raw_path):
        return os.path.realpath(raw_path)
    return os.path.realpath(os.path.join(_session_project_dir(session_path), raw_path))


def _is_within(base_dir: str, target_path: str) -> bool:
    base_dir = os.path.realpath(base_dir)
    target_path = os.path.realpath(target_path)
    return target_path == base_dir or target_path.startswith(base_dir + os.sep)


def _code_editor_args_for_display(session_path: str, func_args: dict) -> dict:
    safe = {}
    if isinstance(func_args, dict):
        safe = dict(func_args)
    raw_path = safe.get("path")
    if raw_path:
        safe["path"] = _resolve_code_editor_target_path(session_path, str(raw_path))
    for k in ("content", "old_text", "new_text"):
        if k in safe and safe[k] is not None:
            try:
                safe[k] = f"<omitted:{len(str(safe[k]))} chars>"
            except Exception:
                safe[k] = "<omitted>"
    return safe

def _ollama_summarize_and_reset_context(
    sm: SessionManager,
    model: str,
    session_path: str,
    messages: list,
    num_ctx: int,
    reason: str,
    reserve_tokens: int = 1600,
):
    system_msgs = [m for m in messages if m.get("role") == "system"]

    artifact_name = f"context_overflow_full_{int(time.time())}.json"
    try:
        artifact_path = sm.save_artifact(
            session_path,
            artifact_name,
            json.dumps(messages, ensure_ascii=False, indent=2),
        )
    except Exception:
        artifact_path = f"./artifacts/{artifact_name}"

    summary_system = {
        "role": "system",
        "content": (
            "Ты — BOTINOK. Сформируй краткий протокол сессии для продолжения работы при переполнении контекста. "
            "Не повторяй длинный текст. Не вызывай инструменты.\n\n"
            "Формат:\n"
            "- SESSION_PROTOCOL\n"
            "- reason: ...\n"
            "- key_facts: (5-10 пунктов)\n"
            "- open_questions: (если есть)\n"
            "- next_steps: (3-7 пунктов)\n"
        ),
    }
    summary_user = {
        "role": "user",
        "content": (
            f"Контекст близок к лимиту или модель зациклилась. reason={reason}. "
            f"Полная история сохранена в {artifact_path}. "
            "Сделай протокол сессии, чтобы можно было продолжить работу с чистым контекстом."
        ),
    }

    summary_messages = system_msgs + [summary_system, summary_user]
    summary_messages = _prepare_messages_for_ollama(
        sm,
        session_path,
        summary_messages,
        num_ctx=num_ctx,
        reserve_tokens=reserve_tokens,
    )

    ollama_base_url = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
    verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)
    chat_url = f"{ollama_base_url}/api/chat"

    summary_text = (
        "SESSION_PROTOCOL\n"
        f"reason: {reason}\n"
        f"artifact: {artifact_path}\n"
        "key_facts:\n"
        "- (summary generation failed)\n"
        "next_steps:\n"
        "- Продолжить с очищенным контекстом\n"
    )
    try:
        payload = {
            "model": model,
            "messages": summary_messages,
            "stream": False,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": 450,
            },
        }
        res = requests.post(
            chat_url,
            json=payload,
            timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300),
            verify=verify_ssl,
        )
        if res.status_code == 200:
            data = res.json()
            summary_text = data.get("message", {}).get("content") or summary_text
    except Exception:
        pass

    protocol_msg = {
        "role": "system",
        "content": (
            "Контекст был очищен из-за риска переполнения/зацикливания. "
            f"Полная история: {artifact_path}\n\n"
            f"{summary_text}"
        ),
    }

    messages.clear()
    messages.extend(system_msgs + [protocol_msg])

    return protocol_msg["content"], artifact_path

def _detect_repetition(full_response: str) -> bool:
    if not full_response:
        return False
    lines = [l.strip() for l in full_response.splitlines() if l.strip()]
    if len(lines) < 10:
        return False
    tail = lines[-REPEAT_LINE_WINDOW:]
    last = tail[-1]
    if not last:
        return False
    return sum(1 for l in tail if l == last) >= REPEAT_LINE_MIN_OCCURRENCES

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
        Layout(name="stats", ratio=1),
        Layout(name="tools_panel", ratio=1)
    )
    return layout

class BotVisualizer:
    def __init__(self, model, prompt, num_ctx, dangerous_mode: bool = False):
        self.model = model
        self.prompt = prompt
        self.num_ctx = num_ctx
        self.dangerous_mode = dangerous_mode
        self.response_text = ""
        self.streaming_tool_text = ""
        self.start_time = time.time()
        self.first_token_time = None
        self.last_chunk_time = None
        self.thinking_tokens = 0
        self.response_tokens = 0
        self.tool_tokens = 0 # Новое поле для учета токенов от инструментов
        self.streaming_tool_tokens = 0 # Токены инструмента во время стриминга (из logprobs)
        self.status = "Initializing..."
        self.vram_info = "Checking VRAM..."
        self.current_vram_used = 0
        self.total_vram = 8.0
        self.prompt_eval_count = 0
        self.eval_count = 0
        self.session_ctx_est = 0
        self.active_tools = []
        self.is_proofreader = False
        
    def reset(self, prompt):
        self.prompt = prompt
        self.response_text = ""
        self.streaming_tool_text = ""
        self.start_time = time.time()
        self.first_token_time = None
        self.last_chunk_time = None
        self.thinking_tokens = 0
        self.response_tokens = 0
        self.tool_tokens = 0
        self.streaming_tool_tokens = 0
        self.status = "Initializing..."
        self.prompt_eval_count = 0
        self.eval_count = 0
        self.session_ctx_est = 0
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
        return self.thinking_tokens + self.response_tokens + self.tool_tokens + self.streaming_tool_tokens

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
        danger_tag = " | DANGEROUS MODE: ON" if self.dangerous_mode else ""
        agent_type = "PROOFREADER AGENT" if self.is_proofreader else "BOTINOK AGENT"
        header_style = "bold black on yellow" if self.is_proofreader else "bold white on blue"
        panel_style = "yellow" if self.is_proofreader else "blue"
        
        return Panel(
            Text(f"{agent_type}{danger_tag} | Model: {self.model} | Context: {self.num_ctx} | {self.vram_info}", justify="center", style=header_style),
            style=panel_style
        )

    def get_content_panel(self, width=80, height=20):
        # Собираем весь текст для отображения
        full_display = self.response_text
        if self.streaming_tool_text and _tool_stream_has_payload(self.streaming_tool_text):
            # Очищаем текст от возможных артефактов и добавляем заголовок
            # Используем r-строку или двойное экранирование для Rich разметки
            tool_content = _trim_tail(self.streaming_tool_text, STREAM_TOOL_TEXT_MAX_CHARS)
            tool_content = tool_content.replace("[", "\\[").replace("]", "\\]")
            full_display += f"\n\n[bold magenta]Streaming Tool Call JSON:[/bold magenta]\n{tool_content}"
            
        # Используем Text.from_markup только если есть теги, иначе обычный Text для скорости
        if "[" in full_display:
            try:
                text_obj = Text.from_markup(full_display)
            except Exception:
                text_obj = Text(full_display, style="bold white")
        else:
            text_obj = Text(full_display, style="bold white")

        # console.render_lines делает всю магию учета переносов
        lines = list(text_obj.wrap(console, width - 4)) 
        
        # Если количество строк превышает высоту окна, берем ПОСЛЕДНИЕ height строк
        if len(lines) > height:
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

        no_chunks_for = time.time() - self.last_chunk_time if self.last_chunk_time else 0.0
        
        # Индикатор активности (спиннер)
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        # Используем фиксированное время для синхронизации анимации
        spinner_index = int(time.time() * 5) % len(spinner_chars)
        spinner = spinner_chars[spinner_index]
        
        display_status = self.status
            
        activity = f"[bold magenta]{spinner}[/bold magenta]" if self.status in ["Generating...", "Waiting for tool call...", "Calling Tools...", "Resuming generation...", "Checking Memory...", "Unloading Models...", "Forced VRAM Cleanup...", "Connecting...", "Tool-mode parsing..."] or "Tool:" in self.status else ""

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_row("[cyan]Status:[/cyan]", f"[bold]{display_status}[/bold] {activity}")
        table.add_row("[cyan]Elapsed:[/cyan]", f"{elapsed:.1f}s")
        table.add_row("[cyan]No chunks:[/cyan]", f"{no_chunks_for:.1f}s")
        table.add_row("[cyan]TTFT:[/cyan]", f"[bold yellow]{ttft}[/bold yellow]")
        table.add_row("[cyan]Thinking:[/cyan]", f"[bold yellow]{self.thinking_tokens}[/bold yellow]")
        table.add_row("[cyan]Response:[/cyan]", f"[bold green]{self.response_tokens}[/bold green]")
        table.add_row("[cyan]Stream Tool:[/cyan]", f"[bold magenta]{self.streaming_tool_tokens}[/bold magenta]")
        table.add_row("[cyan]Final Tool:[/cyan]", f"[bold magenta]{self.tool_tokens}[/bold magenta]")
        table.add_row("[cyan]TPS:[/cyan]", f"[bold green]{tps:.2f}[/bold green]")
        
        # VRAM информация
        table.add_row("[cyan]VRAM:[/cyan]", f"[bold yellow]{self.current_vram_used:.2f}GB[/bold yellow]")
        
        # Разделитель
        table.add_row("", "")
        
        session_ctx_pct = (self.session_ctx_est / self.num_ctx) * 100 if self.num_ctx > 0 else 0
        session_ctx_style = "green" if session_ctx_pct < 70 else "yellow" if session_ctx_pct < 90 else "red"
        table.add_row("[cyan]SessionCtx:[/cyan]", f"[{session_ctx_style}]{self.session_ctx_est}/{self.num_ctx} ({session_ctx_pct:.1f}%)[/{session_ctx_style}]")
        
        last_req_ctx_used = self.prompt_eval_count + self.eval_count
        last_req_ctx_pct = (last_req_ctx_used / self.num_ctx) * 100 if self.num_ctx > 0 else 0
        last_req_ctx_style = "green" if last_req_ctx_pct < 70 else "yellow" if last_req_ctx_pct < 90 else "red"
        table.add_row("[cyan]LastReqCtx:[/cyan]", f"[{last_req_ctx_style}]{last_req_ctx_used}/{self.num_ctx} ({last_req_ctx_pct:.1f}%)[/{last_req_ctx_style}]")
        
        # Индикатор общего заполнения окна (прогресс-бар)
        table.add_row("", "")
        table.add_row("[bold cyan]Context Window Fill:[/bold cyan]", "")
        
        bar_width = 20
        filled = int(bar_width * session_ctx_pct / 100) if session_ctx_pct <= 100 else bar_width
        bar = "█" * filled + "░" * (bar_width - filled)
        table.add_row("", f"[{session_ctx_style}]{bar} {session_ctx_pct:.1f}%[/{session_ctx_style}]")
        
        return Panel(table, title="[bold yellow]Performance[/bold yellow]", border_style="yellow", expand=True)

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

def ask_ollama_stream(model, messages, session_path, step_num, num_ctx=8192, vis=None, read_only_mode=False):
    sm = SessionManager()
    tm = ToolManager()
    
    # Если визуализатор не передан, создаем новый (для первого запуска)
    prompt = messages[-1]["content"] if messages else ""
    if vis is None:
        vis = BotVisualizer(model, prompt, num_ctx, dangerous_mode=tm.dangerous_mode)
    else:
        vis.reset(prompt)

    turn_prompt = prompt

    layout = create_layout()
    
    # Подготовка инструментов
    tools = tm.get_tool_definitions()
    
    # Если включен режим read-only (например для корректора), фильтруем инструменты
    if read_only_mode:
        read_only_tools = {}
        for name, desc in tools.items():
            # Пропускаем shell_exec полностью
            if name == "shell_exec":
                continue
            
            # Для остальных инструментов, если у них есть action, оставляем только безопасные
            if "function" in desc and "parameters" in desc["function"]:
                params = desc["function"]["parameters"]
                if "properties" in params and "action" in params["properties"]:
                    actions = params.get("enum", []) # Corrected: action enum is often inside 'action' property itself or handled via type
                    # In our ToolManager, actions are often in properties['action']['enum']
                    prop_action = params["properties"].get("action", {})
                    actions = prop_action.get("enum", [])
                    
                    # Оставляем только те действия, которые похожи на чтение/просмотр
                    safe_actions = [a for a in actions if a in ("read", "list", "search", "grep", "info", "inspect", "tail", "unit_tail", "since", "query", "stats", "get", "get_repo", "get_readme", "get_file", "get_tags", "get_branches")]
                    if safe_actions:
                        # Создаем копию описания с ограниченными действиями
                        new_desc = json.loads(json.dumps(desc))
                        new_desc["function"]["parameters"]["properties"]["action"]["enum"] = safe_actions
                        read_only_tools[name] = new_desc
                    elif name in ("web_search", "open_url", "experience", "github"):
                        # Fallback for tools that might not have explicit action enums in all cases but are safe
                        read_only_tools[name] = desc
                else:
                    # Если у инструмента нет параметра action, но он сам по себе read-only
                    if name in ("web_search", "open_url", "experience", "github"):
                        read_only_tools[name] = desc
        tools = read_only_tools

    tools_list = list(tools.values()) if isinstance(tools, dict) else (tools or [])
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "logprobs": True,
        "options": {
            "num_ctx": num_ctx,
        }
    }

    # Some Ollama models don't support tools; for them we run chat-only mode.
    if model not in MODELS_NO_TOOLS:
        payload["tools"] = tools_list

    # Настройки для минимизации мерцания в SSH (всегда slow mode)
    refresh_rate = 10
    auto_refresh = True
    use_screen = True  # Альтернативный буфер терминала - меньше мерцания

    with Live(layout, refresh_per_second=refresh_rate, screen=use_screen, auto_refresh=auto_refresh) as live:
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
        verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        
        try:
            # Цикл для обработки потенциальных вызовов инструментов
            tool_rounds = 0
            auto_recoveries = 0
            http_retries = 0
            max_http_retries = 2
            changed_project_files = []
            while True:
                tool_rounds += 1
                if tool_rounds > MAX_TOOL_ROUNDS_PER_TURN:
                    if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                        summary, _ = _ollama_summarize_and_reset_context(
                            sm,
                            model,
                            session_path,
                            messages,
                            num_ctx,
                            reason=f"max_tool_rounds_exceeded({MAX_TOOL_ROUNDS_PER_TURN})_recoveries_exhausted({MAX_AUTO_RECOVERIES_PER_TURN})",
                        )
                        sm.update_context(session_path, "assistant", summary)
                        messages.append({"role": "assistant", "content": summary})
                        break

                    summary, artifact_path = _ollama_summarize_and_reset_context(
                        sm,
                        model,
                        session_path,
                        messages,
                        num_ctx,
                        reason=f"max_tool_rounds_exceeded({MAX_TOOL_ROUNDS_PER_TURN})",
                    )
                    auto_recoveries += 1
                    tool_rounds = 0
                    cont_user = {
                        "role": "user",
                        "content": (
                            "Продолжай выполнение последнего запроса пользователя после авто-очистки контекста. "
                            "Не повторяй длинные куски текста. Не зацикливайся. Если нужны детали — смотри в артефактах/логах.\n\n"
                            f"last_user_prompt: {turn_prompt}\n"
                            f"session_path: {session_path}\n"
                            f"full_history_artifact: {artifact_path}\n"
                            "files: response.md, thinking.md, tools.log, session_raw.log, context.json, artifacts/\n"
                            "Твоя цель: завершить задачу пользователя и дать финальный ответ."
                        )
                    }
                    messages.append(cont_user)
                    sm.update_context(session_path, "assistant", summary)
                    sm.update_context(session_path, "user", cont_user["content"])
                    continue

                if model in MODELS_NO_TOOLS:
                    _ensure_chat_only_system_message(messages)

                prepared = _prepare_messages_for_ollama(sm, session_path, messages, num_ctx=num_ctx)
                payload["messages"] = prepared
                if vis is not None:
                    vis.session_ctx_est = _estimate_messages_tokens(prepared)

                # If we discovered this model can't do tools, ensure payload doesn't include them.
                if model in MODELS_NO_TOOLS and payload.get("tools") is not None:
                    payload.pop("tools", None)
                # Создаем поток для выполнения POST запроса, чтобы не блокировать UI на этапе 'Connecting'
                response_queue = queue.Queue()
                def make_request():
                    try:
                        res = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300), verify=verify_ssl)
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
                    live.refresh()
                    if http_retries < max_http_retries:
                        http_retries += 1
                        time.sleep(2)
                        continue
                    fail_msg = f"Connection Error: {req_result}"
                    sm.update_context(session_path, "system", fail_msg)
                    messages.append({"role": "assistant", "content": fail_msg})
                    time.sleep(2)
                    return messages
                
                response = req_result
                
                if response.status_code != 200:
                    error_text = ""
                    error_msg = "Unknown Error"
                    try:
                        data = response.json()
                        if isinstance(data, dict):
                            error_msg = data.get("error", error_msg)
                            error_text = json.dumps(data, ensure_ascii=False, indent=2)
                        else:
                            error_text = str(data)
                    except Exception:
                        try:
                            error_text = (response.text or "")
                        except Exception:
                            error_text = ""

                    # Auto fallback: if model doesn't support tools, retry without tools once.
                    if (
                        response.status_code == 400
                        and _ollama_error_indicates_no_tools(error_msg)
                        and payload.get("tools")
                    ):
                        MODELS_NO_TOOLS.add(model)
                        _ensure_chat_only_system_message(messages)
                        payload.pop("tools", None)
                        vis.status = "Model has no tools support: chat-only mode"
                        layout["stats"].update(vis.get_stats_panel())
                        live.refresh()
                        continue

                    vis.status = f"Ollama Error: {error_msg}"

                    # Persist error context for debugging.
                    ts = int(time.time())
                    try:
                        err_body_path = sm.save_artifact(
                            session_path,
                            f"ollama_http_error_{response.status_code}_{ts}.txt",
                            (error_text or "")[:200_000],
                        )
                    except Exception:
                        err_body_path = f"./artifacts/ollama_http_error_{response.status_code}_{ts}.txt"

                    try:
                        req_payload = {
                            "model": payload.get("model"),
                            "options": payload.get("options"),
                            "messages": payload.get("messages"),
                            "tools_included": bool(payload.get("tools")),
                        }
                        req_payload_path = sm.save_artifact(
                            session_path,
                            f"ollama_http_error_payload_{ts}.json",
                            json.dumps(req_payload, ensure_ascii=False, indent=2),
                        )
                    except Exception:
                        req_payload_path = f"./artifacts/ollama_http_error_payload_{ts}.json"

                    sm.update_context(
                        session_path,
                        "system",
                        (
                            f"Ollama HTTP error {response.status_code}: {error_msg}. "
                            f"Saved artifacts: {err_body_path}, {req_payload_path}"
                        ),
                    )
                    layout["stats"].update(vis.get_stats_panel())
                    live.refresh()
                    if http_retries < max_http_retries:
                        http_retries += 1
                        time.sleep(3)
                        continue
                    fail_msg = f"Ollama HTTP error {response.status_code}: {error_msg}"
                    messages.append({"role": "assistant", "content": fail_msg})
                    return messages

                vis.status = "Generating..."
                vis.last_chunk_time = time.time()
                live.refresh()
                
                full_response = ""
                full_thinking = ""
                tool_calls = []
                metrics = {}
                aborted_reason = None
                
                sm.update_context(session_path, "user", prompt)
                
                thinking_ended = False

                stream_queue = queue.Queue()

                def stream_reader():
                    try:
                        for line in response.iter_lines():
                            stream_queue.put(("line", line))
                        stream_queue.put(("eof", None))
                    except Exception as e:
                        stream_queue.put(("error", str(e)))

                reader_thread = threading.Thread(target=stream_reader, daemon=True)
                reader_thread.start()

                stream_done = False
                stream_error = None
                waiting_status_set = False

                while not stream_done:
                    # Drain all currently available stream items without blocking.
                    while True:
                        try:
                            kind, item = stream_queue.get_nowait()
                        except queue.Empty:
                            break

                        if kind == "eof":
                            stream_done = True
                            break
                        if kind == "error":
                            stream_error = item
                            stream_done = True
                            break

                        line = item
                        if not line:
                            continue

                        vis.last_chunk_time = time.time()
                        waiting_status_set = False

                        try:
                            decoded_line = line.decode('utf-8')
                            chunk = json.loads(decoded_line)

                            msg = chunk.get("message", {})

                            # Обновляем реальные счетчики токенов Ollama, если они присутствуют в чанке
                            if "prompt_eval_count" in chunk:
                                vis.prompt_eval_count = chunk.get("prompt_eval_count", 0)
                            if "eval_count" in chunk:
                                vis.eval_count = chunk.get("eval_count", 0)

                            # Обработка logprobs для стриминга инструментов
                            logprobs = chunk.get("logprobs")
                            if logprobs and isinstance(logprobs, list):
                                for lp in logprobs:
                                    token = lp.get("token", "")
                                    if token is None:
                                        token = ""
                                    vis.streaming_tool_tokens += 1
                                    # Если мы еще не начали получать основной контент или мышление,
                                    # значит это токены инструмента (JSON аргументы)
                                    if not msg.get("content") and not msg.get("thinking"):
                                        if token:
                                            vis.streaming_tool_text += str(token)
                                            vis.streaming_tool_text = _trim_tail(vis.streaming_tool_text, STREAM_TOOL_TEXT_MAX_CHARS)
                                        if not waiting_status_set:
                                            vis.status = "Streaming Tool JSON..."
                                            waiting_status_set = True
                                        
                                        # Гарантируем перерисовку UI при получении токенов инструмента
                                        main_height = console.size.height - 12
                                        main_width = int(console.size.width * 0.66)
                                        layout["content"].update(vis.get_content_panel(width=main_width, height=max(5, main_height)))
                                        layout["stats"].update(vis.get_stats_panel())

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
                                # Очищаем текст стриминга инструмента при переходе к основному ответу
                                if vis.streaming_tool_text:
                                    vis.streaming_tool_text = ""
                                    
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

                                if len(full_response) % 800 == 0 and _detect_repetition(full_response):
                                    aborted_reason = "repetition_detected"
                                    try:
                                        response.close()
                                    except Exception:
                                        pass
                                    stream_done = True
                                    break

                            # Сбор вызовов инструментов
                            if msg.get("tool_calls"):
                                tool_calls.extend(msg.get("tool_calls"))

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
                                stream_done = True
                                break
                        except json.JSONDecodeError:
                            continue

                    if stream_done:
                        break

                    # UI tick (не зависит от прихода новых чанков)
                    no_chunks_for = time.time() - vis.last_chunk_time if vis.last_chunk_time else 0.0
                    if no_chunks_for >= 1.0 and not waiting_status_set:
                        vis.status = "Waiting for tool call..."
                        waiting_status_set = True
                    elif no_chunks_for < 1.0 and vis.status == "Waiting for tool call...":
                        vis.status = "Generating..."

                    main_height = console.size.height - 12
                    main_width = int(console.size.width * 0.66)
                    layout["content"].update(vis.get_content_panel(width=main_width, height=max(5, main_height)))
                    layout["stats"].update(vis.get_stats_panel())

                    if tool_calls or vis.active_tools:
                        layout["tools_panel"].update(vis.get_tools_panel())

                    time.sleep(0.1)

                if stream_error:
                    raise RuntimeError(f"Ollama stream error: {stream_error}")

                if (not tool_calls) and (not full_response.strip()) and full_thinking.strip():
                    aborted_reason = "missing_final_response"
                    if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                        summary, _ = _ollama_summarize_and_reset_context(
                            sm,
                            model,
                            session_path,
                            messages,
                            num_ctx,
                            reason=f"{aborted_reason}_recoveries_exhausted({MAX_AUTO_RECOVERIES_PER_TURN})",
                        )
                        sm.update_context(session_path, "assistant", summary)
                        messages.append({"role": "assistant", "content": summary})
                        break
                    auto_recoveries += 1
                    tool_rounds = 0
                    cont_user = {
                        "role": "user",
                        "content": (
                            "Сформулируй финальный ответ на последний запрос пользователя. "
                            "Не повторяй рассуждения и не вызывай инструменты без необходимости.\n\n"
                            f"last_user_prompt: {turn_prompt}\n"
                            f"session_path: {session_path}\n"
                        ),
                    }
                    messages.append(cont_user)
                    sm.update_context(session_path, "user", cont_user["content"])
                    continue

                if aborted_reason:
                    if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                        summary, _ = _ollama_summarize_and_reset_context(
                            sm,
                            model,
                            session_path,
                            messages,
                            num_ctx,
                            reason=f"{aborted_reason}_recoveries_exhausted({MAX_AUTO_RECOVERIES_PER_TURN})",
                        )
                        sm.update_context(session_path, "assistant", summary)
                        messages.append({"role": "assistant", "content": summary})
                        break

                    summary, artifact_path = _ollama_summarize_and_reset_context(
                        sm,
                        model,
                        session_path,
                        messages,
                        num_ctx,
                        reason=aborted_reason,
                    )
                    auto_recoveries += 1
                    tool_rounds = 0
                    cont_user = {
                        "role": "user",
                        "content": (
                            "Продолжай выполнение последнего запроса пользователя после авто-очистки контекста. "
                            "Не повторяй длинные куски текста. Не зацикливайся. Если нужны детали — смотри в артефактах/логах.\n\n"
                            f"last_user_prompt: {turn_prompt}\n"
                            f"session_path: {session_path}\n"
                            f"full_history_artifact: {artifact_path}\n"
                            "files: response.md, thinking.md, tools.log, session_raw.log, context.json, artifacts/\n"
                            "Твоя цель: завершить задачу пользователя и дать финальный ответ."
                        )
                    }
                    messages.append(cont_user)
                    sm.update_context(session_path, "assistant", summary)
                    sm.update_context(session_path, "user", cont_user["content"])
                    continue

                ctx_used = metrics.get("prompt_eval_count", 0) + metrics.get("eval_count", 0)
                if num_ctx > 0 and ctx_used >= int(num_ctx * HARD_CTX_PCT):
                    if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                        summary, _ = _ollama_summarize_and_reset_context(
                            sm,
                            model,
                            session_path,
                            messages,
                            num_ctx,
                            reason=f"hard_ctx_threshold_reached({ctx_used}/{num_ctx})_recoveries_exhausted({MAX_AUTO_RECOVERIES_PER_TURN})",
                        )
                        sm.update_context(session_path, "assistant", summary)
                        messages.append({"role": "assistant", "content": summary})
                        break

                    summary, artifact_path = _ollama_summarize_and_reset_context(
                        sm,
                        model,
                        session_path,
                        messages,
                        num_ctx,
                        reason=f"hard_ctx_threshold_reached({ctx_used}/{num_ctx})",
                    )
                    auto_recoveries += 1
                    tool_rounds = 0
                    cont_user = {
                        "role": "user",
                        "content": (
                            "Продолжай выполнение последнего запроса пользователя после авто-очистки контекста. "
                            "Не повторяй длинные куски текста. Не зацикливайся. Если нужны детали — смотри в артефактах/логах.\n\n"
                            f"last_user_prompt: {turn_prompt}\n"
                            f"session_path: {session_path}\n"
                            f"full_history_artifact: {artifact_path}\n"
                            "files: response.md, thinking.md, tools.log, session_raw.log, context.json, artifacts/\n"
                            "Твоя цель: завершить задачу пользователя и дать финальный ответ."
                        )
                    }
                    messages.append(cont_user)
                    sm.update_context(session_path, "assistant", summary)
                    sm.update_context(session_path, "user", cont_user["content"])
                    continue

                # In chat-only mode ignore any tool calls if the model emitted them.
                if model in MODELS_NO_TOOLS and tool_calls:
                    tool_calls = []

                # Если нет вызовов инструментов, выходим из цикла генерации
                if not tool_calls:
                    # Сохраняем финальный ответ этой итерации
                    sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
                    messages.append({"role": "assistant", "content": full_response})
                    break

                # Обработка вызовов инструментов
                vis.status = "Tool-mode parsing..."
                # Очищаем текст стриминга после завершения генерации чанка
                vis.streaming_tool_text = ""
                
                layout["stats"].update(vis.get_stats_panel())
                live.refresh()
                vis.status = "Calling Tools..."
                live.refresh()
                
                # Добавляем ответ ассистента с вызовами инструментов в историю
                messages.append({"role": "assistant", "content": full_response, "tool_calls": tool_calls})
                sm.update_context(session_path, "assistant", full_response, thinking=full_thinking, tool_calls=tool_calls)
                
                for tool_call in tool_calls:
                    func_name = tool_call["function"]["name"]
                    func_args = tool_call["function"]["arguments"]

                    effective_session_path = session_path
                    if func_name == "code_editor" and isinstance(func_args, dict):
                        raw_path = str(func_args.get("path", ""))
                        resolved = _resolve_code_editor_target_path(session_path, raw_path) if raw_path else ""
                        project_dir = _session_project_dir(session_path)

                        # Default: relative paths go into session_path/project/.
                        if raw_path and (not os.path.isabs(raw_path)):
                            func_args["path"] = resolved

                        # If user tries to write outside session dir, require explicit confirmation and run against repo root.
                        if raw_path and os.path.isabs(raw_path) and (not _is_within(session_path, resolved)):
                            effective_session_path = None

                        # If write target is outside project workspace (but still within session), require confirmation.
                        needs_confirm = True
                        if resolved and _is_within(project_dir, resolved):
                            needs_confirm = False
                        
                        # Read action inside session directory is ALWAYS safe.
                        if func_name == "code_editor" and func_args.get("action") == "read" and _is_within(session_path, resolved):
                            needs_confirm = False

                        # Store for later UI display.
                        func_args_display = _code_editor_args_for_display(session_path, func_args)
                    else:
                        func_args_display = func_args
                    
                    # Логика подтверждения для опасных инструментов
                    if func_name in ("shell_exec", "code_editor") and tm.dangerous_mode:
                        if func_name == "code_editor" and isinstance(func_args, dict):
                            ans = "y"
                            # Skip confirmation for safe edits inside session project workspace.
                            if 'needs_confirm' in locals() and not needs_confirm:
                                pass
                            else:
                                live.stop()

                                warn_text = ""
                                if effective_session_path is None:
                                    warn_text = (
                                        "\n\n[bold red]ВНИМАНИЕ:[/bold red] путь находится вне папки сессии. "
                                        "Это может изменить файлы проекта."
                                    )
                                else:
                                    # Within session but outside project dir.
                                    resolved_path = None
                                    try:
                                        resolved_path = str(func_args_display.get('path'))
                                    except Exception:
                                        resolved_path = None
                                    if resolved_path and (not _is_within(_session_project_dir(session_path), resolved_path)):
                                        warn_text = (
                                            "\n\n[bold yellow]Предупреждение:[/bold yellow] путь находится вне "
                                            "`session_path/project/`. Рекомендуется хранить файлы проекта в этой папке."
                                        )

                                console.print("\n" + "═" * 80)
                                console.print(Panel(
                                    Markdown(
                                        f"### Запрос на использование инструмента: `{func_name}`\n\n"
                                        f"**Аргументы (sanitized):**\n```json\n{json.dumps(func_args_display, indent=2, ensure_ascii=False)}\n```"
                                        f"{warn_text}"
                                    ),
                                    title="[bold red]ВНИМАНИЕ: ОПАСНОЕ ДЕЙСТВИЕ[/bold red]",
                                    border_style="red"
                                ))

                                ans = console.input("\n[bold yellow]Разрешить выполнение? (y/n): [/bold yellow]").strip().lower()

                                if ans not in ("y", "yes", "д", "да"):
                                    reason = console.input("[bold cyan]Укажите причину отказа для бота: [/bold cyan]").strip()
                                    if not reason:
                                        reason = "Отменено пользователем без объяснения причин."

                                    result = f"ОТКАЗАНО ПОЛЬЗОВАТЕЛЕМ. Причина: {reason}"
                                    live.start()
                                    vis.add_tool_activity(func_name, str(func_args_display), status="aborted")

                                    compact_msg = _compact_tool_message(func_name, func_args_display, result, "")
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call["id"],
                                        "name": func_name,
                                        "content": compact_msg
                                    })
                                    sm.update_context(session_path, "tool", compact_msg)
                                    continue

                                live.start()

                            # code_editor approved (or skipped) -> do not run generic confirmation panel.
                        else:
                            # Останавливаем Live UI для ввода и выполнения интерактивных команд
                            live.stop()
                            
                            console.print("\n" + "═" * 80)
                            console.print(Panel(
                                Markdown(f"### Запрос на использование инструмента: `{func_name}`\n\n**Аргументы:**\n```json\n{json.dumps(func_args, indent=2, ensure_ascii=False)}\n```"),
                                title="[bold red]ВНИМАНИЕ: ОПАСНОЕ ДЕЙСТВИЕ[/bold red]",
                                border_style="red"
                            ))
                            
                            ans = console.input("\n[bold yellow]Разрешить выполнение? (y/n): [/bold yellow]").strip().lower()
                        
                        if ans not in ("y", "yes", "д", "да"):
                            reason = console.input("[bold cyan]Укажите причину отказа для бота: [/bold cyan]").strip()
                            if not reason:
                                reason = "Отменено пользователем без объяснения причин."
                            
                            result = f"ОТКАЗАНО ПОЛЬЗОВАТЕЛЕМ. Причина: {reason}"
                            # Перезапускаем Live UI перед продолжением
                            live.start()
                            vis.add_tool_activity(func_name, str(func_args), status="aborted")
                            
                            # Добавляем результат отказа в историю
                            compact_msg = _compact_tool_message(func_name, func_args, result, "")
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "name": func_name,
                                "content": compact_msg
                            })
                            sm.update_context(session_path, "tool", compact_msg)
                            continue
                        
                        # Если это shell_exec, выполняем его ПРЯМО ЗДЕСЬ (синхронно),
                        # пока Live UI остановлен, чтобы обеспечить интерактивность.
                        if func_name == "shell_exec":
                            vis.add_tool_activity(func_name, str(func_args), "running")
                            try:
                                # Вызываем напрямую через tm.call_tool, так как Live UI уже остановлен
                                result = tm.call_tool(func_name, func_args, session_path=session_path)
                            except Exception as e:
                                result = f"Error calling tool: {str(e)}"
                            
                            # Сохраняем артефакт и результат
                            artifact_file = f"tool_{func_name}_{int(time.time())}.txt"
                            artifact_path = sm.save_artifact(session_path, artifact_file, str(result))
                            
                            compact_msg = _compact_tool_message(func_name, func_args, result, artifact_path)

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "name": func_name,
                                "content": compact_msg
                            })
                            sm.update_context(session_path, "tool", compact_msg)
                            
                            vis.update_tool_activity(func_name, "completed", size_kb=len(str(result))/1024)
                            
                            console.print("\n" + "─" * 40)
                            console.print("[bold green]Команда завершена.[/bold green]")
                            user_comment = console.input("[bold cyan]Нажмите Enter для возврата или введите комментарий для модели: [/bold cyan]").strip()
                            
                            if user_comment:
                                result = f"ВЫВОД КОМАНДЫ:\n{result}\n\nКОММЕНТАРИЙ ПОЛЬЗОВАТЕЛЯ:\n{user_comment}"
                            
                            # Обновляем сообщение в истории с учетом комментария
                            compact_msg = _compact_tool_message(func_name, func_args, result, artifact_path)
                            messages[-1]["content"] = compact_msg
                            sm.update_context(session_path, "tool", compact_msg)
                            
                            # Перезапускаем Live UI и переходим к следующему инструменту
                            live.start()
                            continue

                        # Для code_editor просто возвращаем Live UI, он выполнится асинхронно ниже
                        live.start()

                    if func_name == "code_editor" and isinstance(func_args_display, dict):
                        query_display = str(func_args_display.get("path") or func_args.get("path") or "")
                    else:
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
                            res = tm.call_tool(func_name, func_args, session_path=effective_session_path)
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

                    # Track changed files for code_editor without leaking content.
                    if func_name == "code_editor":
                        try:
                            parsed = json.loads(str(result))
                            if isinstance(parsed, dict) and parsed.get("changed") and parsed.get("path"):
                                changed_project_files.append(str(parsed.get("path")))
                        except Exception:
                            pass

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
            err_msg = f"Error: {str(e)}"
            try:
                vis.status = err_msg
                layout["stats"].update(vis.get_stats_panel())
            except Exception:
                pass
            try:
                sm.update_context(session_path, "system", err_msg)
            except Exception:
                pass
            messages.append({"role": "assistant", "content": err_msg})
            time.sleep(2)
            return messages

def ask_ollama_stealth(model, messages, session_path, step_num, num_ctx=8192, read_only_mode=False):
    sm = SessionManager()
    tm = ToolManager()
    
    prompt = messages[-1]["content"] if messages else ""
    tools = tm.get_tool_definitions()
    
    if read_only_mode:
        read_only_tools = {}
        for name, desc in tools.items():
            if name == "shell_exec":
                continue
            if "function" in desc and "parameters" in desc["function"]:
                params = desc["function"]["parameters"]
                if "properties" in params and "action" in params["properties"]:
                    prop_action = params["properties"].get("action", {})
                    actions = prop_action.get("enum", [])
                    
                    safe_actions = [a for a in actions if a in ("read", "list", "search", "grep", "info", "inspect", "tail", "unit_tail", "since", "query", "stats", "get", "get_repo", "get_readme", "get_file", "get_tags", "get_branches")]
                    if safe_actions:
                        new_desc = json.loads(json.dumps(desc))
                        new_desc["function"]["parameters"]["properties"]["action"]["enum"] = safe_actions
                        read_only_tools[name] = new_desc
                    elif name in ("web_search", "open_url", "experience", "github"):
                        read_only_tools[name] = desc
                else:
                    if name in ("web_search", "open_url", "experience", "github"):
                        read_only_tools[name] = desc
        tools = read_only_tools

    tools_list = list(tools.values()) if isinstance(tools, dict) else (tools or [])
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "logprobs": True,
        "options": {
            "num_ctx": num_ctx,
        }
    }

    # Some Ollama models don't support tools; for them we run chat-only mode.
    if model not in MODELS_NO_TOOLS:
        payload["tools"] = tools_list

    sm.write_file_header(session_path, "thinking.md", model, num_ctx, prompt)
    sm.write_file_header(session_path, "response.md", model, num_ctx, prompt)
    
    ollama_base_url = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
    OLLAMA_CHAT_URL = f"{ollama_base_url}/api/chat"
    verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)
    
    try:
        while True:
            if model in MODELS_NO_TOOLS:
                _ensure_chat_only_system_message(messages)

            payload["messages"] = _prepare_messages_for_ollama(sm, session_path, messages, num_ctx=num_ctx)

            # If we discovered this model can't do tools, ensure payload doesn't include them.
            if model in MODELS_NO_TOOLS and payload.get("tools") is not None:
                payload.pop("tools", None)

            response = requests.post(OLLAMA_CHAT_URL, json=payload, stream=True, timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300), verify=verify_ssl)
            
            if response.status_code != 200:
                error_msg = ""
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        error_msg = data.get("error", "")
                    else:
                        error_msg = str(data)
                except Exception:
                    try:
                        error_msg = response.text or ""
                    except Exception:
                        error_msg = ""

                # Auto fallback: if model doesn't support tools, retry without tools once.
                if (
                    response.status_code == 400
                    and _ollama_error_indicates_no_tools(error_msg)
                    and payload.get("tools")
                ):
                    MODELS_NO_TOOLS.add(model)
                    _ensure_chat_only_system_message(messages)
                    payload.pop("tools", None)
                    continue

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

                        # Обработка logprobs для стриминга инструментов (stealth mode)
                        logprobs = chunk.get("logprobs")
                        if logprobs and isinstance(logprobs, list):
                            # В stealth моде просто пропускаем или можем логировать, 
                            # но здесь нет визуализатора для обновления счетчиков
                            pass

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

def _choose_or_resume_session(sm: SessionManager, stealth_mode: bool, default_suffix: str) -> tuple[str, str]:
    """Выбор сессии при старте.

    Returns:
      (session_path, resume_last_answer)
    """
    if stealth_mode or (not sys.stdin.isatty()):
        return sm.create_session(default_suffix), ""

    sessions = sm.list_sessions()
    if not sessions:
        return sm.create_session(default_suffix), ""

    latest = sessions[0]
    latest_name = latest.get("name") or "(unknown)"

    choices = [
        (f"Продолжить последнюю: {latest_name}", "continue_latest"),
        ("Выбрать другую сессию", "choose"),
        ("Начать новую сессию", "new"),
    ]
    answers = inquirer.prompt([
        inquirer.List(
            'session_action',
            message="Старт BOTINOK: выбрать сессию",
            choices=choices,
            default="continue_latest",
        )
    ])

    if not answers:
        return sm.create_session(default_suffix), ""

    action = answers.get('session_action')
    if action == "new":
        return sm.create_session(default_suffix), ""

    if action == "choose":
        session_options = []
        for s in sessions:
            name = s.get("name") or "(unknown)"
            path = s.get("path") or ""
            mtime = s.get("mtime")
            try:
                ts = datetime.fromtimestamp(float(mtime)).strftime("%Y-%m-%d %H:%M:%S") if mtime else "unknown"
            except Exception:
                ts = "unknown"
            preview = ""
            if path and os.path.isdir(path):
                preview = sm.load_first_user_prompt(path, max_chars=120)
            if preview:
                session_options.append((f"{name:<35} | {ts} | {preview}", path))
            else:
                session_options.append((f"{name:<45} | {ts}", path))

        picked = inquirer.prompt([
            inquirer.List(
                'session_path',
                message="Выберите сессию для продолжения (Имя | last_modified)",
                choices=session_options,
                default=latest.get("path"),
            )
        ])

        if not picked:
            return sm.create_session(default_suffix), ""

        chosen_path = picked.get('session_path')
        if chosen_path and os.path.isdir(chosen_path):
            sm.ensure_session_structure(chosen_path)
            return chosen_path, sm.load_last_assistant_answer(chosen_path)

        return sm.create_session(default_suffix), ""

    if latest.get("path") and os.path.isdir(latest.get("path")):
        sm.ensure_session_structure(latest["path"])
        return latest["path"], sm.load_last_assistant_answer(latest["path"])

    return sm.create_session(default_suffix), ""

def run_proofreader_turn(model, session_path, num_ctx, developer_messages, vis=None):
    """Выполняет один ход корректора."""
    sm = SessionManager()
    proofreader_history = sm.load_proofreader_history(session_path)
    
    # Подготовка контекста для корректора
    # Мы передаем ему системный промпт, его историю и текущее состояние дел
    if not proofreader_history:
        proofreader_history.append({
            "role": "system",
            "content": (
                "Ты — КОРРЕКТОР (Proofreader). Твоя задача — анализировать работу Исполнителя (разработчика). "
                "Ты подключаешься после того, как Исполнитель выполнил запрос. "
                "У тебя чистый контекст, но ты видишь логи сессии, протоколы и результат. "
                "Изучи файлы в session_path, особенно response.md, thinking.md, tools.log. "
                "Сделай заключение: что сделано правильно, а что нужно исправить. "
                "Будь критичен, ищи зацикливания, ошибки в коде или логике. "
                "Твое заключение будет передано Исполнителю для правок. "
                "Ты должен помнить свои предыдущие замечания и проверять их выполнение."
            )
        })

    # Формируем максимально краткий отчет для корректора
    status_report = (
        f"ОТЧЕТ ДЛЯ КОРРЕКТОРА:\n"
        f"Папка сессии: {session_path}\n"
        f"Задача Исполнителя была: {developer_messages[0].get('content')[:500] if developer_messages else 'Неизвестно'}\n"
        "Твоя задача: самостоятельно изучить файлы в папке сессии (проект, логи, артефакты) "
        "с помощью инструментов и вынести вердикт о качестве работы Исполнителя.\n"
        "Используй `file_system action=list` для начала обзора."
    )
    
    proofreader_history.append({"role": "user", "content": status_report})
    
    # Запускаем генерацию корректора (с инструментами только для чтения)
    # Используем stealth mode для корректора внутри, или stream если хотим видеть процесс
    if vis:
        vis.status = "Proofreader is thinking..."
        vis.model = model
        vis.is_proofreader = True
        # Для корректора создаем временные сообщения, чтобы не портить основной визуал
        proof_messages = ask_ollama_stream(model, proofreader_history, session_path, "proofreader", num_ctx, vis, read_only_mode=True)
        # Возвращаем оригинальные параметры в визуал после окончания
        vis.is_proofreader = False
    else:
        proof_messages = ask_ollama_stealth(model, proofreader_history, session_path, "proofreader", num_ctx, read_only_mode=True)
    
    # Сохраняем обновленную историю корректора
    sm.save_proofreader_history(session_path, proof_messages)
    
    # Возвращаем последнее заключение корректора
    feedback = proof_messages[-1]["content"] if proof_messages else "No feedback from proofreader."
    
    # Сохраняем вердикт в отдельный файл артефакта, чтобы агент мог на него сослаться
    verdict_file = f"proofreader_verdict_{int(time.time())}.md"
    verdict_path = sm.save_artifact(session_path, verdict_file, feedback)
    
    return feedback, verdict_path

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
    parser.add_argument("--dangerous", action="store_true", help="Разрешить опасные инструменты (редактирование файлов и выполнение команд) только в этой сессии")
    parser.add_argument("--proofread", action="store_true", help="Включить режим корректора (цикл: Исполнитель -> Корректор)")
    parser.add_argument("--debug", action="store_true", help="Включить отладочный вывод")
    parser.add_argument("--update", action="store_true", help="Проверить и установить обновления из git")
    
    args = parser.parse_args()
    
    # Обработка обновления
    if args.update:
        console.print("[bold cyan]Проверка обновлений BOTINOK...[/bold cyan]")
        
        result, error = _check_remote_version()
        
        if error:
            console.print(f"[bold red]Ошибка проверки обновлений:[/bold red] {error}")
            # Если это установленная версия (не git), предлагаем переустановить
            if "Not a git repository" in error:
                console.print("[yellow]Похоже BOTINOK установлен не из git.[/yellow]")
                console.print("[yellow]Для обновления запустите:[/yellow]")
                console.print("[green]  curl -sSL https://raw.githubusercontent.com/siv237/botinok/main/install.sh | bash[/green]")
            return
        
        if not result['has_update']:
            console.print(f"[bold green]У вас актуальная версия![/bold green]")
            console.print(f"[cyan]Текущая версия:[/cyan] {result['local_date']} | {_COMMIT_HASH}")
            return
        
        # Есть обновление
        console.print(f"\n[bold yellow]Доступно обновление![/bold yellow]")
        console.print(f"[cyan]Текущая версия:[/cyan] {result['local_date']} | {result['local_hash']}")
        console.print(f"[green]Новая версия:[/green] {result['remote_display']}")
        
        if not result['can_fast_forward']:
            console.print("[yellow]\nВнимание: у вас есть локальные изменения, отсутствующие в основной ветке.[/yellow]")
            console.print("[yellow]Обновление может потребовать ручного разрешения конфликтов.[/yellow]")
        
        # Спрашиваем подтверждение
        from rich.prompt import Confirm
        if Confirm.ask("\n[bold cyan]Установить обновление?[/bold cyan]", default=True):
            console.print("[bold cyan]Обновление...[/bold cyan]")
            success, output = _perform_update()
            
            if success:
                console.print("[bold green]Обновление успешно установлено![/bold green]")
                console.print(f"[dim]{output}[/dim]")
                console.print("\n[bold yellow]Перезапустите BOTINOK для применения изменений.[/bold yellow]")
            else:
                console.print("[bold red]Ошибка при обновлении:[/bold red]")
                console.print(f"[red]{output}[/red]")
                console.print("[yellow]Попробуйте обновить вручную:[/yellow]")
                console.print("[green]  git pull origin main[/green]")
        else:
            console.print("[yellow]Обновление отменено.[/yellow]")
        return
    
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
    if args.dangerous:
        os.environ["BOTINOK_DANGEROUS"] = "1"
    if args.debug:
        os.environ["BOTINOK_DEBUG"] = "1"

    # Если есть данные в stdin (Pipe mode), добавляем их к промпту
    stdin_data = ""
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            if arg_prompt:
                arg_prompt = f"{stdin_data}\n\n{arg_prompt}"
            else:
                arg_prompt = stdin_data

    session_suffix = "visual_run" if not stealth_mode else "stealth_run"
    session_path, resume_last_answer = _choose_or_resume_session(sm, stealth_mode, session_suffix)
    
    # Подготовка начальных сообщений из промптов
    now = datetime.now().astimezone()
    steps_subdir = sm.config.get('Storage', 'StepsSubDir', fallback='steps')
    
    system_time_msg = sm.load_prompt(session_path, "system_time", 
                                     TIMESTAMP=now.isoformat(), 
                                     TZNAME=now.tzname() or "unknown")
    
    session_location_msg = sm.load_prompt(session_path, "session_location",
                                          SESSION_PATH=session_path,
                                          PROJECT_DIR=os.path.join(session_path, 'project'))
    
    session_files_msg = sm.load_prompt(session_path, "session_files",
                                       SESSION_PATH=session_path,
                                       CONTEXT_JSON=os.path.join(session_path, 'context.json'),
                                       RESPONSE_MD=os.path.join(session_path, 'response.md'),
                                       THINKING_MD=os.path.join(session_path, 'thinking.md'),
                                       TOOLS_LOG=os.path.join(session_path, 'tools.log'),
                                       SESSION_RAW_LOG=os.path.join(session_path, 'session_raw.log'),
                                       PERFORMANCE_LOG=os.path.join(session_path, 'performance.log'),
                                       STEPS_DIR=os.path.join(session_path, steps_subdir),
                                       ARTIFACTS_DIR=os.path.join(session_path, 'artifacts'),
                                       PROJECT_DIR=os.path.join(session_path, 'project'),
                                       PROMPTS_DIR=os.path.join(session_path, 'prompts'))
    
    tool_policy_msg = sm.load_prompt(session_path, "tool_policy")
    
    dangerous_status = "ON" if args.dangerous else "OFF"
    dangerous_details = ("В этой сессии разрешены опасные инструменты: code_editor, shell_exec. shell_exec всегда требует подтверждение пользователя перед выполнением." 
                        if args.dangerous else "Опасные инструменты отключены.")
    dangerous_mode_msg = sm.load_prompt(session_path, "dangerous_mode",
                                        DANGEROUS_STATUS=dangerous_status,
                                        DANGEROUS_DETAILS=dangerous_details)

    # Проверка сломанных инструментов
    tm = ToolManager()
    broken_tools_info = tm.get_broken_tools_info() or ""
    broken_tools_msg = sm.load_prompt(session_path, "broken_tools", BROKEN_TOOLS_INFO=broken_tools_info) if broken_tools_info else ""

    resume_context_msg = ""
    if resume_last_answer:
        resume_context_msg = sm.load_prompt(session_path, "resume_context", 
                                            RESUME_LAST_ANSWER=resume_last_answer)
    messages = [
        {"role": "system", "content": system_time_msg},
        {"role": "system", "content": session_location_msg},
        {"role": "system", "content": session_files_msg},
        {"role": "system", "content": tool_policy_msg},
        {"role": "system", "content": dangerous_mode_msg},
    ]

    if broken_tools_msg:
        messages.append({"role": "system", "content": broken_tools_msg})

    if resume_context_msg:
        messages.append({"role": "system", "content": resume_context_msg})
    
    vis = BotVisualizer(model, "", num_ctx, dangerous_mode=args.dangerous)
    step_num = 1

    # Вывод ASCII арта и версии (только если не stealth_mode)
    if not stealth_mode:
        term_width = console.width
        if term_width >= 100:
            ascii_art = f"""
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
    [bold yellow]BOTINOK AGENT - Version {_BOTINOK_VERSION}[/bold yellow]
    """
            console.print(Panel(Text.from_markup(ascii_art), border_style="blue"))
        else:
            # Компактный баннер для узких консолей
            console.print(Panel(
                Text(f"BOTINOK AGENT - Version {_BOTINOK_VERSION}", style="bold yellow"),
                border_style="blue"
            ))

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

            # Добавляем компактную памятку по инструментам ПЕРЕД началом хода (turn)
            tool_reminder_msg = sm.load_prompt(session_path, "tool_reminder",
                                               PROMPTS_DIR=os.path.join(session_path, 'prompts'))
            if tool_reminder_msg:
                messages.append({
                    "role": "system",
                    "content": tool_reminder_msg
                })

            missing_final_retries = 0
            while True:
                turn_start_idx = len(messages)
                messages.append({"role": "user", "content": prompt})

                try:
                    if stealth_mode:
                        messages = ask_ollama_stealth(model, messages, session_path, step_num, num_ctx)
                    else:
                        messages = ask_ollama_stream(model, messages, session_path, step_num, num_ctx, vis)
                except KeyboardInterrupt:
                    # Обработка Ctrl+C - предлагаем выбор
                    if not stealth_mode:
                        console.print("\n[bold yellow]Прервать выполнение?[/bold yellow]")
                        from rich.prompt import Prompt
                        ans = Prompt.ask("[bold cyan]Введите:[/bold cyan] (c)ontinue - вернуться к вводу, (q)uit - выйти, (r)etry - повторить", choices=["c", "q", "r"], default="c")
                        if ans == "q":
                            console.print("[bold red]Завершение работы...[/bold red]")
                            raise SystemExit(0)
                        elif ans == "r":
                            console.print("[bold yellow]Повторяем запрос...[/bold yellow]")
                            continue
                        else:
                            console.print("[bold green]Возврат к вводу[/bold green]")
                            messages.pop()  # Удаляем последнее сообщение пользователя
                            break
                    else:
                        # В stealth mode просто выходим
                        console.print("\n[bold red]Interrupted[/bold red]")
                        raise SystemExit(0)

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
                        console.print(Markdown(last_assistant_message))
                    
                    # --- РЕЖИМ КОРРЕКТОРА ---
                    if args.proofread:
                        console.print("\n[bold magenta]>>> ПРОВЕРКА КОРРЕКТОРОМ...[/bold magenta]")
                        feedback, verdict_path = run_proofreader_turn(model, session_path, num_ctx, messages, None if stealth_mode else vis)
                        
                        # Явно сбрасываем флаг корректора, чтобы UI вернулся в синий цвет
                        if vis:
                            vis.is_proofreader = False
                        
                        console.print("\n[bold magenta]ЗАКЛЮЧЕНИЕ КОРРЕКТОРА:[/bold magenta]")
                        console.print(Markdown(feedback))
                        console.print("\n" + "═" * console.width + "\n")
                        
                        fb_low = feedback.lower()
                        exit_keywords = ["замечаний нет", "все верно", "исправлено", "проверка завершена", "принято", "замечаний не обнаружено", "все в порядке"]
                        if any(kw in fb_low for kw in exit_keywords):
                            console.print("[bold green]Корректор одобрил работу.[/bold green]")
                            step_num += 1
                            break
                        
                        if not stealth_mode:
                            ans = Confirm.ask("[bold yellow]Выполнить правки согласно замечаниям корректора?[/bold yellow]", default=True)
                            if not ans:
                                step_num += 1
                                break
                        
                        # Передаем замечания исполнителю с прямой ссылкой на файл вердикта
                        prompt = (
                            f"КОРРЕКТОР ОБНАРУЖИЛ ОШИБКИ/НЕДОЧЕТЫ.\n"
                            f"Полный текст замечаний сохранен в файле: {verdict_path}\n\n"
                            f"Краткое резюме:\n{feedback[:2000]}\n\n"
                            "Исправь свою работу в соответствии с этими замечаниями. "
                            "Обязательно прочитай файл вердикта, если резюме обрезано."
                        )
                        continue
                    
                    step_num += 1
                    break

                if stealth_mode:
                    break

                if missing_final_retries >= MISSING_FINAL_AUTO_CONTINUE_MAX:
                    console.print("\n[bold red]Final Response отсутствует: текущий turn завершился без нового ответа ассистента (возможно ошибка или ранний выход).[/bold red]")
                    console.print("\n" + "─" * console.width + "\n")
                    step_num += 1
                    break

                missing_final_retries += 1
                sm.update_context(session_path, "system", f"Auto-continue: missing final response (attempt {missing_final_retries}/{MISSING_FINAL_AUTO_CONTINUE_MAX})")
                prompt = (
                    "Продолжай и дай финальный ответ на последний запрос пользователя. "
                    "Не повторяй рассуждения и не вызывай инструменты без необходимости."
                )

    except SystemExit:
        raise
    finally:
        if not stealth_mode:
            console.print(f"\n[bold blue]Session saved to: {session_path}[/bold blue]")

if __name__ == "__main__":
    main()
