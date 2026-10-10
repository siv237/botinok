import os
import sys
import time
import json
import shutil
import signal
import warnings
import requests
import argparse
import re
from datetime import datetime

# Шум TLS: самоподписанные сертификаты (VerifySSL=false в мастере) засоряют
# консоль варнингами urllib3 на каждый запрос. Пользователь уже согласился их
# игнорировать — молчим. В BOTINOK_DEBUG варнинги остаются полезными.
if not os.environ.get("BOTINOK_DEBUG"):
    try:
        from urllib3.exceptions import InsecureRequestWarning
        warnings.filterwarnings("ignore", category=InsecureRequestWarning)
    except Exception:
        pass

# --- Truecolor: терминалы, которые его поддерживают, но не объявляют --------
# rich/Textual включают 24-битный цвет только когда видят COLORTERM=truecolor,
# а ssh COLORTERM не пробрасывает. В итоге картинки (chafa отдаёт truecolor)
# кванризуются в 256-палитру и цвета «уезжают». Если терминал не plain
# console — объявляем truecolor сами. BOTINOK_TRUECOLOR=0 отключает, =1 forcит.
def _ensure_truecolor_env() -> None:
    override = os.environ.get("BOTINOK_TRUECOLOR", "").strip().lower()
    if override in ("0", "off", "no"):
        return
    if override in ("1", "on", "yes", "truecolor"):
        os.environ["COLORTERM"] = "truecolor"
        return
    if os.environ.get("COLORTERM", "").strip().lower() in ("truecolor", "24bit"):
        return
    term = os.environ.get("TERM", "").strip().lower()
    if term in ("", "dumb", "linux") or term.startswith("screen"):
        return
    try:
        if not sys.stdout.isatty():
            return
    except Exception:
        return
    os.environ["COLORTERM"] = "truecolor"


_ensure_truecolor_env()

from core.cli_io import out, term_width
from core.textual_prompts import textual_confirm
from core.session_manager import SessionManager
from core.tool_manager import ToolManager, requires_dangerous
from core.openai_compat import is_openai_backend, chat_stream_request
from core.api_key_gate import (is_auth_error, key_entry_url, save_api_key,
                               prompt_key_console)
from core.textual_history_viewer import view_history
from core.textual_integration import ask_ollama_textual

import subprocess
import shutil

