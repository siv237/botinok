import os
import glob
import fnmatch
import re
import json
import hashlib
import platform
import subprocess
import shutil
import stat
import time
from datetime import datetime
from typing import List, Optional, Dict, Union, Tuple

def file_system_tool(
    action: str,
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
    content_query: Optional[str] = None,
    max_results: int = 50,
    offset: int = 0,
    limit: int = 1000,
    command: Optional[str] = None,
    depth: int = 3,
    sort: str = "name",
    reverse: bool = False,
    max_bytes: int = 256_000,
    pid: Optional[int] = None,
    unit: Optional[str] = None,
    since: Optional[str] = None,
    lines: int = 200,
    dest: Optional[str] = None,
    mode: Optional[str] = None,
    session_path: Optional[str] = None,
    dangerous_mode: bool = False,
) -> str:
    """
    Универсальный инструмент для работы с файловой системой.
    
    Actions:
    - list: Список файлов и директорий
    - search: Поиск файлов по имени/паттерну
    - grep: Поиск текста внутри файлов
    - read: Чтение содержимого файла с поддержкой пагинации
    - info: Получение метаданных о файле
    - inspect: Набор read-only команд для аналитики (fs/du/grep/log/sys/proc/service/journal)
    
    Dangerous actions (требуют dangerous_mode и подтверждения вне сессии):
    - delete: Удаление файла или директории
    - move: Перемещение/переименование файла или директории
    - copy: Копирование файла или директории
    - mkdir: Создание директории
    - chmod: Изменение прав доступа
    - symlink: Создание символической ссылки
    - touch: Создание пустого файла или обновление времени модификации
    """
    try:
        if action == "list":
            return _list_dir(path, sort=sort, reverse=reverse, max_results=max_results)
        elif action == "search":
            return _search_files(path, pattern, recursive, max_results)
        elif action == "grep":
            return _grep_files(path, pattern, content_query, recursive, max_results)
        elif action == "read":
            return _read_file(path, offset, limit, max_bytes=max_bytes)
        elif action == "info":
            return _file_info(path)
        elif action == "inspect":
            return _inspect(
                command=command,
                path=path,
                pattern=pattern,
                recursive=recursive,
                content_query=content_query,
                max_results=max_results,
                offset=offset,
                limit=limit,
                depth=depth,
                sort=sort,
                reverse=reverse,
                max_bytes=max_bytes,
                pid=pid,
                unit=unit,
                since=since,
                lines=lines,
            )
        elif action == "find":
            return _find_files(
                path=path,
                pattern=pattern,
                ftype=content_query or "any",
                min_size=max(0, offset) if offset > 0 else None,
                max_size=limit if limit < 1000 and limit > 0 else None,
                mtime_days=depth if depth > 0 and depth < 100 else None,
                max_depth=10,
                max_results=max_results,
            )
        elif action in ("delete", "move", "copy", "mkdir", "chmod", "symlink", "touch"):
            return _dangerous_action(
                action=action,
                path=path,
                dest=dest,
                mode=mode,
                session_path=session_path,
                dangerous_mode=dangerous_mode,
            )
        else:
            return f"Ошибка: Неизвестное действие '{action}'"
    except Exception as e:
        return f"Ошибка при выполнении {action}: {str(e)}"

def _list_dir(path: str, sort: str = "name", reverse: bool = False, max_results: int = 200) -> str:
    if not os.path.exists(path):
        return f"Путь не существует: {path}"

    entries = []
    for item in os.listdir(path):
        full_path = os.path.join(path, item)
        try:
            is_dir = os.path.isdir(full_path)
            size = os.path.getsize(full_path) if not is_dir else 0
            mtime = os.path.getmtime(full_path)
        except Exception:
            is_dir = False
            size = 0
            mtime = 0
        entries.append((item, full_path, is_dir, size, mtime))

    key_map = {
        "name": lambda e: e[0].lower(),
        "size": lambda e: e[3],
        "mtime": lambda e: e[4],
        "type": lambda e: (0 if e[2] else 1, e[0].lower()),
    }
    key_func = key_map.get(sort, key_map["name"])
    entries.sort(key=key_func, reverse=reverse)

    shown = entries[:max_results]
    out = []
    for item, full_path, is_dir, size, mtime in shown:
        tag = "[DIR]" if is_dir else "[FILE]"
        size_str = "-" if is_dir else str(size)
        mtime_str = datetime.fromtimestamp(mtime).isoformat() if mtime else "-"
        out.append(f"{tag} {item} (size={size_str}, mtime={mtime_str})")

    if not out:
        return "Директория пуста"
    if len(entries) > max_results:
        out.append(f"... и еще {len(entries) - max_results} элементов")
    return "\n".join(out)

