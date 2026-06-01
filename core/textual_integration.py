"""
Интеграция Textual App с стримингом Ollama.

Полная замена Rich Live на Textual App с:
- Tool-calls loop (как в ask_ollama_stream)
- VRAM background prep
- Context overflow handling
- Proper UI callbacks (add_tool_activity, append_assistant_chunk, etc.)
- Repetition detection and recovery
"""

import os
import queue
import threading
import time
import json
import re
import requests
from typing import Optional, List, Dict, Callable

from core.session_manager import SessionManager
from core.tool_manager import ToolManager
from core.textual_app import BotinokTextualApp

MODELS_NO_TOOLS = set()

TOOL_OUTPUT_MAX_CHARS = 100000
STREAM_TOOL_TEXT_MAX_CHARS = 12000
HARD_CTX_PCT = 0.90
MAX_TOOL_ROUNDS_PER_TURN = 80
MAX_AUTO_RECOVERIES_PER_TURN = 2
REPEAT_LINE_WINDOW = 40
REPEAT_LINE_MIN_OCCURRENCES = 6

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
    if not text:
        return False
    s = str(text)
    s = _TOOL_STREAM_TAG_RE.sub("", s)
    s = s.replace("{", "").replace("}", "").replace("[", "").replace("]", "")
    s = s.replace("\"", "").replace("'", "").replace(":", "").replace(",", "")
    s = "".join(ch for ch in s if not ch.isspace())
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


def _prepare_messages_for_ollama(sm, session_path, messages, num_ctx, reserve_tokens=1200):
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


def _ollama_error_indicates_no_tools(error_msg: str) -> bool:
    if not error_msg:
        return False
    msg = str(error_msg).lower()
    return "does not support tools" in msg or "doesn't support tools" in msg or "not support tools" in msg


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


def _compact_tool_message(tool_name, tool_args, result, artifact_path):
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


