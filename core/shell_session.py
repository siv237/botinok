"""
Неблокирующая PTY-сессия для shell-команд.

Ядро механики «shell как отдельная сессия»: процесс крутится в собственном
псевдотерминале и НЕ держит агента. Агент (и пользователь) могут:
  * читать вывод порциями (tail) — без выгрузки всего буфера в контекст;
  * искать по выводу (строка / regex);
  * отправлять ввод в ту же сессию, что и пользователь (пароли, пункты меню);
  * узнавать, жива ли ещё команда, и дожидаться её завершения.

UI (core/shell_screen.py) — лишь один из наблюдателей этой сессии.
"""

from __future__ import annotations

import atexit
import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import threading
import time
import uuid
from collections import deque
from typing import Dict, List, Optional

# Управляющие последовательности, которые не несут текстового смысла:
# альтернативный экран, сохранение/восстановление курсора, видимость курсора.
_ANSI_SCREEN_RE = re.compile(
    rb"(?:\x1b\[\??(?:1049|1047|47|1048)[hl]"
    rb"|\x1b\[\?25[hl]"
    rb"|\x1b7|\x1b8)",
)
# Все ANSI CSI/OSC/SGR escape-последовательности.
_ANSI_ESCAPE_RE = re.compile(
    rb"(?:\x1b\[[0-9;?]*[A-Za-z]"
    rb"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    rb"|\x1b[()][AB012]"
    rb"|\x1b[=>]"
    rb"|\x1b"
    rb"|\x08)"
)

# Символы, которые readline/echo отдают при редактировании строки — режем их из
# «чистого» буфера, чтобы поиск по выводу работал предсказуемо.
_BACKSPACE_RE = re.compile(rb"\x08\x20\x08")

MAX_BUFFER_BYTES = 4 * 1024 * 1024  # лимит «сырого» буфера вывода для агента
MAX_BUFFER_LINES = 20000  # лимит «чистых» строк, доступных чтению/поиску
MAX_SEARCH_MATCHES = 200  # сколько совпадений максимум отдаёт search_output
MAX_SEARCH_CONTEXT = 50  # верхняя граница контекста вокруг совпадения


def _strip_ansi(raw: bytes) -> bytes:
    """Сырые байты PTY → чистый текст для поиска/чтения агентом."""
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    raw = _BACKSPACE_RE.sub(b"", raw)
    raw = _ANSI_SCREEN_RE.sub(b"", raw)
    raw = _ANSI_ESCAPE_RE.sub(b"", raw)
    return raw