def _search_files(path: str, pattern: str, recursive: bool, max_results: int) -> str:
    search_path = os.path.join(path, "**", pattern) if recursive else os.path.join(path, pattern)
    files = glob.glob(search_path, recursive=recursive)
    
    results = files[:max_results]
    output = [f"Найдено {len(files)} файлов (показано {len(results)}):"]
    output.extend(results)
    
    if len(files) > max_results:
        output.append(f"... и еще {len(files) - max_results} файлов")
    
    return "\n".join(output)

def _grep_files(path: str, pattern: str, query: str, recursive: bool, max_results: int) -> str:
    if not query:
        return "Ошибка: Параметр content_query обязателен для grep"
    
    search_path = os.path.join(path, "**", pattern) if recursive else os.path.join(path, pattern)
    files = [f for f in glob.glob(search_path, recursive=recursive) if os.path.isfile(f)]
    
    matches = []
    for file_path in files:
        if len(matches) >= max_results:
            break
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    if query.lower() in line.lower():
                        matches.append(f"{file_path}:{line_num}: {line.strip()}")
                        if len(matches) >= max_results:
                            break
        except Exception:
            continue
            
    return "\n".join(matches) if matches else "Совпадений не найдено"

def _read_file(path: str, offset: int, limit: int, max_bytes: int = 256_000) -> str:
    if not os.path.isfile(path):
        return f"Файл не найден: {path}"
    
    try:
        content, total_lines, end = _read_text_with_limits(path, offset=offset, limit=limit, max_bytes=max_bytes)
        header = f"--- Файл: {path} (строки {offset+1}-{end} из {total_lines}, max_bytes={max_bytes}) ---\n"
        return header + content
    except Exception as e:
        return f"Ошибка чтения файла: {str(e)}"

def _file_info(path: str) -> str:
    if not os.path.exists(path):
        return f"Путь не существует: {path}"
    
    stat = os.stat(path)
    import datetime
    
    info = {
        "Path": os.path.abspath(path),
        "Size": f"{stat.st_size} bytes",
        "Created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "Modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "Is Directory": os.path.isdir(path)
    }
    
    return "\n".join([f"{k}: {v}" for k, v in info.items()])


def _read_text_with_limits(file_path: str, offset: int, limit: int, max_bytes: int) -> Tuple[str, int, int]:
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 1
    if max_bytes <= 0:
        max_bytes = 1

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    total_lines = len(lines)
    end = min(offset + limit, total_lines)
    chunk = "".join(lines[offset:end])
    data = chunk.encode('utf-8', errors='ignore')
    if len(data) > max_bytes:
        trimmed = data[:max_bytes].decode('utf-8', errors='ignore')
        trimmed += "\n...[TRUNCATED_BY_MAX_BYTES]"
        return trimmed, total_lines, end
    return chunk, total_lines, end


def _sha256_file(path: str, max_bytes: int = 10_000_000) -> str:
    if not os.path.isfile(path):
        return f"Файл не найден: {path}"
    h = hashlib.sha256()
    total = 0
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                return f"Ошибка: файл слишком большой для hash (>{max_bytes} bytes)"
            h.update(chunk)
    return h.hexdigest()


def _walk_files(root: str, recursive: bool = True, max_results: int = 50) -> List[str]:
    out = []
    if not os.path.exists(root):
        return out
    if os.path.isfile(root):
        return [root]

    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                out.append(os.path.join(dirpath, fn))
                if len(out) >= max_results:
                    return out
    else:
        for fn in os.listdir(root):
            fp = os.path.join(root, fn)
            if os.path.isfile(fp):
                out.append(fp)
                if len(out) >= max_results:
                    return out
    return out


def _dir_total_size(path: str, max_files: int = 200_000) -> Dict[str, Union[str, int]]:
    if not os.path.exists(path):
        return {"error": f"Путь не существует: {path}"}
    if os.path.isfile(path):
        try:
            return {"path": os.path.abspath(path), "bytes": os.path.getsize(path), "files": 1}
        except Exception as e:
            return {"error": str(e)}

    total = 0
    files = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                total += os.path.getsize(fp)
                files += 1
            except Exception:
                continue
            if files >= max_files:
                return {"path": os.path.abspath(path), "bytes": total, "files": files, "truncated": True}
    return {"path": os.path.abspath(path), "bytes": total, "files": files, "truncated": False}