def ask_ollama_textual(
    model: str,
    messages: List[Dict],
    session_path: str,
    num_ctx: int = 8192,
    dangerous_mode: bool = False,
) -> List[Dict]:
    sm = SessionManager()
    tm = ToolManager()

    ollama_base_url = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
    ollama_chat_url = f"{ollama_base_url}/api/chat"
    verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)
    request_timeout = sm.config.getint('Ollama', 'RequestTimeout', fallback=300)

    app = BotinokTextualApp(session_path=session_path)
    app.set_model_info(model, dangerous=dangerous_mode)

    stream_active = threading.Event()
    stream_active.clear()
    input_enabled = threading.Event()
    input_enabled.set()

    def _call_from_thread(fn, *args, **kwargs):
        try:
            app.call_from_thread(fn, *args, **kwargs)
        except Exception:
            try:
                fn(*args, **kwargs)
            except Exception:
                pass

    def _update_stats(**kwargs):
        s = dict(app.stats_data)
        s.update(kwargs)
        _call_from_thread(app.update_stats, **s)

    def _add_tool(name, query, status="running", size_kb=0):
        _call_from_thread(app.add_tool_activity, name, query, status, size_kb)

    def _update_tool(name, status="completed", size_kb=0):
        _call_from_thread(app.update_tool_activity, name, status, size_kb)

    def _append_user(text):
        _call_from_thread(app.append_user_message, text)

    def _append_chunk(content="", thinking=""):
        _call_from_thread(app.append_assistant_chunk, content, thinking)

    def _finalize_turn(content, thinking="", tool_calls=None):
        _call_from_thread(app.finalize_assistant_turn, content, thinking, tool_calls)

    def _append_tool_result(tool_name, result):
        _call_from_thread(app.append_tool_result, tool_name, result)

    def _write_log(text):
        _call_from_thread(app.rich_log.write, text)

    _stream_buf = []
    _thinking_buf = []

    def _flush_thinking_buf():
        nonlocal _thinking_buf
        if _thinking_buf:
            text = "".join(_thinking_buf)
            _thinking_buf = []
            _call_from_thread(app.append_assistant_chunk, thinking=text)

    def _flush_stream_buf():
        nonlocal _stream_buf
        if _stream_buf:
            text = "".join(_stream_buf)
            _stream_buf = []
            _call_from_thread(app.append_assistant_chunk, content=text)

    def _stream_chunk(content: str):
        nonlocal _stream_buf
        _stream_buf.append(content)
        if "\n" in content:
            _flush_stream_buf()
        elif len("".join(_stream_buf)) > 200:
            _flush_stream_buf()

    def _stream_thought(thought: str):
        nonlocal _thinking_buf
        _thinking_buf.append(thought)
        if "\n" in thought:
            _flush_thinking_buf()
        elif len("".join(_thinking_buf)) > 200:
            _flush_thinking_buf()

    def _set_input_enabled(enabled):
        if enabled:
            input_enabled.set()
        else:
            input_enabled.clear()
        try:
            input_widget = app.query_one("#input")
            _call_from_thread(setattr, input_widget, "disabled", not enabled)
        except Exception:
            pass

    def _do_vram_prep():
        try:
            _update_stats(status="Checking Memory...")
            try:
                status = sm.get_ollama_status()
            except Exception:
                status = None
            if status and "models" in status:
                vram_info_parts = []
                for m in status["models"]:
                    vram = m.get("size_vram", 0) / (1024**3)
                    vram_info_parts.append(f"{m['name']}: {vram:.2f}GB")
                    if vram > 7.0 or (m['name'] != model and len(status['models']) > 0):
                        _update_stats(status="Unloading Models...")
                        try:
                            sm.unload_models()
                        except Exception:
                            pass
                        break
                vram_str = " | ".join(vram_info_parts) if vram_info_parts else "No models loaded"
                _update_stats(vram=vram_str, status="Ready")
            else:
                _update_stats(vram="No models loaded", status="Ready")
        except Exception:
            _update_stats(status="Ready")

    def _stream_turn(user_text):
        nonlocal _stream_buf
        stream_active.set()
        _set_input_enabled(False)
        _update_stats(status="Connecting...")
        current_model = sm.config.get('Ollama', 'DefaultModel', fallback='qwen3.5:9b')
        current_ctx = sm.config.getint('Ollama', 'DefaultContext', fallback=8192)
        current_ollama_chat_url = f"{sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')}/api/chat"
        current_verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        current_timeout = sm.config.getint('Ollama', 'RequestTimeout', fallback=300)

        if current_model in MODELS_NO_TOOLS:
            _ensure_chat_only_system_message(messages)

        tool_rounds = 0
        auto_recoveries = 0
        turn_prompt = user_text

        while True:
            tool_rounds += 1
            if tool_rounds > MAX_TOOL_ROUNDS_PER_TURN:
                if auto_recoveries >= MAX_AUTO_RECOVERIES_PER_TURN:
                    break
                auto_recoveries += 1
                tool_rounds = 0
                cont_user_content = sm.load_prompt(
                    session_path, "auto_continue",
                    LAST_USER_PROMPT=turn_prompt,
                    SESSION_PATH=session_path,
                )
                cont_user = {"role": "user", "content": cont_user_content or f"Continue task: {turn_prompt[:100]}"}
                messages.append(cont_user)
                sm.update_context(session_path, "user", cont_user["content"])
                continue

            prepared = _prepare_messages_for_ollama(sm, session_path, messages, num_ctx=current_ctx)
            session_ctx_est = _estimate_messages_tokens(prepared)
            _update_stats(session_ctx=session_ctx_est, session_ctx_max=current_ctx)

            tools = tm.get_tool_definitions()
            tools_list = list(tools.values()) if isinstance(tools, dict) else (tools or [])

            payload = {
                "model": current_model,
                "messages": prepared,
                "stream": True,
                "logprobs": True,
                "options": {"num_ctx": current_ctx},
            }

            if current_model not in MODELS_NO_TOOLS:
                payload["tools"] = tools_list
            elif payload.get("tools") is not None:
                payload.pop("tools", None)

            _update_stats(status="Generating...")

            try:
                response = requests.post(
                    current_ollama_chat_url, json=payload, stream=True,
                    timeout=current_timeout, verify=current_verify_ssl,
                )
            except Exception as e:
                _write_log(f"[red]Connection Error: {e}[/red]")
                _update_stats(status=f"Connection Error")
                break

            if response.status_code != 200:
                error_msg = "Unknown Error"
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        error_msg = data.get("error", error_msg)
                except Exception:
                    error_msg = response.text[:500] if response.text else "Unknown Error"

                if (
                    response.status_code == 400
                    and _ollama_error_indicates_no_tools(error_msg)
                    and payload.get("tools")
                ):
                    MODELS_NO_TOOLS.add(current_model)
                    _ensure_chat_only_system_message(messages)
                    payload.pop("tools", None)
                    _update_stats(status="Chat-only mode (no tools)")
                    continue

                _write_log(f"[red]Ollama Error {response.status_code}: {error_msg}[/red]")
                _update_stats(status=f"Ollama Error")
                break

            full_response = ""
            full_thinking = ""
            tool_calls = []
            start_time = time.time()
            first_token_time = None
            thinking_tokens = 0
            response_tokens = 0
            streaming_tool_text = ""
            streaming_tool_tokens = 0
            prompt_eval_count = 0
            eval_count = 0
            last_chunk_time = time.time()
            _stream_buf.clear()
            _thinking_buf.clear()
            _call_from_thread(app.start_assistant_turn)

            sm.update_context(session_path, "user", user_text)

            for line in response.iter_lines():
                if not line:
                    continue

                last_chunk_time = time.time()
                _call_from_thread(app.report_chunk)

                try:
                    chunk = json.loads(line.decode('utf-8', errors='replace'))
                except json.JSONDecodeError:
                    continue

                msg = chunk.get("message", {})

                if "prompt_eval_count" in chunk:
                    prompt_eval_count = chunk.get("prompt_eval_count", 0)
                if "eval_count" in chunk:
                    eval_count = chunk.get("eval_count", 0)

                logprobs = chunk.get("logprobs")
                if logprobs and isinstance(logprobs, list):
                    for lp in logprobs:
                        tok = lp.get("token", "")
                        if tok and not tok.startswith("<|") and not tok.endswith("|>"):
                            streaming_tool_tokens += 1

                thought = msg.get("thinking", "")
                if thought:
                    full_thinking += thought
                    thinking_tokens += 1
                    _stream_thought(thought)

                token = msg.get("content", "")
                if token:
                    full_response += token
                    response_tokens += 1
                    if not first_token_time:
                        first_token_time = time.time()
                    _stream_chunk(content=token)

                tc_list = msg.get("tool_calls")
                if tc_list:
                    tool_calls.extend(tc_list)
                    for tc in tc_list:
                        func = tc.get("function", {})
                        tool_name = func.get("name", "unknown")
                        try:
                            tool_args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                        except Exception:
                            tool_args = {}
                        args_display = json.dumps(tool_args, ensure_ascii=False)[:60]
                        _add_tool(tool_name, args_display)

                if chunk.get("done"):
                    elapsed = time.time() - start_time
                    ttft_val = first_token_time - start_time if first_token_time else elapsed
                    tps_val = (thinking_tokens + response_tokens + streaming_tool_tokens) / (time.time() - first_token_time) if first_token_time and (time.time() - first_token_time) > 0 else 0

                    last_req_ctx = prompt_eval_count + eval_count
                    _update_stats(
                        status="Processing tool calls..." if tool_calls else "Done",
                        elapsed=elapsed,
                        ttft=f"{ttft_val:.2f}s",
                        thinking_tokens=thinking_tokens,
                        response_tokens=response_tokens,
                        stream_tool_tokens=streaming_tool_tokens,
                        tps=tps_val,
                        session_ctx=session_ctx_est,
                        last_req_ctx=last_req_ctx,
                    )
                    break
            else:
                _update_stats(status="Stream ended without done")
                break

            _flush_thinking_buf()
            _flush_stream_buf()

            if _detect_repetition(full_response):
                sm.update_context(session_path, "system", "Repetition detected, auto-continuing")
                cont_content = sm.load_prompt(
                    session_path, "auto_continue",
                    LAST_USER_PROMPT=turn_prompt,
                    SESSION_PATH=session_path,
                )
                messages.append({"role": "assistant", "content": full_response, "thinking": full_thinking, "tool_calls": tool_calls if tool_calls else None})
                sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
                cont_user = {"role": "user", "content": cont_content or f"Continue task: {turn_prompt[:100]}"}
                messages.append(cont_user)
                sm.update_context(session_path, "user", cont_user["content"])
                _finalize_turn(full_response, full_thinking)
                continue

            _flush_thinking_buf()
            _flush_stream_buf()

            if tool_calls:
                messages.append({"role": "assistant", "content": full_response, "thinking": full_thinking, "tool_calls": tool_calls})
                sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)

                _finalize_turn(full_response, full_thinking, tool_calls)

                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "unknown")
                    tc_id = tc.get("id", "")
                    try:
                        tool_args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                    except Exception:
                        tool_args = {}

                    _add_tool(tool_name, json.dumps(tool_args, ensure_ascii=False)[:60], status="running")

                    progress_callback = None
                    if tool_name == "curl":

                        def _make_curl_cb(tn=tool_name):
                            last_reported = [0.0]

                            def cb(bytes_downloaded, total_bytes):
                                size_kb = bytes_downloaded / 1024
                                if total_bytes > 0:
                                    pct = (bytes_downloaded / total_bytes) * 100
                                    _update_tool(tn, status="running", size_kb=size_kb)
                                else:
                                    if bytes_downloaded - last_reported[0] > 10240:
                                        _update_tool(tn, status="running", size_kb=size_kb)
                                        last_reported[0] = bytes_downloaded
                            return cb

                        progress_callback = _make_curl_cb()

                    effective_session_path = session_path
                    if tool_name == "code_editor" and isinstance(tool_args, dict):
                        raw_path = tool_args.get("path", "")
                        if raw_path and not os.path.isabs(raw_path):
                            project_dir = os.path.join(session_path, "project")
                            tool_args["path"] = os.path.realpath(os.path.join(project_dir, raw_path))

                    tool_result = tm.call_tool(
                        tool_name,
                        tool_args,
                        session_path=effective_session_path,
                        progress_callback=progress_callback,
                    )

                    res_str = "" if tool_result is None else str(tool_result)
                    size_kb = len(res_str.encode('utf-8', errors='ignore')) / 1024

                    artifact_name = f"tool_{tool_name}_{int(time.time())}.txt"
                    try:
                        artifact_path = sm.save_artifact(session_path, artifact_name, res_str[:200_000])
                    except Exception:
                        artifact_path = f"./artifacts/{artifact_name}"

                    compact_msg = _compact_tool_message(tool_name, tool_args, tool_result, artifact_path)

                    tool_message = {
                        "role": "tool",
                        "name": tool_name,
                        "content": compact_msg,
                    }
                    if tc_id:
                        tool_message["tool_call_id"] = tc_id

                    messages.append(tool_message)
                    sm.update_context(session_path, "tool", compact_msg)

                    _update_tool(tool_name, status="completed", size_kb=size_kb)
                    _append_tool_result(tool_name, compact_msg[:500])

                tool_reminder_msg = sm.load_prompt(session_path, "tool_reminder",
                                                    PROMPTS_DIR=os.path.join(session_path, 'prompts'))
                if tool_reminder_msg:
                    messages.append({"role": "system", "content": tool_reminder_msg})

                user_text = ""
                continue
            else:
                messages.append({"role": "assistant", "content": full_response, "thinking": full_thinking})
                sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
                _finalize_turn(full_response, full_thinking)
                break

        session_ctx_est = _estimate_messages_tokens(messages)
        _update_stats(session_ctx=session_ctx_est, status="Ready")
        _flush_thinking_buf()
        _flush_stream_buf()
        stream_active.clear()
        _set_input_enabled(True)

    _current_model = model
    _current_ctx = num_ctx
    _last_user_text = ""
    _ollama_chat_url = ollama_chat_url
    _verify_ssl = verify_ssl
    _request_timeout = request_timeout

    def _get_ollama_models():
        try:
            url = ollama_base_url.rstrip("/") + "/api/tags"
            r = requests.get(url, timeout=5, verify=_verify_ssl)
            if r.status_code == 200:
                data = r.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def _handle_slash_command(cmd: str):
        nonlocal _current_model, _current_ctx, _ollama_chat_url
        parts = cmd.strip().split()
        command = parts[0].lower()

        if command == "/help":
            _write_log("[bold cyan]📋 Доступные команды:[/bold cyan]")
            _write_log("  [green]/model <name>[/green]  — сменить модель (например /model qwen3.5:9b)")
            _write_log("  [green]/models[/green]         — список доступных моделей Ollama")
            _write_log("  [green]/ctx <n>[/green]         — сменить размер контекста (например /ctx 32768)")
            _write_log("  [green]/clear[/green]          — очистить экран")
            _write_log("  [green]/dangerous[/green]      — переключить dangerous mode")
            _write_log("  [green]/retry[/green]          — повторить последний запрос")
            _write_log("  [green]/vram[/green]           — показать статус VRAM")
            _write_log("  [green]exit[/green]            — выход")
            _write_log("")

        elif command == "/models":
            _write_log("[bold cyan]🔍 Получаю список моделей...[/bold cyan]")
            models = _get_ollama_models()
            if models:
                _write_log("[bold cyan]📦 Доступные модели:[/bold cyan]")
                for m in models:
                    tag = "[green]●[/green]" if _current_model == m else "[dim]○[/dim]"
                    _write_log(f"  {tag} {m}")
            else:
                _write_log("[red]Не удалось получить список моделей[/red]")

        elif command == "/model":
            if len(parts) < 2:
                _write_log(f"[yellow]Текущая модель: {_current_model}[/yellow]")
                _write_log("[dim]Использование: /model <имя_модели>[/dim]")
            else:
                new_model = parts[1]
                _current_model = new_model
                sm.config.set('Ollama', 'DefaultModel', new_model)
                with open(sm.config_path, 'w') as cf:
                    sm.config.write(cf)
                _write_log(f"[green]✅ Модель сменена на: {new_model}[/green]")
                _write_log("[dim]Новая модель будет использована в следующем запросе.[/dim]")

        elif command == "/ctx":
            if len(parts) < 2:
                _write_log(f"[yellow]Текущий контекст: {_current_ctx}[/yellow]")
            else:
                try:
                    new_ctx = int(parts[1])
                    if new_ctx < 1024:
                        _write_log("[red]Минимальный контекст: 1024[/red]")
                    else:
                        _current_ctx = new_ctx
                        sm.config.set('Ollama', 'DefaultContext', str(new_ctx))
                        with open(sm.config_path, 'w') as cf:
                            sm.config.write(cf)
                        _update_stats(session_ctx_max=new_ctx)
                        _write_log(f"[green]✅ Контекст сменён на: {new_ctx}[/green]")
                except ValueError:
                    _write_log("[red]Неверное число[/red]")

        elif command == "/clear":
            app.clear_log()

        elif command == "/dangerous":
            current = os.environ.get("BOTINOK_DANGEROUS", "0") == "1"
            new_val = "0" if current else "1"
            os.environ["BOTINOK_DANGEROUS"] = new_val
            tm.dangerous_mode = not current
            status = "[green]ON[/green]" if not current else "[red]OFF[/red]"
            _write_log(f"[yellow]⚠️ Dangerous mode: {status}[/yellow]")

        elif command == "/vram":
            _write_log("[bold cyan]🔍 Проверяю VRAM...[/bold cyan]")
            try:
                status = sm.get_ollama_status()
                if status and "models" in status:
                    for m in status["models"]:
                        vram = m.get("size_vram", 0) / (1024**3)
                        _write_log(f"  [cyan]{m['name']}[/cyan] — VRAM: [yellow]{vram:.2f}GB[/yellow]")
                else:
                    _write_log("[dim]Нет загруженных моделей[/dim]")
            except Exception as e:
                _write_log(f"[red]Ошибка: {e}[/red]")

        elif command == "/retry":
            if _last_user_text:
                on_user_input(_last_user_text)
            else:
                _write_log("[yellow]Нет предыдущего запроса для повтора[/yellow]")

        else:
            _write_log(f"[yellow]Неизвестная команда: {command}. Введите /help для списка команд.[/yellow]")

    def on_user_input(text: str):
        nonlocal _last_user_text
        if text.lower() in ("exit", "quit", "выход"):
            app.exit()
            return

        if stream_active.is_set():
            return

        _last_user_text = text
        nonlocal _ollama_chat_url, _request_timeout, _verify_ssl
        ollama_base_url_updated = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        _ollama_chat_url = f"{ollama_base_url_updated}/api/chat"
        _verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)

        messages.append({"role": "user", "content": text})
        sm.update_context(session_path, "user", text)

        worker = threading.Thread(target=_stream_turn, args=(text,), daemon=True)
        worker.start()

    app.on_submit = on_user_input
    app.on_slash_command = _handle_slash_command
    app._vram_prep_fn = _do_vram_prep

    app.run()

    return messages