def _git_version_info(script_dir: str):
    """Версия из git (date, hash) или None, если это не git-репозиторий."""
    try:
        git_check = subprocess.run(
            ['git', '--version'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        if git_check.returncode != 0:
            return None
        inside = subprocess.run(
            ['git', 'rev-parse', '--is-inside-work-tree'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        date_result = subprocess.run(
            ['git', 'log', '-1', '--format=%cd', '--date=format:%d.%m.%Y'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        commit_date = date_result.stdout.strip() if date_result.returncode == 0 else ""
        hash_result = subprocess.run(
            ['git', 'log', '-1', '--format=%h'],
            capture_output=True, text=True, cwd=script_dir, timeout=5
        )
        commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else ""
        if commit_date and commit_hash:
            return commit_date, commit_hash[:4]
    except Exception:
        return None
    return None


def _read_version_file(script_dir: str):
    """Fallback: версия из файла `.version` (для не-git установок)."""
    version_file = os.path.join(script_dir, ".version")
    try:
        if os.path.exists(version_file):
            with open(version_file, "r") as f:
                version = f.read().strip()
            parts = version.split(" | ")
            if len(parts) >= 3:
                return parts[1], parts[2]
    except Exception:
        pass
    return None


def _write_version_file(script_dir: str) -> None:
    """Обновить `.version` по текущему git-коммиту (после обновления)."""
    info = _git_version_info(script_dir)
    if not info:
        return
    try:
        with open(os.path.join(script_dir, ".version"), "w", encoding="utf-8") as f:
            f.write(f"0.4 | {info[0]} | {info[1]}\n")
    except Exception:
        pass


def _get_version_info(script_dir: str = None):
    """Версия: git — источник истины, `.version` — только fallback.

    Раньше приоритет был у `.version`, но `git pull` его не обновляет — баннер
    навсегда застревал на версии момента установки (напр. `10.06.2026 | cd57`).
    """
    script_dir = script_dir or os.path.dirname(os.path.abspath(__file__))

    info = _git_version_info(script_dir)
    if info:
        return info

    info = _read_version_file(script_dir)
    if info:
        return info
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



def _refresh_launcher(script_dir: str) -> str:
    """Пересоздать лаунчер в BIN_DIR: старые копии не знают про BOTINOK_LAUNCH_DIR."""
    import shutil
    launcher = shutil.which("botinok")
    if not launcher or not os.path.isfile(launcher):
        return ""
    try:
        with open(launcher, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if "BOTINOK_LAUNCH_DIR" in content:
            return "Лаунчер актуален."
        new_content = content.replace(
            'cd "$BOTINOK_HOME"',
            'export BOTINOK_LAUNCH_DIR="$PWD"\ncd "$BOTINOK_HOME"',
            1,
        )
        if new_content == content:
            return "Не распознан формат лаунчера — прогони вручную: sudo bash install.sh"
        with open(launcher, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.chmod(launcher, 0o755)
        return f"Лаунчер обновлён: {launcher}"
    except PermissionError:
        return "Нет прав на обновление лаунчера — запусти `botinok --update` через sudo."
    except Exception as e:
        return f"Не удалось обновить лаунчер: {e}"


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

        # Обновляем .version, иначе баннер останется на версии установки.
        _write_version_file(script_dir)
        
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


def _clip(s, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


_LIGHT_BG: "bool | None" = None
_LIGHT_BG_QUERIED = False


def _light_background() -> "bool | None":
    """Светлый ли фон у терминала (OSC 11). None — терминал не ответил.

    Один запрос на процесс, результат кэшируется. Нужен, чтобы подсветка кода
    подбиралась под реальную палитру, а не перекрывала её тёмной темой.
    """
    global _LIGHT_BG, _LIGHT_BG_QUERIED
    if _LIGHT_BG_QUERIED:
        return _LIGHT_BG
    _LIGHT_BG_QUERIED = True
    try:
        if not (sys.stdout.isatty() and sys.stdin.isatty()):
            return _LIGHT_BG
        import select
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            sys.stdout.write("\x1b]11;?\x1b\\")
            sys.stdout.flush()
            buf = b""
            end = time.time() + 0.15
            while time.time() < end:
                r, _, _ = select.select([fd], [], [], max(0.0, end - time.time()))
                if not r:
                    break
                buf += os.read(fd, 64)
                if b"\x1b\\" in buf or b"\x07" in buf:
                    break
            m = re.search(rb"11;rgb:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})", buf)
            if m:
                comps = [int(x[:4], 16) / 65535 for x in m.groups()]
                _LIGHT_BG = (0.2126 * comps[0] + 0.7152 * comps[1] + 0.0722 * comps[2]) > 0.5
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        pass
    return _LIGHT_BG


def _fmt_dangerous_detail(name: str, args) -> str:
    """Диалог dangerous-спроса без JSON-синтаксиса: одна понятная строка."""
    if isinstance(args, dict):
        action = str(args.get("action") or "")
        if name == "shell_exec" and (not action or action == "run") and args.get("command"):
            return f"Команда: {_clip(args['command'], 200)}"
    line = _fmt_tool_event(name, args) or name
    if isinstance(args, dict):
        skip = {"action", "session_id", "command", "path", "directory",
                "pattern", "query", "url", "name"}
        extra = [f"{k}={_clip(v, 40)}" for k, v in args.items()
                 if k not in skip and v not in (None, "", [], {})]
        if extra:
            line += " · " + " ".join(extra)
    return line


_INPUT_PROMPT_RE = re.compile(
    r"(password|пароль|passphrase|pin|token)\s*:|\[sudo\].*password|login:|username:|имя пользователя",
    re.IGNORECASE,
)
_ANY_PROMPT_RE = re.compile(
    r"(\(y/(n|es|da|да)\)|continue\?|proceed\?|продолжить\?|yes/no)",
    re.IGNORECASE,
)


def _parse_shell_result(result):
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _looks_like_input_prompt(output: str):
    """(строка-промпт, секретный ли ввод) если вывод заканчивается запросом ввода."""
    lines = [l for l in (output or "").splitlines() if l.strip()]
    if not lines:
        return None, False
    last = lines[-1]
    if _INPUT_PROMPT_RE.search(last):
        return last, True
    if _ANY_PROMPT_RE.search(last):
        return last, False
    return None, False


def _shell_output_for_console(result) -> str:
    """Хвост вывода shell_exec для показа в консоль — то же, что видит агент."""
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    text = str(data.get("output_tail") or data.get("output") or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    shown = lines[-15:]
    body = "\n".join(shown)
    if len(body) > 2000:
        body = body[-2000:]
    if len(lines) > len(shown):
        body = f"… ({len(lines) - len(shown)} строк выше)\n" + body
    return body


def _fmt_tool_event(name: str, args) -> str:
    """Человекочитаемая строка о вызове инструмента для консольного прогресса.

    Пустая строка — событие служебное, показывать нечего.
    """
    if not isinstance(args, dict):
        return name
    action = str(args.get("action") or "")
    sid = str(args.get("session_id") or "")
    if name == "shell_exec":
        cmd = str(args.get("command") or "")
        if (not action or action == "run") and cmd:
            return f"shell: $ {_clip(cmd, 110)}"
        if action == "read":
            tail = args.get("tail_lines")
            return f"shell: вывод {sid}" + (f" (хвост {tail})" if tail else "")
        if action == "wait":
            return f"shell: ожидание {sid}"
        if action == "search":
            return f"shell: поиск «{_clip(args.get('pattern', ''), 40)}» в {sid}"
        if action in ("send", "send_key"):
            return f"shell: ввод в {sid}"
        if action == "kill":
            return f"shell: завершение {sid}"
        return f"shell: {action or 'вызов'}"
    if name == "file_system":
        path = _clip(args.get("path") or args.get("directory") or "", 90)
        if action == "read":
            parts = []
            if args.get("offset"):
                parts.append(f"с {args['offset']}")
            if args.get("limit"):
                parts.append(f"{args['limit']} строк")
            return f"чтение: {path}" + (f" ({', '.join(parts)})" if parts else "")
        if action == "grep":
            return f"grep: «{_clip(args.get('pattern', ''), 40)}» в {path}"
        if action == "list":
            return f"лист: {path}"
        if action == "search":
            return f"поиск файлов: «{_clip(args.get('pattern', ''), 40)}» в {path}"
        if action == "inspect":
            return ("инспекция: " + str(args.get("command", "")) + " " + path).strip()
        return (f"{action}: {path}" if action else f"file_system: {path}").strip() or "file_system"
    if name == "code_editor":
        return f"правка файла: {_clip(args.get('path', ''), 90)}" + (f" ({action})" if action else "")
    if name in ("web", "curl", "web_search", "open_url", "web_extract"):
        q = args.get("query") or args.get("url") or args.get("output_path") or ""
        q = _clip(q, 90)
        return f"веб ({action or 'get'}): {q}" if q else f"веб ({action or 'get'})"
    if name == "journal":
        bits = [str(args[k]) for k in ("unit", "since", "until", "grep") if args.get(k)]
        joined = " ".join(bits)
        return f"journal{f' ({action})' if action else ''}" + (f": {joined}" if joined else "")
    if name == "github":
        g = _clip(args.get("repo") or args.get("query") or "", 60)
        return f"github ({action}): {g}" if g else f"github ({action})"
    if name == "skills":
        sk = _clip(args.get("name") or args.get("query") or args.get("skill_id") or "", 50)
        return f"skills ({action}): {sk}" if sk else f"skills ({action})"
    if name == "experience":
        return f"опыт ({action})" if action else "опыт"
    if name == "sign_step":
        return ""
    if name == "session_memory":
        return f"память сессии ({action})" if action else "память сессии"
    for k in ("path", "url", "query", "command", "pattern", "name"):
        if args.get(k):
            return f"{name} ({action}): {_clip(args[k], 80)}" if action else f"{name}: {_clip(args[k], 80)}"
    return f"{name} ({action})" if action else name


def _attach_shell_console(session) -> bool:
    """Интерактивный перехват PTY: пользователь общается с командой напрямую,
    как будто запустил её сам. Живой вывод, любой ввод (пароли, меню, y/n,
    Ctrl+C). Ctrl+] — отцепиться, команда продолжит в фоне.
    Возвращает True, если пользователь отцепился (команда ещё живёт)."""
    import select
    import termios
    import threading
    import tty
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        old = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        return False

    def _on_chunk(chunk: bytes) -> None:
        try:
            os.write(1, chunk)
        except OSError:
            pass

    sys.stderr.write("\n[botinok] ⌨ Интерактив: команда ваша (Ctrl+] — отцепиться, она продолжит в фоне)\n")
    sys.stderr.flush()
    session.subscribe(_on_chunk)

    # Heartbeat: молчаливые долгие команды (du, find) не должны выглядеть зависанием.
    stop_hb = threading.Event()

    def _heartbeat() -> None:
        t0 = time.time()
        while not stop_hb.wait(8.0):
            if session.is_running():
                try:
                    os.write(2, f"\r\x1b[K[botinok] ⏳ выполняется {int(time.time() - t0)} с · Ctrl+] — отцепиться".encode())
                except OSError:
                    return

    hb = threading.Thread(target=_heartbeat, name="shell-hb", daemon=True)
    hb.start()

    detached = False
    fd = sys.stdin.fileno()
    try:
        tty.setraw(fd)
        while True:
            try:
                r, _, _ = select.select([fd], [], [], 0.25)
            except (OSError, ValueError):
                break
            if r:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                cut = data.find(b"\x1d")  # Ctrl+]
                if cut >= 0:
                    if data[:cut]:
                        session.send_bytes(data[:cut])
                    detached = True
                    break
                session.send_bytes(data)
            if not session.is_running():
                time.sleep(0.3)  # дать ридеру долить хвост в буферы
                break
    finally:
        stop_hb.set()
        session.unsubscribe(_on_chunk)
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass
        sys.stderr.write("\r\x1b[K\n")
        sys.stderr.flush()
    return detached and session.is_running()


def ask_ollama_stealth(model, messages, session_path, step_num, num_ctx=8192, read_only_mode=False, progress=None, confirm_dangerous=None, on_shell_input=None, attach_shell=None, on_shell_started=None):
    printed_outputs = set()  # не печатать один и тот же хвост shell-вывода дважды
    asked_inputs = set()     # на один и тот же промпт не спрашивать дважды
    detached_sessions = set()  # пользователь отцепился — обратно не цепляем
    tapped_sids = set()        # вывод этих сессий уже льётся в общий поток
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
        key_gate_retried = False
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

                # Проблема с API-ключом: просим ввести (если терминал
                # интерактивный), сохраняем и повторяем ход один раз.
                if is_auth_error(response.status_code, str(error_msg)):
                    key = None
                    if not key_gate_retried:
                        key_gate_retried = True
                        key = prompt_key_console(key_entry_url(sm),
                                                 str(error_msg)[:160])
                    if key:
                        try:
                            save_api_key(sm, key)
                            print("[botinok] API-ключ сохранён.", file=sys.stderr)
                            continue
                        except Exception as e:
                            print(f"[botinok] Не удалось сохранить API-ключ: {e}",
                                  file=sys.stderr)
                    else:
                        url = key_entry_url(sm)
                        print("[botinok] LLM-сервер отклонил API-ключ. Пропишите "
                              "ApiKey в ~/.config/botinok/config.cfg"
                              + (f" (получить ключ: {url})" if url else ""),
                              file=sys.stderr)
                    return messages

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

                if progress:
                    line = _fmt_tool_event(func_name, func_args)
                    if line:
                        progress(line)

                result = None
                if not tm.dangerous_mode and requires_dangerous(func_name, func_args, session_path):
                    if confirm_dangerous:
                        approved, reason = confirm_dangerous(func_name, func_args)
                    else:
                        approved, reason = False, "нет интерактивного терминала для подтверждения"
                    if approved:
                        tm.dangerous_mode = True
                        os.environ["BOTINOK_DANGEROUS"] = "1"
                    else:
                        result = f"ОТКАЗАНО ПОЛЬЗОВАТЕЛЕМ. Причина: {reason or 'отказ без пояснения'}"
                        sm.log_tool_call(session_path, func_name, func_args, result, status="denied")
                if result is None:
                    sm.log_tool_call(session_path, func_name, func_args, "STARTED", status="running")
                    # Долгое ожидание молчаливой команды не должно выглядеть зависанием.
                    hb_stop = None
                    if progress and func_name == "shell_exec" and isinstance(func_args, dict) and func_args.get("action") == "wait":
                        import threading
                        hb_stop = threading.Event()

                        def _wait_hb(_ev=hb_stop):
                            t0 = time.time()
                            while not _ev.wait(8.0):
                                progress(f"ожидание завершения shell-сессии · {int(time.time() - t0)} с")

                        threading.Thread(target=_wait_hb, daemon=True).start()
                    try:
                        result = tm.call_tool(func_name, func_args, session_path=session_path)
                    except Exception as e:
                        result = f"Error calling tool: {str(e)}"
                    finally:
                        if hb_stop is not None:
                            hb_stop.set()
                    if func_name == "shell_exec":
                        data = _parse_shell_result(result) or {}
                        sid = str(data.get("session_id") or "")
                        # Вывод интерактивной команды льётся в общий поток пассивно,
                        # без перехвата и клавиш.
                        if sid and on_shell_started and data.get("mode") == "interactive" and sid not in tapped_sids:
                            tapped_sids.add(sid)
                            on_shell_started(sid)
                        outp = _shell_output_for_console(result)
                        prompt_line, secret = _looks_like_input_prompt(outp)
                        if sid and prompt_line:
                            if attach_shell and sid not in detached_sessions:
                                # Программа задала вопрос (пароль, y/n) — терминал
                                # на время принадлежит ей; Ctrl+] возвращает его обратно.
                                if attach_shell(sid):
                                    detached_sessions.add(sid)
                                result = tm.call_tool(
                                    "shell_exec",
                                    {"action": "status", "session_id": sid, "tail_lines": 40},
                                    session_path=session_path,
                                )
                                outp = _shell_output_for_console(result)
                            elif on_shell_input and (sid, prompt_line) not in asked_inputs:
                                # Перехват недоступен — строчный ввод через send.
                                asked_inputs.add((sid, prompt_line))
                                text = on_shell_input(prompt_line, secret)
                                if text is not None:
                                    tm.call_tool(
                                        "shell_exec",
                                        {"action": "send", "session_id": sid, "input": text},
                                        session_path=session_path,
                                    )
                                    sm.log_tool_call(session_path, "shell_exec",
                                                     {"action": "send", "session_id": sid},
                                                     "<скрыто>" if secret else text, status="user_input")
                                    time.sleep(0.5)
                                    result = tm.call_tool(
                                        "shell_exec",
                                        {"action": "read", "session_id": sid, "tail_lines": 15},
                                        session_path=session_path,
                                    )
                                    outp = _shell_output_for_console(result)
                        if outp and sid not in tapped_sids:
                            if progress and outp not in printed_outputs:
                                printed_outputs.add(outp)
                                progress(outp)

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

            # Фоновые веб-задачи: инкрементные уведомления + напоминание о висящих.
            try:
                from tools import web_jobs as _wj
                _wj_note = _wj.format_notifications()
            except Exception:
                _wj_note = ""
            if _wj_note:
                messages.append({"role": "user", "content": _wj_note})
                sm.update_context(session_path, "user", _wj_note)

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

    # Пустые сессии от прошлых запусков («начал и вышел») прибираем молча;
    # свежие (<10 мин) не трогаем — в них может жить другой экземпляр.
    sm.prune_stale_empty_sessions()

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

    def preview_and_sign(path: str):
        # (первый запрос, последняя подпись шага) — экран покажет их вместе.
        return (sm.load_first_user_prompt(path), sm.load_last_sign_note(path))

    from core.session_picker import pick_session
    try:
        action, chosen_path = pick_session(
            session_data, latest_name, preview_loader=preview_and_sign
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
    # Лаунчер делает cd в папку установки — возвращаем реальную папку запуска:
    # cwd, относительные пути инструментов («.») и shell по умолчанию должны
    # указывать на проект пользователя, а не на /opt/botinok.
    launch_dir = os.environ.get("BOTINOK_LAUNCH_DIR")
    if launch_dir and os.path.isdir(launch_dir):
        os.chdir(launch_dir)

    parser = argparse.ArgumentParser(description="BOTINOK AGENT - Interactive AI Assistant")
    
    sm = SessionManager()
    
    # Уведомление о используемом конфиге — в stderr, чтобы stdout оставался чистым
    if sm.config_source == "personal":
        print(f"Using personal config: {sm.config_path}", file=sys.stderr)
    
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
    parser.add_argument("--once", action="store_true", help="Один запрос: ответил — вышел, без вопроса о продолжении (для скриптов)")
    parser.add_argument("--dangerous", action="store_true", help="Разрешить опасные инструменты (редактирование файлов и выполнение команд) только в этой сессии")
    parser.add_argument("--proofread", action="store_true", help="Включить режим корректора (цикл: Исполнитель -> Корректор)")
    parser.add_argument("--debug", action="store_true", help="Включить отладочный вывод")
    parser.add_argument("--update", action="store_true", help="Проверить и установить обновления из git")
    parser.add_argument("--ensure-deps", action="store_true", help="Проверить и установить системные зависимости (chafa, ffmpeg, aria2 и др.)")
    parser.add_argument("--view-history", metavar="SESSION_PATH", help="Просмотр истории сессии через Textual (с прокруткой)")
    parser.add_argument("--version", action="version", version=f"BOTINOK {_BOTINOK_VERSION}", help="Показать версию и дату коммита")

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

        # Лаунчер чиним тоже ВСЕГДА: старые копии без BOTINOK_LAUNCH_DIR
        # ломают рабочую папку даже при актуальном коде.
        launcher_note = _refresh_launcher(os.path.dirname(os.path.abspath(__file__)))
        if launcher_note:
            out(launcher_note)

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

    # Одиночный запрос (`botinok "..."`, --stealth или pipe) обслуживается
    # headless-циклом ниже: без TUI, без выбора сессии, все инструменты
    # без подтверждений, временная сессия удаляется после ответа.
    arg_prompt = args.prompt if args.prompt else args.prompt_pos
    if not args.stealth and not arg_prompt and sys.stdin.isatty():
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
                                               CWD=os.environ.get("BOTINOK_LAUNCH_DIR") or os.getcwd(),
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

        try:
            ask_ollama_textual(
                model=args.model,
                messages=messages,
                session_path=session_path,
                num_ctx=args.ctx,
                dangerous_mode=args.dangerous,
                version=_BOTINOK_VERSION,
                proofread=args.proofread,
                proofreader_fn=run_proofreader_turn,
                resume_session=bool(resume_last_answer),
            )
        finally:
            # Страховка: если TUI завершился аварийно и не погасил mouse-tracking,
            # клики в шелле печатают escape-мусор. Последовательности idempotent.
            sys.stdout.write("\x1b[?1002l\x1b[?1003l\x1b[?1000l\x1b[?1006l\x1b[?1015l")
            sys.stdout.flush()
            # Пользователь вышел, так и не начав диалог, — сессия не нужна.
            sm.prune_empty_session(session_path)
        return

    # Headless-режим: одиночный запрос без интерактива.
    model = args.model
    num_ctx = args.ctx
    # Dangerous mode по умолчанию выключен; при потребности в опасном действии
    # спросим в консоли по ходу. В pipe спросить некого — опасное отсекается.
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

    # Временная сессия одиночного запроса: живёт до конца работы, затем удаляется.
    session_path = sm.create_session("oneshot")

    def _progress(line: str) -> None:
        print(f"[botinok] {line}", file=sys.stderr, flush=True)

    def _print_answer(text: str) -> None:
        """Ответ в живой терминал — через Rich Markdown (таблицы, заголовки,
        списки). Фонов нет нигде:ANSI-темы кода прозрачны, inline-коду фон
        выключен — текст рисуется палитрой терминала и не спорит с любым фоном.
        Светлая/тёмная тема кода — по реальному фону терминала (OSC 11).
        В pipe и при --stealth — чистый текст без разметки."""
        if progress_fn:
            from rich.console import Console
            from rich.markdown import Markdown
            from rich.theme import Theme
            from rich.style import Style
            theme = "ansi_light" if _light_background() else "ansi_dark"
            flat = Theme({
                "markdown.code": Style(bold=True, color="cyan"),
                "markdown.code_block": Style(color="cyan"),
            })
            Console(highlight=False, theme=flat).print(Markdown(text, code_theme=theme))
        else:
            out(text)

    # Прогресс — только живому терминалу; в pipe и при --stealth stdout/stderr чистые.
    # События инструментов — приглушённой строкой с маркером, не сырым JSON.
    _err_console = None
    if sys.stderr.isatty() and not args.stealth:
        from rich.console import Console
        _err_console = Console(stderr=True, highlight=False)

    def _tool_progress(line: str) -> None:
        if _err_console is not None:
            from rich.markup import escape
            if "\n" in line:
                body = "\n".join(f"│ {l}" for l in line.splitlines())
                _err_console.print(f"[dim]{escape(body)}[/dim]")
            else:
                _err_console.print(f"[dim]⚙ {escape(line)}[/dim]")
        else:
            print(f"[botinok] {line}", file=sys.stderr, flush=True)

    progress_fn = _tool_progress if (sys.stderr.isatty() and not args.stealth) else None
    _tapped_live = set()  # shell-сессии, чей вывод льётся в общий поток
    if progress_fn:
        # Фон терминала спрашиваем на старте, пока пользователь не печатает.
        _light_background()
        if args.once:
            _progress(f"сессия временная: {session_path}")
        else:
            _progress(f"сессия временная: {session_path} "
                      "(Enter/Esc после ответа — завершить, текст — продолжение)")

    def _confirm_dangerous(name: str, tool_args) -> tuple[bool, str]:
        """Запрос dangerous mode посреди одиночного запроса (только живой tty stdin)."""
        if not sys.stdin.isatty():
            return False, "нет интерактивного терминала (pipe/stealth), опасные действия запрещены"
        detail = _fmt_dangerous_detail(name, tool_args)
        if _err_console is not None:
            from rich.markup import escape
            _err_console.print(f"\n[yellow]⚠ Опасное действие[/yellow]")
            _err_console.print(f"  {escape(detail)}")
            _err_console.print("[bold]Выполнить?[/bold] [green]y[/green] — да "
                               "(dangerous mode включится и для следующих команд), "
                               "иначе — отказ (можно указать причину): ", end="")
        else:
            print(f"\n[botinok] ⚠ Опасное действие: {detail}", file=sys.stderr, flush=True)
            print("[botinok] Выполнить? y — да (dangerous mode включится и для следующих "
                  "команд), иначе — отказ (можно указать причину): ", end="", file=sys.stderr, flush=True)
        try:
            ans = input().strip()
        except EOFError:
            print("", file=sys.stderr)
            return False, "ответ не получен"
        if ans.lower() in ("y", "yes", "д", "да"):
            return True, ""
        return False, ans

    def _on_shell_input(prompt_line: str, secret: bool):
        """Команда ждёт ввод — спросить у человека; None — пропустить (модель сама)."""
        if not sys.stdin.isatty():
            return None
        if _err_console is not None:
            from rich.markup import escape
            _err_console.print(f"\n[cyan]⌨ Команда ждёт ввод[/cyan] [dim]({escape(prompt_line)})[/dim]")
        else:
            print(f"\n[botinok] ⌨ Команда ждёт ввод: {prompt_line}", file=sys.stderr, flush=True)
        try:
            if secret:
                import getpass
                text = getpass.getpass("[botinok] Введите (символы не видны, Enter — отправить): ")
            else:
                sys.stderr.write("[botinok] Введите (пустая строка — пропустить, решит модель): ")
                sys.stderr.flush()
                text = input()
        except EOFError:
            print("", file=sys.stderr)
            return None
        return text if text.strip() else None

    def _attach_shell(session_id: str) -> bool:
        from core.shell_session import ShellSessionRegistry
        s = ShellSessionRegistry.instance().get(session_id)
        if s is None:
            return False
        # На время перехвата глушим пассивный тап — вывод пишет сам перехват.
        _tapped_live.discard(session_id)
        try:
            return _attach_shell_console(s)
        finally:
            _tapped_live.add(session_id)

    def _on_shell_started(session_id: str) -> None:
        """Пассивный тап: сырой вывод команды льётся в терминал (stderr) без
        перехвата и клавиш. Быстрый вывод «догоняется» при подписке. Перехват
        (raw-режим) включается только когда программа реально ждёт ввод."""
        from core.shell_session import ShellSessionRegistry
        s = ShellSessionRegistry.instance().get(session_id)
        if s is None or session_id in _tapped_live:
            return
        _tapped_live.add(session_id)

        def _tap(chunk: bytes) -> None:
            if session_id not in _tapped_live:
                return
            try:
                os.write(2, chunk)
            except OSError:
                pass

        s.subscribe_flush(_tap)

    def _ask_next_question():
        """Продолжение сессии после ответа: пустая строка (Enter), Esc, Ctrl+C —
        завершить; любой непустой текст — следующий вопрос."""
        if _err_console is not None:
            _err_console.print("\n[bold]Продолжаем?[/bold] [dim]Enter / Esc — завершить сессию "
                               "(она удалится), любой текст — следующий вопрос[/dim]")
        sys.stderr.write("[botinok] ❯ ")
        sys.stderr.flush()
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print("", file=sys.stderr, flush=True)
            return None
        line = line.strip()
        # Esc в терминале приходит как escape-последовательность (\x1b, \x1bOP, …)
        if not line or (line.startswith("\x1b") and len(line) <= 4):
            return None
        return line
    
    # Подготовка начальных сообщений из промптов
    now = datetime.now().astimezone()
    steps_subdir = sm.config.get('Storage', 'StepsSubDir', fallback='steps')
    
    system_time_msg = sm.load_prompt(session_path, "system_time", 
                                     TIMESTAMP=now.isoformat(), 
                                     TZNAME=now.tzname() or "unknown")
    
    session_location_msg = sm.load_prompt(session_path, "session_location",
                                          SESSION_PATH=session_path,
                                          CWD=os.environ.get("BOTINOK_LAUNCH_DIR") or os.getcwd(),
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
    if args.dangerous:
        dangerous_details = ("Опасные инструменты (code_editor, shell_exec) разрешены и выполняются "
                             "без подтверждения — режим одиночного запроса.")
    else:
        dangerous_details = ("Опасные инструменты (code_editor, shell_exec) выключены. Если задача требует "
                             "опасного действия (shell-команда, запись вне папки сессии), выполняй его — "
                             "пользователь подтвердит переключение в dangerous mode или откажет с причиной.")
    dangerous_mode_msg = sm.load_prompt(session_path, "dangerous_mode",
                                        DANGEROUS_STATUS=dangerous_status,
                                        DANGEROUS_DETAILS=dangerous_details)

    # Проверка сломанных инструментов
    tm = ToolManager()
    broken_tools_info = tm.get_broken_tools_info() or ""
    broken_tools_msg = sm.load_prompt(session_path, "broken_tools", BROKEN_TOOLS_INFO=broken_tools_info) if broken_tools_info else ""

    messages = [
        {"role": "system", "content": system_time_msg},
        {"role": "system", "content": session_location_msg},
        {"role": "system", "content": session_files_msg},
        {"role": "system", "content": tool_policy_msg},
        {"role": "system", "content": dangerous_mode_msg},
    ]

    if broken_tools_msg:
        messages.append({"role": "system", "content": broken_tools_msg})
    
    step_num = 1
    prompt = arg_prompt

    def _kill_all_shells() -> None:
        """Фоновые shell-сессии не должны переживать ботинка и «драконить» диск."""
        try:
            from core.shell_session import ShellSessionRegistry
            ShellSessionRegistry.instance().close_all()
        except Exception:
            pass

    # Ctrl+C (SIGINT) штатно разворачивается в KeyboardInterrupt и доходит до
    # finally ниже. SIGTERM/SIGHUP (закрытие терминала, kill, timeout) Python
    # завершают молча, без atexit — ставим свои обработчики.
    def _on_term(signum, frame):
        _kill_all_shells()
        raise SystemExit(128 + signum)

    for _sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(_sig, _on_term)
        except Exception:
            pass

    try:
        while prompt:
            # Добавляем компактную памятку по инструментам ПЕРЕД началом хода (turn)
            tool_reminder_msg = sm.load_prompt(session_path, "tool_reminder",
                                               PROMPTS_DIR=os.path.join(session_path, 'prompts'))
            if tool_reminder_msg:
                messages.append({"role": "system", "content": tool_reminder_msg})

            while True:
                turn_start_idx = len(messages)
                messages.append({"role": "user", "content": prompt})

                try:
                    messages = ask_ollama_stealth(
                        model, messages, session_path, step_num, num_ctx,
                        progress=progress_fn,
                        confirm_dangerous=None if args.stealth else _confirm_dangerous,
                        on_shell_input=None if args.stealth else _on_shell_input,
                        attach_shell=None if args.stealth else _attach_shell,
                        on_shell_started=_on_shell_started if progress_fn else None,
                    )
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
                _print_answer(last_assistant_message)

                if not args.proofread:
                    step_num += 1
                    break

                # --- РЕЖИМ КОРРЕКТОРА (headless) ---
                out("\n[bold magenta]>>> ПРОВЕРКА КОРРЕКТОРОМ...[/bold magenta]")
                feedback, verdict_path = run_proofreader_turn(model, session_path, num_ctx, messages)
                out("\n[bold magenta]ЗАКЛЮЧЕНИЕ КОРРЕКТОРА:[/bold magenta]")
                _print_answer(feedback)
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

            # Ход завершён. В живом терминале спрашиваем продолжение:
            # Enter — завершить (сессия удалится), текст — новый вопрос в этой же сессии.
            if args.once or args.stealth or not sys.stdin.isatty():
                break
            prompt = _ask_next_question()
            if prompt is None:
                break
    except SystemExit:
        raise
    finally:
        # Всё, что могло остаться в фоне (du, ждущие ввода процессы), — умереть
        # вместе с ботинком. Затем — удаление временной сессии.
        _kill_all_shells()
        shutil.rmtree(session_path, ignore_errors=True)
        if progress_fn:
            _progress(f"сессия завершена и удалена: {session_path}")

if __name__ == "__main__":
    main()
