#!/usr/bin/env python3
"""
Единый реестр безопасных (read-only) операций и подсказок для агента.

Используется:
  * `tools/file_system.py` — реализует операции (`action=inspect` + `action=help`);
  * `core/tool_manager.py` — при запрете `shell_exec run` предлагает безопасный
    эквивалент на основе этого же реестра.

Принципы безопасности:
  * только чтение, никакой мутации;
  * запуск через argv без shell (`subprocess`, не `shell=True`);
  * лимит вывода (max_bytes) и таймаут;
  * для файлов — только обычные файлы (без /dev, FIFO, сокетов).

Никакой доменной логики: реестр — это каталог возможностей, а не сценарии задач.
"""

import base64
import hashlib
import os
import shlex
import shutil
import subprocess
from typing import Dict, List, Optional

DEFAULT_MAX_BYTES = 256_000
BASE64_MAX_BYTES = 20_000_000
TIMEOUT_SEC = 15


# --------------------------------------------------------------------------
# Запуск без shell
# --------------------------------------------------------------------------

def _run(argv: List[str], max_bytes: int = DEFAULT_MAX_BYTES, timeout: int = TIMEOUT_SEC,
         cwd: Optional[str] = None) -> str:
    env = dict(os.environ)
    env.setdefault("LC_ALL", "C")  # стабильный машинночитаемый вывод
    env.setdefault("LANG", "C")
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            cwd=cwd, env=env)
    except FileNotFoundError:
        return f"Ошибка: команда не найдена: {argv[0]}"
    except subprocess.TimeoutExpired:
        return "Ошибка: timeout"
    except Exception as e:
        return f"Ошибка: {e}"
    out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr else "")
    data = out.encode("utf-8", errors="ignore")
    if len(data) > max_bytes:
        out = data[:max_bytes].decode("utf-8", errors="ignore") + "\n...[TRUNCATED_BY_MAX_BYTES]"
    return out.strip() if out.strip() else "(no output)"


def _regular_file(path: str) -> Optional[str]:
    if not path:
        return "Ошибка: не указан path"
    if os.path.islink(path):
        # Читаем сам файл, а не спецфайл; ссылку не разыменовываем молча.
        real = os.path.realpath(path)
        if not os.path.isfile(real):
            return f"Ошибка: не обычный файл: {path}"
        return None
    if not os.path.isfile(path):
        return f"Ошибка: не обычный файл: {path}"
    return None


# --------------------------------------------------------------------------
# Файловые операции
# --------------------------------------------------------------------------

def file_base64(path: str, max_bytes: int = BASE64_MAX_BYTES) -> str:
    """Файл → base64 (без префикса data:, как ждут API вроде Ollama)."""
    err = _regular_file(path)
    if err:
        return err
    size = os.path.getsize(path)
    if size > max_bytes:
        return (f"Ошибка: файл {size} байт больше лимита {max_bytes} "
                f"(увеличь max_bytes, если нужно)")
    with open(path, "rb") as f:
        data = f.read(max_bytes + 1)
    return base64.b64encode(data).decode("ascii")


def file_type(path: str) -> str:
    err = _regular_file(path)
    if err:
        return err
    return _run(["file", "-b", "--", path])


def stat_file(path: str) -> str:
    err = _regular_file(path)
    if err:
        return err
    return _run(["stat", "--", path])


def count_file(path: str) -> str:
    err = _regular_file(path)
    if err:
        return err
    return _run(["wc", "-l", "-w", "-c", "--", path])


def readlink_file(path: str) -> str:
    if not path or not os.path.islink(path):
        return f"Ошибка: не симлинк: {path}"
    return os.readlink(path)


def hash_file(path: str, algo: str = "sha256") -> str:
    err = _regular_file(path)
    if err:
        return err
    algo = (algo or "sha256").lower()
    if algo not in ("md5", "sha1", "sha256", "sha512"):
        return "Ошибка: algo должен быть md5|sha1|sha256|sha512"
    h = hashlib.new(algo)
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception as e:
        return f"Ошибка: {e}"
    return f"{algo}: {h.hexdigest()}"


