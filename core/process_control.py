#!/usr/bin/env python3
"""
Единый контроль запущенных процессов и мгновенная остановка.

Зачем: инструменты (aria2c, jq, lynx, safe_ops, shell) запускают дочерние
процессы через `subprocess.run`, который блокирует поток и не прерывается по
Esc. Здесь — общий реестр процессов и `stop_event`: по запросу остановки все
зарегистрированные процессы (вместе с их группами) убиваются, а `run()`
возвращает управление сразу.

Использование:
    from core import process_control as pc
    cp = pc.run(["aria2c", ...], timeout=..., capture_output=True, text=True)
    if pc.stop_requested(): ...
"""

import os
import signal
import subprocess
import threading
import time
from typing import List, Optional

_lock = threading.Lock()
_procs = set()
_stop = threading.Event()


# --------------------------------------------------------------------------
# Флаг остановки
# --------------------------------------------------------------------------

def stop_requested() -> bool:
    return _stop.is_set()


def clear_stop() -> None:
    _stop.clear()


def request_stop() -> None:
    _stop.set()
    kill_all()


# --------------------------------------------------------------------------
# Реестр процессов
# --------------------------------------------------------------------------

def register(proc: subprocess.Popen) -> None:
    with _lock:
        _procs.add(proc)


def unregister(proc: subprocess.Popen) -> None:
    with _lock:
        _procs.discard(proc)


def _signal(proc: subprocess.Popen, sig) -> None:
    try:
        if proc.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), sig)
                return
            except Exception:
                pass
        proc.send_signal(sig)
    except Exception:
        pass


def kill_all(grace: float = 2.0) -> None:
    """Убить все зарегистрированные процессы (группами), затем добить."""
    with _lock:
        procs = list(_procs)
    for p in procs:
        _signal(p, signal.SIGTERM)
    deadline = time.time() + grace
    for p in procs:
        try:
            remaining = max(0.05, deadline - time.time())
            p.wait(timeout=remaining)
        except Exception:
            _signal(p, signal.SIGKILL)


def terminate(proc: subprocess.Popen) -> None:
    _signal(proc, signal.SIGTERM)
    try:
        proc.wait(timeout=1)
    except Exception:
        _signal(proc, signal.SIGKILL)


# --------------------------------------------------------------------------
# Прерываемый запуск
# --------------------------------------------------------------------------

def run(argv: List[str], timeout: Optional[float] = None, cwd: Optional[str] = None,
        env: Optional[dict] = None, input: Optional[str] = None,
        capture_output: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    """Как subprocess.run, но прерывается по request_stop() и регистрируется."""
    kwargs = dict(cwd=cwd, env=env, text=text)
    if os.name == "posix":
        kwargs["start_new_session"] = True  # своя группа → убьём всё дерево
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if input is not None:
        kwargs["stdin"] = subprocess.PIPE
    proc = subprocess.Popen(argv, **kwargs)
    register(proc)
    out = err = None
    try:
        if input is not None:
            # communicate с input нельзя вызывать повторно — шлём и ждём в потоке.
            result = {}

            def _worker():
                try:
                    result["out"], result["err"] = proc.communicate(input=input)
                except Exception as e:  # pragma: no cover
                    result["error"] = e

            th = threading.Thread(target=_worker, daemon=True)
            th.start()
            deadline = time.time() + timeout if timeout else None
            while th.is_alive():
                if _stop.is_set():
                    terminate(proc)
                    break
                if deadline and time.time() > deadline:
                    terminate(proc)
                    th.join(timeout=1)
                    raise subprocess.TimeoutExpired(argv, timeout)
                th.join(timeout=0.1)
            th.join(timeout=1)
            if "error" in result:
                raise result["error"]
            out, err = result.get("out"), result.get("err")
        else:
            out, err = _wait_with_stop(proc, timeout, argv)
    finally:
        unregister(proc)
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _wait_with_stop(proc: subprocess.Popen, timeout: Optional[float], argv):
    deadline = time.time() + timeout if timeout else None
    while True:
        try:
            return proc.communicate(timeout=0.1)
        except subprocess.TimeoutExpired:
            if _stop.is_set():
                terminate(proc)
                return proc.communicate()
            if deadline and time.time() > deadline:
                terminate(proc)
                raise subprocess.TimeoutExpired(argv, timeout)


def stop_and_clear() -> None:
    request_stop()
