import os
import sys
import time
import json
import requests
import argparse
import re
from datetime import datetime
from core.cli_io import out, term_width
from core.textual_prompts import textual_confirm
from core.session_manager import SessionManager
from core.tool_manager import ToolManager
from core.openai_compat import is_openai_backend, chat_stream_request
from core.textual_history_viewer import view_history
from core.textual_integration import ask_ollama_textual

import subprocess
import shutil

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


# Системные бинарники, которые нужны инструментам и рендеру.
_SYSTEM_TOOLS = (
    ("curl", "curl"),
    ("lynx", "lynx"),
    ("jq", "jq"),
    ("aria2c", "aria2"),
    ("file", "file"),
    ("git", "git"),
    ("chafa", "chafa"),      # рендер изображений в чате и пейджере
    ("ffmpeg", "ffmpeg"),    # транскод аудио для omni-моделей
)

# Пакетный менеджер -> (команда установки, команда обновления индексов).
_PKG_MANAGERS = (
    ("apt-get", ["apt-get", "install", "-y"], ["apt-get", "update", "-y"]),
    ("dnf", ["dnf", "install", "-y"], None),
    ("yum", ["yum", "install", "-y"], None),
    ("brew", ["brew", "install"], None),
)


def _missing_system_tools() -> list:
    """Список отсутствующих системных инструментов (binary, пакет)."""
    return [(binary, pkg) for binary, pkg in _SYSTEM_TOOLS if shutil.which(binary) is None]


def _missing_packages() -> list:
    seen, out = set(), []
    for _binary, pkg in _missing_system_tools():
        if pkg not in seen:
            seen.add(pkg)
            out.append(pkg)
    return out


def _pkg_manager():
    for name, install, update in _PKG_MANAGERS:
        if shutil.which(name):
            return name, install, update
    return None, None, None


def _run_priv(cmd: list, timeout: int = 900):
    """Запустить команду установки: root — напрямую, иначе sudo -n (без пароля)."""
    if os.geteuid() != 0:
        if shutil.which("sudo"):
            cmd = ["sudo", "-n"] + cmd
        else:
            return None
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _system_deps_warning() -> str:
    missing = _missing_system_tools()
    if not missing:
        return ""
    items = ", ".join(f"{b} (пакет {p})" for b, p in missing)
    return ("\n[!] Не хватает системных зависимостей: " + items +
            "\n    Поставь их: `botinok --ensure-deps` (или `bash update.sh`), "
            "либо повторно запусти install.sh (sudo bash install.sh).")


def _ensure_system_deps(verbose: bool = True) -> str:
    """Проверить и доустановить ВСЕ системные компоненты.

    Ключевое отличие от прежнего `_ensure_chafa`: ставит весь список
    `_SYSTEM_TOOLS` (curl/lynx/jq/aria2c/file/git/chafa/ffmpeg), а не только
    chafa, и вызывается независимо от факта обновления git.
    """
    if not _missing_system_tools():
        return "[+] Системные зависимости на месте."
    name, install, update = _pkg_manager()
    pkgs = _missing_packages()
    if not install:
        return ("[!] Не найден пакетный менеджер. Установи вручную: "
                + ", ".join(pkgs))
    if os.geteuid() != 0 and not shutil.which("sudo"):
        return ("[!] Нужны права root для установки: " + ", ".join(pkgs)
                + " (запусти под root: `sudo botinok --ensure-deps`).")

    lines = [f"[i] Ставлю системные компоненты: {', '.join(pkgs)}"]
    # apt без свежих индексов часто не находит пакет — обновляем индекс.
    if update and name == "apt-get":
        r = _run_priv(update)
        if r is not None and r.returncode != 0:
            lines.append("[i] apt-get update не прошёл — пробую установку как есть.")
    r = _run_priv(install + pkgs)
    if r is None:
        lines.append("[!] Не удалось выполнить установщик (нет прав/timeout).")
    elif r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip().splitlines()
        lines.append("[!] Ошибка установки: " + " | ".join(err[-3:])[:300])
    still = _missing_packages()
    if still:
        lines.append("[!] Не удалось поставить: " + ", ".join(still)
                     + " — поставь вручную и перезапусти.")
    else:
        lines.append("[+] Все системные компоненты установлены.")
    return "\n".join(lines)