def _top_largest_files(path: str, recursive: bool, max_results: int) -> str:
    if not os.path.exists(path):
        return f"Путь не существует: {path}"
    files = []
    if os.path.isfile(path):
        files = [path]
    else:
        for dirpath, dirnames, filenames in os.walk(path):
            for fn in filenames:
                files.append(os.path.join(dirpath, fn))
            if not recursive:
                break

    items = []
    for fp in files:
        try:
            items.append((os.path.getsize(fp), fp))
        except Exception:
            continue
    items.sort(key=lambda x: x[0], reverse=True)
    shown = items[:max_results]
    out = [f"Top {len(shown)} largest files under {path}:"]
    out.extend([f"{size} {fp}" for size, fp in shown])
    if len(items) > max_results:
        out.append(f"... and {len(items) - max_results} more")
    return "\n".join(out)


def _proc_list(max_results: int = 50) -> str:
    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return "Ошибка: /proc недоступен"
    pids = []
    for name in os.listdir(proc_root):
        if name.isdigit():
            pids.append(int(name))
    pids.sort()
    out = ["pid\tcmdline"]
    shown = 0
    for p in pids:
        if shown >= max_results:
            break
        cmdline_path = os.path.join(proc_root, str(p), "cmdline")
        try:
            with open(cmdline_path, "rb") as f:
                raw = f.read(4096)
            cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
            if not cmd:
                cmd = "[kernel]"
            out.append(f"{p}\t{cmd[:200]}")
            shown += 1
        except Exception:
            continue
    if len(pids) > shown:
        out.append(f"... and {len(pids) - shown} more pids")
    return "\n".join(out)


def _proc_info(pid: int, max_bytes: int = 128_000) -> str:
    base = f"/proc/{pid}"
    if not os.path.isdir(base):
        return f"PID не найден: {pid}"
    parts = []
    for name in ["status", "cmdline", "environ"]:
        fp = os.path.join(base, name)
        if not os.path.exists(fp):
            continue
        try:
            if name in ("cmdline", "environ"):
                with open(fp, "rb") as f:
                    raw = f.read(max_bytes)
                txt = raw.replace(b"\x00", b"\n").decode("utf-8", errors="ignore")
                if name == "environ":
                    keys = []
                    for line in txt.splitlines():
                        if "=" in line:
                            keys.append(line.split("=", 1)[0])
                    txt = "\n".join(keys[:200])
            else:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read(max_bytes)
            parts.append(f"--- {fp} ---\n{txt}")
        except Exception:
            continue
    return "\n\n".join(parts) if parts else "Нет данных"


