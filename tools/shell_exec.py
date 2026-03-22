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
    interactive: bool = True,
) -> str:
    if not command or not str(command).strip():
        return "Ошибка: command пустой"

    try:
        run_cwd = _project_root() if not cwd else os.path.realpath(cwd)
        
        if interactive:
            # В интерактивном режиме мы не перехватываем stdout/stderr в трубы,
            # чтобы пользователь мог взаимодействовать (вводить пароли и т.д.).
            # Но нам нужно вернуть результат агенту. 
            # Используем временный файл для захвата вывода через 'script' (если доступен) или просто запускаем.
            print(f"\n--- Запуск интерактивной команды (CWD: {run_cwd}) ---")
            
            # Попробуем использовать 'script' для записи сессии, если это Linux
            import platform
            log_file = f"/tmp/botinok_shell_{os.getpid()}.log"
            if platform.system() == "Linux":
                # script -e -c "команда" -q /tmp/log
                # -e: возвращать код завершения команды
                # -c: выполнить команду
                # -q: quiet (не писать старт/стоп в лог)
                cmd_to_run = ["script", "-e", "-q", "-c", command, log_file]
            else:
                cmd_to_run = shlex.split(command)

            cp = subprocess.run(
                cmd_to_run,
                cwd=run_cwd,
                stdin=None, # Наследует от родителя
                stdout=None, 
                stderr=None,
            )
            
            output = ""
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        output = f.read()
                    os.remove(log_file)
                except Exception:
                    output = "(не удалось прочитать лог сессии)"
            
            res = {
                "command": command,
                "cwd": run_cwd,
                "returncode": cp.returncode,
                "output": output.strip() if output.strip() else "(interactive session ended)",
                "mode": "interactive"
            }
            return json.dumps(res, ensure_ascii=False, indent=2)

        # Неинтерактивный режим (старый вариант)
        argv = shlex.split(command)
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
            "mode": "batch"
        }
        return json.dumps(res, ensure_ascii=False, indent=2)
    except FileNotFoundError:
        return "Ошибка: команда не найдена"
    except subprocess.TimeoutExpired:
        return "Ошибка: timeout"
    except Exception as e:
        return f"Ошибка shell_exec: {str(e)}"