def listing(path: str, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    target = path or "."
    return _run(["ls", "-la", "--", target], max_bytes=max_bytes)


def base64_decode(text: str) -> str:
    if not text:
        return "Ошибка: не передана строка base64 (используй content_query)"
    try:
        raw = base64.b64decode(text, validate=False)
        return raw.decode("utf-8", errors="replace")
    except Exception as e:
        return f"Ошибка декодирования base64: {e}"


# --------------------------------------------------------------------------
# Система / процессы / сервисы
# --------------------------------------------------------------------------

def sys_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
    except Exception as e:
        return f"Ошибка: {e}"
    days, rem = divmod(int(secs), 86400)
    hours, rem = divmod(rem, 3600)
    mins, s = divmod(rem, 60)
    return f"uptime: {days}d {hours}h {mins}m {s}s ({secs:.0f} сек)"


def sys_loadavg() -> str:
    try:
        one, five, fifteen = os.getloadavg()
        return f"loadavg: {one:.2f} {five:.2f} {fifteen:.2f}"
    except Exception as e:
        return f"Ошибка: {e}"


def sys_cpu(max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    if shutil.which("lscpu"):
        return _run(["lscpu"], max_bytes=max_bytes)
    try:
        with open("/proc/cpuinfo") as f:
            data = f.read(max_bytes)
        return data
    except Exception as e:
        return f"Ошибка: {e}"


def sys_mounts(max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    try:
        with open("/proc/mounts") as f:
            data = f.read(max_bytes)
        return data
    except Exception as e:
        return f"Ошибка: {e}"


def proc_top(max_results: int = 20) -> str:
    n = max(1, min(int(max_results or 20), 200))
    out = _run(["ps", "-eo", "pid,comm,%cpu,%mem,etime", "--sort=-%cpu", "--no-headers"])
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return "\n".join(lines[:n]) if lines else out


def svc_list(max_results: int = 100) -> str:
    return _run(["systemctl", "list-units", "--type=service", "--no-pager",
                 "--plain", "--no-legend"], max_bytes=max(4096, int(max_results or 100) * 120))


# --------------------------------------------------------------------------
# Сеть (только чтение)
# --------------------------------------------------------------------------

def net_interfaces() -> str:
    if shutil.which("ip"):
        return _run(["ip", "addr"])
    return _run(["ifconfig"])


def net_ports() -> str:
    if shutil.which("ss"):
        return _run(["ss", "-tuln"])
    return _run(["netstat", "-tuln"])


def net_dns(name: str) -> str:
    if not name:
        return "Ошибка: не указано имя (используй content_query)"
    if shutil.which("getent"):
        return _run(["getent", "hosts", name])
    if shutil.which("dig"):
        return _run(["dig", "+short", name])
    return _run(["host", name])


# --------------------------------------------------------------------------
# Разработка / медиа
# --------------------------------------------------------------------------

def dev_which(name: str) -> str:
    if not name:
        return "Ошибка: не указано имя (используй content_query)"
    found = shutil.which(name)
    if found:
        return found
    return _run(["which", name])


def image_meta(path: str) -> str:
    err = _regular_file(path)
    if err:
        return err
    try:
        from PIL import Image, ExifTags
    except Exception:
        return "Ошибка: Pillow не установлен"
    try:
        with Image.open(path) as img:
            lines = [f"format: {img.format}", f"mode: {img.mode}",
                     f"size: {img.width}x{img.height}"]
            exif = getattr(img, "_getexif", lambda: None)()
            if exif:
                for tag_id, value in list(exif.items())[:30]:
                    name = ExifTags.TAGS.get(tag_id, tag_id)
                    lines.append(f"exif.{name}: {str(value)[:120]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка: {e}"


def _git(args: List[str], path: str, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    workdir = path or "."
    return _run(["git", "-C", workdir] + args, max_bytes=max_bytes)


def git_read(subcmd: str, path: str, arg: str = "", max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    sub = (subcmd or "").lower()
    table = {
        "git.status": ["status", "-sb"],
        "git.log": ["log", "--oneline", "-n", "30"],
        "git.diff": ["diff", "--stat"],
        "git.show": ["show", "--stat", "--oneline", "-n", "1"],
        "git.remote": ["remote", "-v"],
        "git.branch": ["branch", "-a"],
        "git.tag": ["tag", "--sort=-creatordate"],
        "git.ls_files": ["ls-files"],
        "git.grep": ["grep", "-n", "--max-count=50", arg] if arg else ["grep", "-n", "--max-count=50"],
    }
    argv = table.get(sub)
    if not argv:
        return f"Ошибка: неизвестная git-операция '{subcmd}'"
    return _git(argv, path, max_bytes=max_bytes)


# --------------------------------------------------------------------------
# Каталог и подсказки
# --------------------------------------------------------------------------

# name -> описание для справки и подсказок
CATALOG: Dict[str, str] = {
    "fs.base64": "файл → base64 (для API/vision)",
    "fs.file_type": "тип файла (file)",
    "fs.stat": "метаданные файла (stat)",
    "fs.count": "строки/слова/байты (wc)",
    "fs.readlink": "куда указывает симлинк",
    "fs.hash": "хеш файла (algo=md5|sha1|sha256|sha512)",
    "fs.listing": "ls -la",
    "text.base64_decode": "base64 → текст",
    "sys.uptime": "аптайм",
    "sys.loadavg": "средняя нагрузка",
    "sys.cpu": "информация о CPU",
    "sys.mounts": "смонтированные ФС",
    "proc.top": "топ процессов по CPU",
    "svc.list": "список сервисов systemd",
    "net.interfaces": "интерфейсы/адреса",
    "net.ports": "слушающие порты",
    "net.dns": "resolve имени (content_query)",
    "dev.which": "где находится бинарник (content_query)",
    "image.meta": "размер/EXIF изображения",
    "git.status": "git status",
    "git.log": "git log --oneline",
    "git.diff": "git diff --stat",
    "git.show": "git show (последний коммит)",
    "git.remote": "git remote -v",
    "git.branch": "git branch -a",
    "git.tag": "git tag",
    "git.ls_files": "git ls-files",
    "git.grep": "git grep (content_query)",
}

# бинарник shell → безопасная альтернатива (шаблон вызова)
_SHELL_SUGGEST = {
    "base64": 'file_system action=inspect command=fs.base64 path="<файл>"',
    "file": 'file_system action=inspect command=fs.file_type path="<файл>"',
    "stat": 'file_system action=inspect command=fs.stat path="<файл>"',
    "wc": 'file_system action=inspect command=fs.count path="<файл>"',
    "readlink": 'file_system action=inspect command=fs.readlink path="<симлинк>"',
    "cat": 'file_system action=read path="<файл>"',
    "head": 'file_system action=read path="<файл>" limit=<N>',
    "tail": 'file_system action=inspect command=fs.tail path="<файл>" lines=<N>',
    "less": 'file_system action=read path="<файл>"',
    "more": 'file_system action=read path="<файл>"',
    "ls": 'file_system action=list path="<каталог>"',
    "dir": 'file_system action=list path="<каталог>"',
    "find": 'file_system action=find path="<каталог>" pattern="<маска>"',
    "grep": 'file_system action=grep path="<каталог>" pattern="<regex>" content_query="<строка>"',
    "egrep": 'file_system action=grep path="<каталог>" pattern="<regex>" content_query="<строка>"',
    "rg": 'file_system action=grep path="<каталог>" pattern="<regex>" content_query="<строка>"',
    "sha256sum": 'file_system action=inspect command=fs.hash algo=sha256 path="<файл>"',
    "sha1sum": 'file_system action=inspect command=fs.hash algo=sha1 path="<файл>"',
    "md5sum": 'file_system action=inspect command=fs.hash algo=md5 path="<файл>"',
    "df": 'file_system action=inspect command=sys.disk_free path="<путь>"',
    "du": 'file_system action=inspect command=du.top_files path="<каталог>"',
    "free": 'file_system action=inspect command=sys.meminfo',
    "uptime": 'file_system action=inspect command=sys.uptime',
    "ps": 'file_system action=inspect command=proc.top',
    "top": 'file_system action=inspect command=proc.top',
    "systemctl": 'file_system action=inspect command=svc.status unit="<unit>"',
    "journalctl": 'journal action=query (или file_system action=inspect command=journal.tail)',
    "ip": 'file_system action=inspect command=net.interfaces',
    "ifconfig": 'file_system action=inspect command=net.interfaces',
    "ss": 'file_system action=inspect command=net.ports',
    "netstat": 'file_system action=inspect command=net.ports',
    "dig": 'file_system action=inspect command=net.dns content_query="<имя>"',
    "host": 'file_system action=inspect command=net.dns content_query="<имя>"',
    "nslookup": 'file_system action=inspect command=net.dns content_query="<имя>"',
    "which": 'file_system action=inspect command=dev.which content_query="<имя>"',
    "type": 'file_system action=inspect command=dev.which content_query="<имя>"',
    "identify": 'file_system action=inspect command=image.meta path="<файл>"',
    "uname": 'file_system action=inspect command=env.uname',
    "git": 'file_system action=inspect command=git.log path="<репозиторий>"',
}


# Синонимы/сокращения → каноническая операция (прощающий ввод).
_ALIASES = {
    "base64": "fs.base64", "b64": "fs.base64",
    "file_type": "fs.file_type", "filetype": "fs.file_type", "file": "fs.file_type",
    "stat": "fs.stat", "count": "fs.count", "wc": "fs.count",
    "readlink": "fs.readlink", "hash": "fs.hash", "sha256": "fs.hash", "md5": "fs.hash",
    "ls": "fs.listing", "listing": "fs.listing", "ll": "fs.listing",
    "base64_decode": "text.base64_decode", "b64decode": "text.base64_decode",
    "uptime": "sys.uptime", "loadavg": "sys.loadavg", "cpu": "sys.cpu",
    "mounts": "sys.mounts", "top": "proc.top", "ps": "proc.top",
    "services": "svc.list", "svc": "svc.list",
    "interfaces": "net.interfaces", "ports": "net.ports", "dns": "net.dns",
    "which": "dev.which", "image": "image.meta",
    "status": "git.status", "log": "git.log", "diff": "git.diff",
    "show": "git.show", "remote": "git.remote", "branch": "git.branch",
    "tag": "git.tag", "ls_files": "git.ls_files", "grep_git": "git.grep",
}


def normalize_command(name: str) -> Optional[str]:
    """Привести ввод к канонической операции (прощающий ввод)."""
    if not name:
        return None
    cmd = str(name).strip().lower().replace(" ", ".").replace("_", "_")
    if cmd in CATALOG:
        return cmd
    if cmd in _ALIASES:
        return _ALIASES[cmd]
    # частичное совпадение по суффиксу, напр. "ports" → net.ports
    for key in CATALOG:
        if key.split(".")[-1] == cmd:
            return key
    return None


def suggest_command(name: str) -> Optional[str]:
    """Ближайшая операция по вводу (для «похоже, вы имели в виду»)."""
    import difflib
    options = list(CATALOG.keys()) + list(_ALIASES.keys())
    match = difflib.get_close_matches(str(name or "").strip().lower(), options, n=1, cutoff=0.6)
    if not match:
        return None
    return _ALIASES.get(match[0], match[0])


def advice_for(command: str, result: str) -> str:
    """Короткий совет/следующий шаг после безопасной операции."""
    cmd = command or ""
    if cmd == "fs.base64":
        return ('💡 для API не копируй base64 вручную: web сам закодирует файл — '
                'json_body={…"images":[{"$file_base64":"<путь>"}]}')
    if cmd == "fs.file_type":
        return "💡 если это HTML вместо файла — источник отдал заглушку (капча/rate-limit)"
    if cmd == "image.meta":
        return "💡 чтобы отправить изображение в API — file_system action=inspect command=fs.base64"
    if cmd == "net.ports":
        return "💡 к локальному порту можно обратиться через web (http://localhost:<port>/)"
    if cmd.startswith("git."):
        return "💡 другие git-операции: file_system action=inspect command=git.<status|log|diff|show|branch|tag>"
    if "Ошибка" in (result or "") or "not found" in (result or "").lower():
        return "💡 полный список безопасных операций: file_system action=help"
    return ""


def suggest_for_shell(command: str) -> Optional[str]:
    """По shell-команде вернуть безопасный эквивалент (без исполнения)."""
    if not command or not str(command).strip():
        return None
    try:
        parts = shlex.split(str(command))
    except Exception:
        parts = str(command).split()
    if not parts:
        return None
    binary = os.path.basename(parts[0])
    template = _SHELL_SUGGEST.get(binary)
    if not template:
        return None
    # Подставим первый похожий на путь аргумент вместо <файл>.
    arg_path = next((p for p in parts[1:] if not p.startswith("-") and ("/" in p or "." in p)),
                    None)
    if arg_path:
        template = template.replace("<файл>", arg_path).replace("<каталог>", arg_path)
    return template


_SECTIONS = (
    ("📂 Файлы", ("fs.base64", "fs.file_type", "fs.stat", "fs.count", "fs.hash",
                  "fs.listing", "fs.readlink", "text.base64_decode")),
    ("🖥 Система", ("sys.uptime", "sys.loadavg", "sys.cpu", "sys.mounts",
                    "proc.top", "svc.list")),
    ("🌐 Сеть", ("net.interfaces", "net.ports", "net.dns")),
    ("🧩 Разработка", ("dev.which", "git.status", "git.log", "git.diff", "git.show",
                       "git.remote", "git.branch", "git.tag", "git.ls_files", "git.grep")),
    ("🖼 Медиа", ("image.meta",)),
)


def catalog() -> str:
    lines = ["🧰 file_system — безопасные операции (без dangerous mode)", ""]
    for title, names in _SECTIONS:
        lines.append(title)
        for name in names:
            lines.append(f"  {name:<20} — {CATALOG.get(name, '')}")
        lines.append("")
    lines += [
        "Как вызывать:",
        "  file_system action=inspect command=<операция> [path=…] [content_query=…] [algo=…]",
        "",
        "Примеры:",
        '  file_system action=inspect command=fs.base64 path="/…/photo.jpg"',
        '  file_system action=inspect command=fs.hash algo=sha256 path="/…/image.iso"',
        '  file_system action=inspect command=fs.file_type path="/…/download.bin"',
        '  file_system action=inspect command=net.ports',
        '  file_system action=inspect command=git.log path="/…/repo"',
        "",
        "Для отправки фото в API (без ручного base64):",
        '  web action=json url="http://localhost:11434/api/chat" method=POST \\',
        '      json_body={"model":"…","messages":[{"role":"user","content":"…",',
        '                 "images":[{"$file_base64":"/…/photo.jpg"}]}]}',
        "",
        "Мутации (delete/move/copy/mkdir/chmod/symlink/touch) разрешены внутри папки сессии.",
        "Выполнение кода (shell_exec run) — только dangerous mode; инструмент подскажет безопасный эквивалент.",
    ]
    return "\n".join(lines)


def catalog_short() -> str:
    names = ", ".join(CATALOG.keys())
    return f"Безопасные операции (file_system action=help): {names}"