class ShellSession:
    """Живая PTY-сессия команды. Потокобезопасна для одного писателя/читателя."""

    def __init__(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout_sec: int = 0,
        env: Optional[Dict[str, str]] = None,
        rows: int = 24,
        cols: int = 100,
        name: str = "",
    ) -> None:
        self.session_id = f"sh_{uuid.uuid4().hex[:8]}"
        self.name = name or command
        self.command = command
        self.cwd = os.path.realpath(cwd) if cwd else os.getcwd()
        self.timeout_sec = max(0, int(timeout_sec or 0))
        self.rows = int(rows) if rows else 24
        self.cols = int(cols) if cols else 100
        self.env = env

        self._master: Optional[int] = None
        self._slave: Optional[int] = None
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._closed = False

        # Необработанный вывод (с ANSI) — для артефакта/UI.
        self._raw: deque = deque(maxlen=MAX_BUFFER_BYTES)
        # Очищенный вывод — для поиска/чтения агентом. Ограничен по числу строк,
        # иначе долгоживущая сессия с большим выводом съест память.
        self._clean_str: deque = deque(maxlen=MAX_BUFFER_LINES)
        self._partial = b""  # недоохваченный хвост при разрезании на строки
        self._total_clean_bytes = 0
        self._total_clean_lines = 0
        self._total_raw_bytes = 0

        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.returncode: Optional[int] = None
        self._stop_flag = threading.Event()

        # Подписчики на свежие порции сырого вывода: UI-экран.
        self._subscribers: List[callable] = []

    # ------------------------------------------------------------------ life

    def start(self) -> None:
        """Открывает PTY и запускает процесс. Неблокирующий."""
        self._master, self._slave = pty.openpty()

        # Неблокирующее чтение мастера —	reader крутит select().
        self._set_nonblocking(self._master)

        argv = ["/bin/bash", "-c", self.command]
        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        env["LINES"] = str(self.rows)
        env["COLUMNS"] = str(self.cols)
        if self.env:
            env.update(self.env)

        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=self._slave,
                stdout=self._slave,
                stderr=self._slave,
                cwd=self.cwd,
                env=env,
                start_new_session=True,
            )
        except Exception:
            # Старт не удался — закрываем оба конца PTY, иначе дескрипторы утекут.
            for fd in (self._master, self._slave):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            self._master = None
            self._slave = None
            raise
        # Slave больше не нужен в родителе — дочерний процесс его унаследовал.
        try:
            os.close(self._slave)
        except OSError:
            pass
        self._slave = None

        self.set_winsize(self.rows, self.cols)

        self._reader_thread = threading.Thread(
            target=self._reader_loop, name=f"shell-rd-{self.session_id}", daemon=True
        )
        self._reader_thread.start()

    def _set_nonblocking(self, fd: int) -> None:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def set_winsize(self, rows: int, cols: int) -> None:
        self.rows = max(1, int(rows))
        self.cols = max(1, int(cols))
        if self._master is None:
            return
        try:
            fcntl.ioctl(
                self._master,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", self.rows, self.cols, 0, 0),
            )
        except OSError:
            pass

    # ---------------------------------------------------------------- read

    def _reader_loop(self) -> None:
        """Читает master PTY в буферы и оповещает подписчиков."""
        deadline = (self.started_at + self.timeout_sec) if self.timeout_sec else None
        while not self._stop_flag.is_set():
            if self._proc is not None and self._proc.poll() is not None:
                # Процесс умер: дочитываем остаток и выходим.
                self._drain(timeout=0.3)
                break
            if deadline is not None and time.time() > deadline:
                self.kill()
                break
            try:
                ready, _, _ = select.select([self._master], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            self._drain(timeout=0.0)

        self._drain(timeout=0.5)
        with self._lock:
            if self._proc is not None:
                self.returncode = self._proc.returncode
                if self.returncode is None:
                    self.returncode = self._proc.wait()
            self.finished_at = time.time()
        self._notify(b"")

    def _drain(self, timeout: float = 0.0) -> None:
        """Вычитывает всё доступное из мастера."""
        end = time.time() + timeout if timeout else time.time()
        while True:
            wait = 0.0
            if timeout:
                remaining = end - time.time()
                if remaining <= 0:
                    return
                # Реальный таймаут, чтобы не крутить CPU вхолостую.
                wait = min(remaining, 0.05)
            try:
                ready, _, _ = select.select([self._master], [], [], wait)
            except (OSError, ValueError):
                return
            if not ready:
                if timeout:
                    continue
                return
            try:
                chunk = os.read(self._master, 65536)
            except BlockingIOError:
                return
            except OSError:
                return
            if not chunk:
                return
            self._append_chunk(chunk)

    def _append_chunk(self, chunk: bytes) -> None:
        with self._lock:
            self._total_raw_bytes += len(chunk)
            self._raw.extend(chunk)
            clean = _strip_ansi(chunk)
            self._total_clean_bytes += len(clean)
            self._partial += clean
            if b"\n" in self._partial:
                *lines, self._partial = self._partial.split(b"\n")
                for ln in lines:
                    try:
                        self._clean_str.append(ln.decode("utf-8", "ignore"))
                    except Exception:
                        self._clean_str.append(repr(ln))
                    self._total_clean_lines += 1
            else:
                # Промпты без перевода строки ('Password:', 'choose>') тоже должны
                # быть видны агенту — досдаём хвост, не дожидаясь Enter.
                self._flush_partial_locked()
        self._notify(chunk)

    # ------------------------------------------------------------ subscribe

    def subscribe(self, callback) -> None:
        """Подписаться на свежие сырые порции (callback(bytes) вызывается из потока-ридера)."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        with self._lock:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    def _notify(self, chunk: bytes) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(chunk)
            except Exception:
                pass

    # ----------------------------------------------------------------- API

    def is_running(self) -> bool:
        return self.returncode is None and not self._closed

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at

    @property
    def lines_total(self) -> int:
        """Всего чистых строк вывода за всю жизнь сессии (не только удержанных в буфере)."""
        return self._total_clean_lines

    def send_bytes(self, data: bytes) -> int:
        """Отправить сырые байты в PTY (основной низкоуровневый метод)."""
        if self._master is None or self._closed:
            return 0
        try:
            return os.write(self._master, data)
        except OSError:
            return 0

    def send_input(self, text: str) -> int:
        """Отправить текст в сессию (как будто пользователь набрал и нажал Enter).

        Двойной перевод строки не добавляем: PTY-эхо и readline сами покажут ввод.
        """
        if not text:
            return 0
        data = text.encode("utf-8", "ignore")
        if data and not data.endswith(b"\n"):
            data += b"\n"
        return self.send_bytes(data.replace(b"\n", b"\r"))

    # Клавиатурные сокращения для меню/интерактивных программ.
    KEY_SEQUENCES: Dict[str, bytes] = {
        "enter": b"\r",
        "return": b"\r",
        "tab": b"\t",
        "esc": b"\x1b",
        "escape": b"\x1b",
        "up": b"\x1b[A",
        "down": b"\x1b[B",
        "right": b"\x1b[C",
        "left": b"\x1b[D",
        "home": b"\x1b[H",
        "end": b"\x1b[F",
        "pageup": b"\x1b[5~",
        "pagedown": b"\x1b[6~",
        "space": b" ",
        "backspace": b"\x7f",
        "del": b"\x1b[3~",
        "ctrl-c": b"\x03",
        "ctrl_c": b"\x03",
        "ctrl-d": b"\x04",
        "ctrl_d": b"\x04",
        "ctrl-z": b"\x1a",
        "ctrl_z": b"\x1a",
        "ctrl-a": b"\x01",
        "ctrl-e": b"\x05",
        "ctrl-k": b"\x0b",
        "ctrl-u": b"\x15",
        "ctrl-w": b"\x17",
        "ctrl-l": b"\x0c",
        "f1": b"\x1bOP",
        "f2": b"\x1bOQ",
        "f3": b"\x1bOR",
        "f4": b"\x1bOS",
        "y": b"y",
        "n": b"n",
    }

    def send_key(self, key: str) -> int:
        """Отправить специальную клавишу/одиночный символ (enter, down, ctrl-c, 'y', ...)."""
        k = (key or "").strip().lower()
        seq = self.KEY_SEQUENCES.get(k)
        if seq is None:
            seq = key.encode("utf-8", "ignore") if key else b""
        return self.send_bytes(seq)

    # -------------------------------------------------------------- queries

    def _flush_partial_locked(self) -> None:
        """Сдать недоохваченный хвост — вызывается уже под self._lock."""
        if not self._partial:
            return
        try:
            self._clean_str.append(self._partial.decode("utf-8", "ignore"))
        except Exception:
            self._clean_str.append(repr(self._partial))
        self._total_clean_lines += 1
        self._partial = b""

    def get_output(self, tail_lines: int = 50) -> str:
        """Очищенный от ANSI хвост вывода — для контекста агента."""
        with self._lock:
            lines = list(self._clean_str)
            if self._partial:
                lines.append(self._partial.decode("utf-8", "ignore"))
            if tail_lines and len(lines) > tail_lines:
                return "\n".join(lines[-tail_lines:])
            return "\n".join(lines)

    def get_raw_tail(self, max_bytes: int = 65536) -> bytes:
        """Сырой (с ANSI) хвост вывода — для артефакта."""
        with self._lock:
            return bytes(self._raw)[-max_bytes:]

    def search_output(self, pattern: str, regex: bool = False,
                      tail_lines: int = 2000, context: int = 0) -> str:
        """Поиск по выводу. Возвращает найденные строки (с контекстом)."""
        try:
            context = int(context)
        except (TypeError, ValueError):
            context = 0
        context = max(0, min(context, MAX_SEARCH_CONTEXT))
        with self._lock:
            lines = list(self._clean_str)
            if self._partial:
                lines.append(self._partial.decode("utf-8", "ignore"))
            if tail_lines and len(lines) > tail_lines:
                lines = lines[-tail_lines:]

        def around(i: int) -> str:
            if context <= 0:
                return f"[{i}] {lines[i]}"
            lo = max(0, i - context)
            hi = min(len(lines), i + context + 1)
            return f"[{i}] " + "\n".join(lines[lo:hi])

        def scan(predicate) -> List[str]:
            found: List[str] = []
            for i, ln in enumerate(lines):
                if predicate(ln):
                    found.append(around(i))
                    if len(found) >= MAX_SEARCH_MATCHES:
                        break
            return found

        if regex:
            try:
                rx = re.compile(pattern)
            except re.error as e:
                return f"Ошибка regex: {e}"
            matches = scan(rx.search)
        else:
            needle = pattern
            matches = scan(lambda ln: needle in ln)
        if not matches:
            return f"Совпадений не найдено: {pattern!r}"
        return "\n".join(matches)

    def wait(self, timeout_sec: float = 10.0) -> bool:
        """Дождаться завершения команды. True — команда завершилась."""
        if self._reader_thread is None:
            return True
        self._reader_thread.join(timeout=max(0.1, float(timeout_sec)))
        return not self.is_running()

    def kill(self) -> None:
        """SIGINT всей группе процесса, при необходимости — SIGKILL."""
        if self._proc is None:
            return
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGINT)
        except Exception:
            try:
                self._proc.send_signal(signal.SIGINT)
            except Exception:
                pass
        # Popen.wait(timeout=...) бросает TimeoutExpired, а не возвращает None.
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            try:
                self._proc.wait(timeout=2)
            except Exception:
                pass

    def close(self) -> None:
        """Жёстко закрыть сессию (kill + закрыть мастер)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._stop_flag.set()
        try:
            self.kill()
        except Exception:
            pass
        for fd_attr in ("_master",):
            fd = getattr(self, fd_attr, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, fd_attr, None)

    # -------------------------------------------------------------- summary

    def status_dict(self, tail_lines: int = 30) -> dict:
        running = self.is_running()
        out_tail = self.get_output(tail_lines) if tail_lines else ""
        rc = self.returncode
        return {
            "session_id": self.session_id,
            "name": self.name,
            "command": self.command,
            "cwd": self.cwd,
            "running": running,
            "returncode": rc,
            "elapsed": round(self.elapsed, 2),
            "timeout_sec": self.timeout_sec,
            "lines_total": self._total_clean_lines,
            "buffered_lines": len(self._clean_str),
            "bytes_total": self._total_clean_bytes,
            "output_tail": out_tail,
        }


# ------------------------------------------------------------------ registry

class TextualAppRegistry:
    """Глобально хранит живое Textual-приложение.

    Проблема, которую решает этот класс: ботинок вызывает инструменты в
    рабочем потоке (textual_integration._stream_turn поднимается как
    threading.Thread). ContextVar `active_app` НЕ наследуется потоками, и в
    рабочем потоке `_active_textual_app()` ничего не найдёт — модальный экран
    терминала никогда бы не открылся.

    Поэтому приложение регистрируем явно (обычный модуль-глобал — он виден из
    любого потока), а экран пушим через `app.call_from_thread(...)`, который
    выполняет код в правильном контексте (Textual 8.2).
    """

    _app = None
    _lock = threading.Lock()

    @classmethod
    def set_app(cls, app) -> None:
        with cls._lock:
            cls._app = app

    @classmethod
    def get_app(cls):
        with cls._lock:
            return cls._app

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._app = None


class ShellSessionRegistry:
    """Одиночка: хранит живые shell-сессии, чтобы агент и UI могли к ним обращаться."""

    _instance: Optional["ShellSessionRegistry"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._sessions: Dict[str, ShellSession] = {}
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "ShellSessionRegistry":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def add(self, session: ShellSession) -> str:
        with self._lock:
            self._sessions[session.session_id] = session
        return session.session_id

    def get(self, session_id: str) -> Optional[ShellSession]:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> List[dict]:
        with self._lock:
            return [s.status_dict(tail_lines=0) for s in self._sessions.values()]

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def cleanup_dead(self) -> None:
        with self._lock:
            dead = [sid for sid, s in self._sessions.items()
                    if not s.is_running() and s.finished_at is not None
                    and (time.time() - (s.finished_at or 0)) > 600]
        for sid in dead:
            s = self.get(sid)
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
            self.remove(sid)

    def close_all(self) -> None:
        """Жёстко закрыть все сессии (вызывается при завершении процесса)."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass


def _shutdown_sessions() -> None:
    """atexit: не оставляем осиротевшие процессы и PTY-дескрипторы после выхода."""
    try:
        ShellSessionRegistry.instance().close_all()
    except Exception:
        pass


atexit.register(_shutdown_sessions)