def _perform_update():
    """Выполняет git pull для обновления и при необходимости обновляет зависимости Python."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    try:
        # Запоминаем текущий хэш перед pull
        old_hash_result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        old_hash = old_hash_result.stdout.strip() if old_hash_result.returncode == 0 else None
        
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
        
        if pull_result.returncode != 0:
            return False, pull_result.stderr
        
        # Проверяем, изменился ли requirements.txt
        if old_hash:
            diff_result = subprocess.run(
                ['git', 'diff', '--name-only', old_hash, 'HEAD'],
                capture_output=True, text=True, cwd=script_dir, timeout=5
            )
            if diff_result.returncode == 0:
                changed_files = diff_result.stdout.strip().split('\n')
                if 'requirements.txt' in changed_files:
                    # Обнаружено изменение requirements.txt - запускаем установку
                    pip_result = subprocess.run(
                        [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
                        capture_output=True, text=True, cwd=script_dir, timeout=120
                    )
                    pip_output = pip_result.stdout if pip_result.returncode == 0 else pip_result.stderr
                    return True, (f"{pull_result.stdout}\n[Обнаружено изменение requirements.txt]"
                                  f"\nОбновление зависимостей:\n{pip_output}{_system_deps_warning()}"
                                  f"\n{_ensure_system_deps()}")
        
        return True, pull_result.stdout + _system_deps_warning() + "\n" + _ensure_system_deps()
    except Exception as e:
        return False, str(e)


# Получаем версию при запуске
_COMMIT_DATE, _COMMIT_HASH = _get_version_info()
_BOTINOK_VERSION = f"0.4 | {_COMMIT_DATE} | {_COMMIT_HASH}"

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_PS_URL = "http://localhost:11434/api/ps"


TOOL_OUTPUT_MAX_CHARS = 100000

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

def _has_audio_message(messages) -> bool:
    """Есть ли в истории аудио-сообщение (медиа, которое надо слать как input_audio).

    Аудио в Ollama доставляется только через OpenAI/pv1 (input_audio), поэтому
    ход с аудио надо перенаправлять на /v1 даже при backend=ollama."""
    return any(
        isinstance(m, dict) and m.get("media_kind") == "audio" and m.get("audios")
        for m in messages
    )


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
            for k in ("content", "old_text", "new_text", "edits"):
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

            # Аудио доставляется только через /v1 (input_audio) — перенаправляем ход
            # с аудио на openai-путь даже при backend=ollama.
            use_openai_backend = is_openai_backend(sm) or _has_audio_message(messages)

            if use_openai_backend:
                response = chat_stream_request(
                    sm,
                    payload,
                    timeout=sm.config.getint('Ollama', 'RequestTimeout', fallback=300),
                    verify_ssl=verify_ssl,
                )
            else:
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

                if os.environ.get("BOTINOK_DEBUG"):
                    import traceback as _tb
                    print(f"[stealth] HTTP {response.status_code}: {str(error_msg)[:800]}", file=sys.stderr)
                    _tb.print_stack()
                return messages

            full_response = ""
            full_thinking = ""
            tool_calls = []
            
            sm.update_context(session_path, "user", prompt)
            
            for line in response.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8', errors='replace'))
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
                
                # Special handling for vision/audio tools - add multimodal content for omni models
                if func_name == "vision" and isinstance(result, dict) and result.get("image_data"):
                    vision_prompt = result.get("prompt", "Опиши что ты видишь на этом изображении")
                    messages.append({
                        "role": "user",
                        "content": vision_prompt,
                        "images": [result["image_data"]]
                    })
                elif func_name == "audio" and isinstance(result, dict) and result.get("audio_data"):
                    audio_prompt = result.get("prompt", "Опиши, что ты слышишь в этом аудио")
                    messages.append({
                        "role": "user",
                        "content": audio_prompt,
                        "audios": [result["audio_data"]],
                        "media_kind": "audio",
                        "mime_type": result.get("mime_type", "audio/wav"),
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "content": compact_msg,
                        "tool_call_id": tool_call.get("id")
                    })
                
                sm.log_step(session_path, f"tool_{func_name}_{int(time.time())}", tool_call, {"result": result}, {})

            payload["messages"] = messages
            
        return messages
            
    except Exception:
        if os.environ.get("BOTINOK_DEBUG"):
            import traceback as _tb
            _tb.print_exc()
        return messages

def _choose_or_resume_session(sm: SessionManager, stealth_mode: bool, default_suffix: str) -> tuple[str | None, str]:
    """Выбор сессии при старте.

    Returns:
      (session_path, resume_last_answer) или (None, "") при отмене
    """
    if stealth_mode or (not sys.stdin.isatty()):
        return sm.create_session(default_suffix), ""

    sessions = sm.list_sessions()
    if not sessions:
        return sm.create_session(default_suffix), ""

    latest = sessions[0]
    latest_name = latest.get("name") or "(unknown)"

    # Данные для Textual-экрана выбора: имя, путь, mtime. Превью первого запроса
    # и размер папки экран досчитывает САМ, в фоне — иначе открытие списка ждёт
    # перебор тысяч файлов во всех сессиях.
    session_data = [
        {
            "name": s.get("name") or "(unknown)",
            "path": s.get("path") or "",
            "mtime": s.get("mtime"),
        }
        for s in sessions
    ]

    from core.session_picker import pick_session
    try:
        action, chosen_path = pick_session(
            session_data, latest_name, preview_loader=sm.load_first_user_prompt
        )
    except KeyboardInterrupt:
        return None, ""

    if action == "cancel":
        return None, ""
    if action == "new":
        return sm.create_session(default_suffix), ""
    if action == "latest":
        chosen_path = latest.get("path") or ""

    if chosen_path and os.path.isdir(chosen_path):
        sm.ensure_session_structure(chosen_path)
        return chosen_path, sm.load_last_assistant_answer(chosen_path)

    return sm.create_session(default_suffix), ""

def run_proofreader_turn(model, session_path, num_ctx, developer_messages):
    """Выполняет один ход корректора (headless, без UI)."""
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
        "ПОШАГОВЫЙ АЛГОРИТМ:\n"
        "1. Вызови `file_system action=list` чтобы получить список файлов\n"
        "2. ОБЯЗАТЕЛЬНО вызови `file_system action=read` для файлов thinking.md, response.md, tools.log\n"
        "3. Проанализируй содержимое и выдай заключение: что сделано правильно, что исправить\n"
        "НЕ выдавай вердикт без чтения содержимого файлов!"
    )
    
    proofreader_history.append({"role": "user", "content": status_report})
    
    # Запускаем генерацию корректора (с инструментами только для чтения)
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
    
    # Уведомление о используемом конфиге
    if sm.config_source == "personal":
        out(f"[dim cyan]Using personal config: {sm.config_path}[/dim cyan]")
    
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
    parser.add_argument("--ensure-deps", action="store_true", help="Проверить и установить системные зависимости (chafa, ffmpeg, aria2 и др.)")
    parser.add_argument("--view-history", metavar="SESSION_PATH", help="Просмотр истории сессии через Textual (с прокруткой)")
    
    args = parser.parse_args()

    # Установка системных зависимостей (без обновления кода).
    if args.ensure_deps:
        out(_ensure_system_deps())
        return

    # Обработка просмотра истории через Textual
    if args.view_history:
        out("[bold cyan]Запуск просмотра истории через Textual...[/bold cyan]")
        view_history(args.view_history)
        return

    # Обработка мастера настройки
    if args.wizard:
        from core.config_wizard import ConfigWizard
        wizard = ConfigWizard()
        wizard.run()
        return

    # Обработка обновления
    if args.update:
        out("[bold cyan]Проверка обновлений BOTINOK...[/bold cyan]")

        # Компоненты ставим ВСЕГДА, независимо от того, есть ли новый коммит:
        # иначе обновление на актуальной версии не доустанавливает chafa/ffmpeg.
        out(_ensure_system_deps())

        result, error = _check_remote_version()
        
        if error:
            out(f"[bold red]Ошибка проверки обновлений:[/bold red] {error}")
            # Если это установленная версия (не git), предлагаем переустановить
            if "Not a git repository" in error:
                out("[yellow]Похоже BOTINOK установлен не из git.[/yellow]")
                out("[yellow]Для обновления запустите:[/yellow]")
                out("[green]  curl -sSL https://raw.githubusercontent.com/siv237/botinok/main/install.sh | bash[/green]")
            return
        
        if not result['has_update']:
            out(f"[bold green]У вас актуальная версия![/bold green]")
            out(f"[cyan]Текущая версия:[/cyan] {result['local_date']} | {_COMMIT_HASH}")
            return
        
        # Есть обновление
        out(f"\n[bold yellow]Доступно обновление![/bold yellow]")
        out(f"[cyan]Текущая версия:[/cyan] {result['local_date']} | {result['local_hash']}")
        out(f"[green]Новая версия:[/green] {result['remote_display']}")
        
        if not result['can_fast_forward']:
            out("[yellow]\nВнимание: у вас есть локальные изменения, отсутствующие в основной ветке.[/yellow]")
            out("[yellow]Обновление может потребовать ручного разрешения конфликтов.[/yellow]")
        
        # Спрашиваем подтверждение
        _do_update = True
        if sys.stdin.isatty():
            _do_update = bool(textual_confirm("Установить обновление?", default=True))
        if _do_update:
            out("[bold cyan]Обновление...[/bold cyan]")
            success, output = _perform_update()
            
            if success:
                out("[bold green]Обновление успешно установлено![/bold green]")
                out(f"[dim]{output}[/dim]")
                out("\n[bold yellow]Перезапустите BOTINOK для применения изменений.[/bold yellow]")
            else:
                out("[bold red]Ошибка при обновлении:[/bold red]")
                out(f"[red]{output}[/red]")
                out("[yellow]Попробуйте обновить вручную:[/yellow]")
                out("[green]  git pull origin main[/green]")
        else:
            out("[yellow]Обновление отменено.[/yellow]")
        return

    # Обработка Textual режима (по умолчанию)
    # Stealth/pipe-режим (аргумент --stealth или данные в stdin) обслуживается
    # headless-циклом ниже — Textual его не должен перехватывать.
    if not args.stealth and sys.stdin.isatty():
        if args.dangerous:
            os.environ["BOTINOK_DANGEROUS"] = "1"
        if args.debug:
            os.environ["BOTINOK_DEBUG"] = "1"

        session_suffix = "visual_run"
        session_path, resume_last_answer = _choose_or_resume_session(sm, False, session_suffix)
        if not session_path:
            out("[yellow]Сессия не выбрана. Выход.[/yellow]")
            return

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
        if resume_last_answer:
            # На восстановлении инструкции про обязательную проверку навыков
            # модели не отправляются вовсе.
            tool_policy_msg = SessionManager.strip_skills_mandate(tool_policy_msg)

        dangerous_status = "ON" if args.dangerous else "OFF"
        dangerous_details = ("В этой сессии разрешены опасные инструменты: code_editor, shell_exec. shell_exec всегда требует подтверждение пользователя перед выполнением."
                            if args.dangerous else "Опасные инструменты отключены.")
        dangerous_mode_msg = sm.load_prompt(session_path, "dangerous_mode",
                                             DANGEROUS_STATUS=dangerous_status,
                                             DANGEROUS_DETAILS=dangerous_details)

        tm = ToolManager()
        broken_tools_info = tm.get_broken_tools_info() or ""
        broken_tools_msg = sm.load_prompt(session_path, "broken_tools", BROKEN_TOOLS_INFO=broken_tools_info) if broken_tools_info else ""

        resume_session_msg = ""
        if resume_last_answer:
            brief = sm.build_resume_brief(session_path)
            resume_session_msg = sm.load_prompt(session_path, "resume_session", **brief)
            if not resume_session_msg:
                resume_session_msg = sm.load_prompt(session_path, "resume_context",
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

        if resume_session_msg:
            messages.append({"role": "system", "content": resume_session_msg})

        ask_ollama_textual(
            model=args.model,
            messages=messages,
            session_path=session_path,
            num_ctx=args.ctx,
            dangerous_mode=args.dangerous,
            version=_BOTINOK_VERSION,
            initial_prompt=(args.prompt or args.prompt_pos or ""),
            proofread=args.proofread,
            proofreader_fn=run_proofreader_turn,
            resume_session=bool(resume_last_answer),
        )
        return

    # Определяем параметры из аргументов или конфига
    arg_prompt = args.prompt if args.prompt else args.prompt_pos
    model = args.model
    num_ctx = args.ctx
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

    session_path, resume_last_answer = _choose_or_resume_session(sm, True, "stealth_run")
    
    # Если пользователь отменил выбор сессии - выходим
    if session_path is None:
        out("\n[dim]Старт отменён.[/dim]")
        return
    
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
    
    step_num = 1
    try:
        while arg_prompt:
            prompt = arg_prompt
            arg_prompt = None  # Используем только один раз

            # Добавляем компактную памятку по инструментам ПЕРЕД началом хода (turn)
            tool_reminder_msg = sm.load_prompt(session_path, "tool_reminder",
                                               PROMPTS_DIR=os.path.join(session_path, 'prompts'))
            if tool_reminder_msg:
                messages.append({"role": "system", "content": tool_reminder_msg})

            while True:
                turn_start_idx = len(messages)
                messages.append({"role": "user", "content": prompt})

                try:
                    messages = ask_ollama_stealth(model, messages, session_path, step_num, num_ctx)
                except KeyboardInterrupt:
                    out("\n[bold red]Interrupted[/bold red]")
                    raise SystemExit(0)

                sm.save_messages_snapshot(session_path, messages, model=model, num_ctx=num_ctx)

                last_assistant_message = ""
                for m in reversed(messages[turn_start_idx:]):
                    if m.get("role") == "assistant" and m.get("content"):
                        last_assistant_message = m["content"]
                        break

                if not last_assistant_message:
                    break

                # Очистка от невалидных UTF-8 байтов
                last_assistant_message = last_assistant_message.encode('utf-8', errors='ignore').decode('utf-8')
                out(last_assistant_message)

                if not args.proofread:
                    step_num += 1
                    break

                # --- РЕЖИМ КОРРЕКТОРА (headless) ---
                out("\n[bold magenta]>>> ПРОВЕРКА КОРРЕКТОРОМ...[/bold magenta]")
                feedback, verdict_path = run_proofreader_turn(model, session_path, num_ctx, messages)
                out("\n[bold magenta]ЗАКЛЮЧЕНИЕ КОРРЕКТОРА:[/bold magenta]")
                out(feedback)
                out("\n" + "═" * term_width() + "\n")

                fb_low = feedback.lower()
                exit_keywords = ["замечаний нет", "все верно", "исправлено", "проверка завершена", "принято", "замечаний не обнаружено", "все в порядке"]
                if any(kw in fb_low for kw in exit_keywords):
                    out("[bold green]Корректор одобрил работу.[/bold green]")
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
    except SystemExit:
        raise

if __name__ == "__main__":
    main()
