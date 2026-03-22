import os
import json
import shlex
import subprocess
from typing import Optional, List


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def shell_exec(
    command: str,
    cwd: Optional[str] = None,
    timeout_sec: int = 120,
    max_bytes: int = 256_000,
) -> str:
    if not command or not str(command).strip():
        return "Ошибка: command пустой"

    try:
        argv: List[str] = shlex.split(command)
    except Exception as e:
        return f"Ошибка: не удалось распарсить команду: {str(e)}"

    try:
        run_cwd = _project_root() if not cwd else os.path.realpath(cwd)

        cp = subprocess.run(
            argv,
            cwd=run_cwd,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_sec)),
        )
        out = (cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")
        data = out.encode("utf-8", errors="ignore")
        if len(data) > max_bytes:
            out = data[:max_bytes].decode("utf-8", errors="ignore") + "\n...[TRUNCATED_BY_MAX_BYTES]"

        res = {
            "command": command,
            "cwd": run_cwd,
            "returncode": cp.returncode,
            "output": out.strip() if out.strip() else "(no output)",
        }
        return json.dumps(res, ensure_ascii=False, indent=2)
    except FileNotFoundError:
        return "Ошибка: команда не найдена"
    except subprocess.TimeoutExpired:
        return "Ошибка: timeout"
    except Exception as e:
        return f"Ошибка shell_exec: {str(e)}"