def _sys_meminfo() -> str:
    fp = "/proc/meminfo"
    if not os.path.isfile(fp):
        return "Ошибка: /proc/meminfo недоступен"
    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        data = f.read(64_000)
    keys = ["MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "SwapTotal", "SwapFree"]
    out = []
    for line in data.splitlines():
        if any(line.startswith(k + ":") for k in keys):
            out.append(line)
    return "\n".join(out) if out else data


def _sys_disk_free(path: str = "/") -> str:
    try:
        st = os.statvfs(path)
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bfree
        avail = st.f_frsize * st.f_bavail
        used = total - free
        return "\n".join([
            f"path: {os.path.abspath(path)}",
            f"total_bytes: {total}",
            f"used_bytes: {used}",
            f"free_bytes: {free}",
            f"avail_bytes: {avail}",
        ])
    except Exception as e:
        return f"Ошибка disk_free: {str(e)}"


def _read_os_release() -> str:
    fp = "/etc/os-release"
    if not os.path.isfile(fp):
        return "Ошибка: /etc/os-release не найден"
    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
        return f.read(32_000)


def _run_safe_command(argv: List[str], max_bytes: int = 256_000) -> str:
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        out = (cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")
        data = out.encode("utf-8", errors="ignore")
        if len(data) > max_bytes:
            out = data[:max_bytes].decode("utf-8", errors="ignore") + "\n...[TRUNCATED_BY_MAX_BYTES]"
        return out.strip() if out.strip() else "(no output)"
    except FileNotFoundError:
        return f"Ошибка: команда не найдена: {argv[0]}"
    except subprocess.TimeoutExpired:
        return "Ошибка: timeout"
    except Exception as e:
        return f"Ошибка: {str(e)}"


def _inspect(
    command: Optional[str],
    path: str,
    pattern: str,
    recursive: bool,
    content_query: Optional[str],
    max_results: int,
    offset: int,
    limit: int,
    depth: int,
    sort: str,
    reverse: bool,
    max_bytes: int,
    pid: Optional[int],
    unit: Optional[str],
    since: Optional[str],
    lines: int,
) -> str:
    if not command:
        return "Ошибка: для action='inspect' нужен параметр command"

    cmd = command.strip().lower()

    if cmd.startswith("journal."):
        return "Ошибка: для работы с systemd journal используй инструмент 'journal' (action: tail/unit_tail/since/query/stats)"

    if cmd in ("fs.list", "list"):
        return _list_dir(path, sort=sort, reverse=reverse, max_results=max_results)
    if cmd == "fs.tree":
        return _fs_tree(path, depth=depth, max_results=max_results)
    if cmd == "fs.head":
        return _read_file(path, 0, min(limit, lines), max_bytes=max_bytes)
    if cmd == "fs.tail":
        return _tail_file(path, n=min(lines, limit), max_bytes=max_bytes)
    if cmd == "fs.sha256":
        return _sha256_file(path)
    if cmd == "du.dir_total":
        return json.dumps(_dir_total_size(path), ensure_ascii=False, indent=2)
    if cmd == "du.top_files":
        return _top_largest_files(path, recursive=recursive, max_results=max_results)
    if cmd == "grep.contains":
        return _grep_files(path, pattern, content_query or "", recursive, max_results)
    if cmd == "grep.regex":
        return _grep_regex(path, pattern, content_query or "", recursive, max_results)
    if cmd == "log.read":
        return _read_file(path, offset, limit, max_bytes=max_bytes)
    if cmd == "log.tail":
        return _tail_file(path, n=min(lines, max_results * 10), max_bytes=max_bytes)
    if cmd == "sys.meminfo":
        return _sys_meminfo()
    if cmd == "sys.disk_free":
        return _sys_disk_free(path)
    if cmd == "env.os_release":
        return _read_os_release()
    if cmd == "env.uname":
        return str(platform.uname())
    if cmd == "proc.list":
        return _proc_list(max_results=max_results)
    if cmd == "proc.info":
        if pid is None:
            return "Ошибка: для proc.info нужен pid"
        return _proc_info(int(pid), max_bytes=max_bytes)
    if cmd == "svc.status":
        if not unit:
            return "Ошибка: для svc.status нужен unit"
        return _run_safe_command(["systemctl", "status", unit, "--no-pager", "--full"], max_bytes=max_bytes)
    if cmd == "svc.failed":
        return _run_safe_command(["systemctl", "--failed", "--no-pager", "--plain"], max_bytes=max_bytes)
    if cmd == "journal.tail":
        n = max(1, min(lines, 2000))
        return _run_safe_command(["journalctl", "-n", str(n), "--no-pager"], max_bytes=max_bytes)
    if cmd == "journal.unit_tail":
        if not unit:
            return "Ошибка: для journal.unit_tail нужен unit"
        n = max(1, min(lines, 2000))
        return _run_safe_command(["journalctl", "-u", unit, "-n", str(n), "--no-pager"], max_bytes=max_bytes)
    if cmd == "journal.since":
        if not since:
            return "Ошибка: для journal.since нужен since (например, '1 hour ago' или '2026-03-21 10:00:00')"
        n = max(1, min(lines, 2000))
        return _run_safe_command(["journalctl", "--since", since, "-n", str(n), "--no-pager"], max_bytes=max_bytes)

    return f"Ошибка: неизвестная inspect command '{command}'"


def _fs_tree(path: str, depth: int, max_results: int) -> str:
    if depth < 0:
        depth = 0
    if not os.path.exists(path):
        return f"Путь не существует: {path}"

    base = os.path.abspath(path)
    out = [base]
    count = 0

    def rec(cur: str, d: int, prefix: str):
        nonlocal count
        if count >= max_results:
            return
        if d < 0:
            return
        try:
            entries = sorted(os.listdir(cur))
        except Exception:
            return
        for name in entries:
            if count >= max_results:
                return
            fp = os.path.join(cur, name)
            is_dir = os.path.isdir(fp)
            out.append(f"{prefix}{'├─ '}{name}{'/' if is_dir else ''}")
            count += 1
            if is_dir and d > 0:
                rec(fp, d - 1, prefix + "   ")

    if os.path.isdir(base):
        rec(base, depth, "")
    return "\n".join(out) + ("\n...[TRUNCATED_BY_MAX_RESULTS]" if count >= max_results else "")


def _tail_file(path: str, n: int, max_bytes: int) -> str:
    if not os.path.isfile(path):
        return f"Файл не найден: {path}"
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        total = len(lines)
        start = max(0, total - n)
        content = "".join(lines[start:total])
        data = content.encode('utf-8', errors='ignore')
        if len(data) > max_bytes:
            content = data[-max_bytes:].decode('utf-8', errors='ignore')
            content = "...[TRUNCATED_HEAD_BY_MAX_BYTES]\n" + content
        header = f"--- TAIL {n} lines: {path} (строки {start+1}-{total} из {total}, max_bytes={max_bytes}) ---\n"
        return header + content
    except Exception as e:
        return f"Ошибка tail: {str(e)}"


def _grep_regex(path: str, pattern: str, regex: str, recursive: bool, max_results: int) -> str:
    if not regex:
        return "Ошибка: content_query обязателен для grep.regex"
    try:
        rx = re.compile(regex, re.IGNORECASE)
    except Exception as e:
        return f"Ошибка regex: {str(e)}"

    search_path = os.path.join(path, "**", pattern) if recursive else os.path.join(path, pattern)
    files = [f for f in glob.glob(search_path, recursive=recursive) if os.path.isfile(f)]

    matches = []
    for file_path in files:
        if len(matches) >= max_results:
            break
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    if rx.search(line):
                        s = line.strip()
                        if len(s) > 300:
                            s = s[:300] + "...[TRUNCATED_LINE]"
                        matches.append(f"{file_path}:{line_num}: {s}")
                        if len(matches) >= max_results:
                            break
        except Exception:
            continue

    return "\n".join(matches) if matches else "Совпадений не найдено"


def _is_within_session(target_path: str, session_path: Optional[str]) -> bool:
    """Проверяет, находится ли путь внутри сессии."""
    if not session_path:
        return False
    try:
        session = os.path.realpath(session_path)
        target = os.path.realpath(target_path)
        return target == session or target.startswith(session + os.sep)
    except Exception:
        return False


def _confirm_action(action: str, path: str, dest: Optional[str] = None) -> bool:
    """Запрашивает подтверждение у пользователя для опасного действия."""
    try:
        if dest:
            prompt = f"\n⚠️  Подтвердите {action}: '{path}' -> '{dest}' [y/N]: "
        else:
            prompt = f"\n⚠️  Подтвердите {action}: '{path}' [y/N]: "
        response = input(prompt).strip().lower()
        return response in ("y", "yes", "д", "да")
    except (EOFError, KeyboardInterrupt):
        return False


def _parse_mode(mode_str: str) -> int:
    """Парсит строку режима доступа (octal или символьную) в число."""
    if not mode_str:
        return 0o755
    try:
        # Пробуем octal (например, "755" или "0755")
        return int(mode_str, 8)
    except ValueError:
        pass
    
    # Символьное представение (например, "rwxr-xr-x")
    mode = 0
    parts = mode_str.split(",")
    for part in parts:
        part = part.strip()
        if len(part) >= 3 and part[0] in ("r", "-"):
            # Формат rwxr-xr-x
            m = 0
            for i, c in enumerate(part[:9]):
                if c != "-":
                    m |= [0o400, 0o200, 0o100, 0o040, 0o020, 0o010, 0o004, 0o002, 0o001][i]
            return m
    return 0o755


def _dangerous_action(
    action: str,
    path: str,
    dest: Optional[str] = None,
    mode: Optional[str] = None,
    session_path: Optional[str] = None,
    dangerous_mode: bool = False,
) -> str:
    """Обработчик опасных операций с файловой системой."""
    if not dangerous_mode:
        return f"Ошибка: действие '{action}' требует dangerous mode"
    
    # Проверка на пути вне сессии теперь выполняется на уровне botinok.py
    # с интерактивным подтверждением. Здесь только выполнение.
    
    try:
        if action == "delete":
            if not os.path.lexists(path):
                return f"Ошибка: путь не существует: {path}"
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return f"Удалено: {path}"
        
        elif action == "move":
            if not dest:
                return "Ошибка: для move нужен параметр dest"
            if not os.path.exists(path):
                return f"Ошибка: исходный путь не существует: {path}"
            os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
            shutil.move(path, dest)
            return f"Перемещено: {path} -> {dest}"
        
        elif action == "copy":
            if not dest:
                return "Ошибка: для copy нужен параметр dest"
            if not os.path.exists(path):
                return f"Ошибка: исходный путь не существует: {path}"
            os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
            if os.path.isdir(path):
                shutil.copytree(path, dest)
            else:
                shutil.copy2(path, dest)
            return f"Скопировано: {path} -> {dest}"
        
        elif action == "mkdir":
            mode_val = _parse_mode(mode) if mode else 0o755
            os.makedirs(path, mode=mode_val, exist_ok=True)
            return f"Создана директория: {path} (mode={oct(mode_val)})"
        
        elif action == "chmod":
            if not os.path.exists(path):
                return f"Ошибка: путь не существует: {path}"
            mode_val = _parse_mode(mode) if mode else 0o644
            os.chmod(path, mode_val)
            return f"Изменены права: {path} -> {oct(mode_val)}"
        
        elif action == "symlink":
            if not dest:
                return "Ошибка: для symlink нужен параметр dest (целевая ссылка)"
            os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
            if os.path.exists(dest):
                os.remove(dest)
            os.symlink(path, dest)
            return f"Создана ссылка: {dest} -> {path}"
        
        elif action == "touch":
            if os.path.exists(path):
                # Обновляем время модификации
                os.utime(path, None)
                return f"Обновлено время модификации: {path}"
            else:
                # Создаем пустой файл
                os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
                with open(path, "w") as f:
                    pass
                return f"Создан файл: {path}"
        
        else:
            return f"Ошибка: неизвестное опасное действие '{action}'"
            
    except Exception as e:
        return f"Ошибка при {action}: {str(e)}"


def _find_files(
    path: str,
    pattern: str = "*",
    ftype: str = "any",
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    mtime_days: Optional[int] = None,
    max_depth: int = 10,
    max_results: int = 50,
) -> str:
    """Продвинутый поиск файлов с фильтрами (read-only, безопасный)."""
    if not os.path.exists(path):
        return f"Путь не существует: {path}"
    
    results = []
    now = time.time()
    cutoff_time = now - (mtime_days * 86400) if mtime_days else None
    
    try:
        for root, dirs, files in os.walk(path):
            # Ограничиваем глубину
            depth = root.count(os.sep) - path.count(os.sep)
            if depth >= max_depth:
                del dirs[:]
                continue
            
            for name in files + dirs:
                if len(results) >= max_results:
                    break
                    
                full_path = os.path.join(root, name)
                
                # Проверяем паттерн
                if not fnmatch.fnmatch(name, pattern):
                    continue
                
                # Определяем тип
                is_file = os.path.isfile(full_path)
                is_dir = os.path.isdir(full_path) and not os.path.islink(full_path)
                is_link = os.path.islink(full_path)
                
                # Фильтр по типу
                if ftype == "file" and not is_file:
                    continue
                if ftype == "dir" and not is_dir:
                    continue
                if ftype == "link" and not is_link:
                    continue
                
                # Фильтр по размеру
                if is_file:
                    try:
                        size = os.path.getsize(full_path)
                        if min_size is not None and size < min_size:
                            continue
                        if max_size is not None and size > max_size:
                            continue
                    except Exception:
                        continue
                
                # Фильтр по времени модификации
                if cutoff_time:
                    try:
                        mtime = os.path.getmtime(full_path)
                        if mtime < cutoff_time:
                            continue
                    except Exception:
                        continue
                
                # Добавляем в результаты
                tag = "[LINK]" if is_link else "[DIR]" if is_dir else "[FILE]"
                size_str = str(os.path.getsize(full_path)) if is_file else "-"
                results.append(f"{tag} {full_path} (size={size_str})")
            
            if len(results) >= max_results:
                break
    except Exception as e:
        return f"Ошибка при поиске: {str(e)}"
    
    if not results:
        return f"Ничего не найдено в {path} с фильтрами: pattern='{pattern}', type='{ftype}'"
    
    header = f"Найдено {len(results)} элементов (max_results={max_results}):"
    output = [header] + results
    
    return "\n".join(output)
