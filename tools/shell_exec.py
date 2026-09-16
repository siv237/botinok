"""
Инструмент shell_exec — «shell как отдельная сессия».

Команда запускается в собственной PTY-сессии (core/shell_session.ShellSession),
которая НЕ держит агента. Агент смотрит «со стороны»:
  * читает вывод порциями (tail) — без выгрузки всего буфера в контекст;
  * ищет по выводу (строка/regex) — чтобы найти промпт/ошибку/пароль;
  * отправляет ввод в ту же сессию, что и пользователь (пароли, пункты меню);
  * запрашивает статус/завершение.

UI: при наличии Textual-приложения поверх экрана открывается встроенный
терминал (core/shell_screen.ShellScreen) — пользователь работает в нём наравне
с агентом. Окно можно свернуть (Ctrl+Q / кнопка «Свернуть») — сессия продолжит
жить и появится в панели свёрнутых терминалов на основном экране; кнопка
«Закрыть» завершает сессию.

Действия (action):
  run      — запустить команду (интерактивно, в PTY). Возвращает session_id + tail.
  status   — состояние сессии + хвост вывода.
  read     — прочитать хвост вывода (tail_lines).
  search   — поиск по выводу (pattern, regex, context).
  send     — отправить текст в сессию (как пользователь набрал + Enter).
  send_key — отправить спец-клавишу (enter, down, y, ctrl-c, ...).
  wait     — дождаться завершения (wait_timeout).
  kill     — прервать сессию.
  list     — список сессий.
"""

import json
import os
import time
from typing import Optional, Dict

from core.shell_session import ShellSession, ShellSessionRegistry

MAX_TAIL_CHARS = 6000


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _tail_for_context(session: ShellSession, tail_lines: int = 40) -> str:
    out = session.get_output(tail_lines=tail_lines)
    if len(out) > MAX_TAIL_CHARS:
        out = out[-MAX_TAIL_CHARS:] + "\n...[TRUNCATED]"
    return out


def _need_session(reg: ShellSessionRegistry, session_id: str) -> Optional[ShellSession]:
    """Достать сессию или None (с_payload уже содержит список доступных)."""
    return reg.get(session_id)


def _ui_push_screen(session: ShellSession, on_done) -> bool:
    """Открыть встроенный экран терминала, если Textual-приложение живо.

    Вызывается из рабочего потока (ботинок выполняет инструменты в
    threading.Thread), где ContextVar active_app НЕ установлен — поэтому
    приложение берём из глобального реестра и пушим экран через
    app.call_from_thread(...), который выполнит код в правильном контексте
    (Textual 8.2). Это единственный рабочий путь, аналогичный ConfirmationScreen.
    """
    app = _active_textual_app()
    if app is None:
        return False

    def _push():
        try:
            # Приложение умеет сам открывать/сворачивать несколько терминалов
            # (см. BotinokTextualApp.open_shell_session). Если его нет —
            # работаем напрямую.
            opener = getattr(app, "open_shell_session", None)
            if callable(opener):
                opener(session)
                return True
            from core.shell_screen import ShellScreen
            app.push_screen(ShellScreen(session=session, on_done=on_done))
            return True
        except Exception:
            return False

    try:
        # Fire-and-forget, как в ConfirmationScreen: блокировать рабочий поток на
        # результате нельзя (можно получить deadlock с UI-циклом). Экран
        # докинется асинхронно в правильном контексте.
        app.call_from_thread(_push)
        return True
    except Exception:
        # Запасной вариант: вдруг вызвали из UI-потока — пушим напрямую.
        try:
            return _push()
        except Exception:
            return False


def _active_textual_app():
    """Текущее Textual-приложение.

    Textual 8.2: приложение хранится в ContextVar `active_app`
    (textual._context), а НЕ в атрибуте класса App. Пробуем по порядку:
      1. глобальный реестр (главный путь — ботинок вызывает инструменты
         в рабочем потоке, где ContextVar не наследуется);
      2. ContextVar (если инструмент вызвали из UI-потока);
      3. атрибут класса (остался от старых версий Textual — для совместимости).
    """
    try:
        from core.shell_session import TextualAppRegistry
        app = TextualAppRegistry.get_app()
        if app is not None:
            return app
    except Exception:
        pass
    try:
        from textual._context import active_app as active_app_ctx
        try:
            return active_app_ctx.get()
        except LookupError:
            pass  # контекст не установлен — приложения нет
    except ImportError:
        pass
    try:
        from textual.app import App
    except Exception:
        return None
    for attr in ("_active_app", "active_app"):
        app = getattr(App, attr, None)
        if app is not None:
            return app
    return None


def shell_exec(
    command: str = "",
    cwd: Optional[str] = None,
    timeout_sec: int = 120,
    action: str = "run",
    session_id: str = "",
    input: str = "",
    key: str = "",
    pattern: str = "",
    regex: bool = False,
    context: int = 0,
    tail_lines: int = 40,
    wait_timeout: float = 10.0,
    interactive: bool = True,
    name: str = "",
    env: Optional[Dict[str, str]] = None,
) -> str:
    """Главная точка входа инструмента shell_exec.

    Возвращает JSON-строку с результатом действия.
    """
    reg = ShellSessionRegistry.instance()
    # Подчищаем давно завершённые сессии, чтобы реестр не рос бесконечно.
    try:
        reg.cleanup_dead()
    except Exception:
        pass

    # ---------------------------------------------------------- run
    if action == "run":
        if not command or not str(command).strip():
            return _result({"error": "command пустой"})
        run_cwd = _project_root() if not cwd else os.path.realpath(cwd)

        session = ShellSession(
            command=command,
            cwd=run_cwd,
            timeout_sec=max(0, int(timeout_sec or 0)),
            name=name or command,
            env=env,
        )
        try:
            session.start()
        except Exception as e:
            # Не оставляем висеть PTY-дескрипторы при неудачном старте.
            try:
                session.close()
            except Exception:
                pass
            return _result({
                "error": f"не удалось запустить команду: {e}",
                "command": command,
                "cwd": run_cwd,
            })
        reg.add(session)

        if interactive:
            # Пытаемся открыть встроенный экран терминала; если UI недоступен
            # (чат-режим без TUI) — работаем как headless-сессия.
            _ui_push_screen(session, on_done=lambda s: None)

            # Небольшая пауза, чтобы агент увидел хотя бы стартовый вывод/промпт.
            session.wait(0.6)
        else:
            session.wait(min(float(timeout_sec or 30), 30.0))

        st = session.status_dict(tail_lines=tail_lines)
        return _result({
            "status": "running" if session.is_running() else "finished",
            "mode": "interactive" if interactive else "batch",
            "session_id": session.session_id,
            "command": session.command,
            "cwd": session.cwd,
            "running": session.is_running(),
            "returncode": session.returncode,
            "elapsed": round(session.elapsed, 2),
            "lines_total": st["lines_total"],
            "output_tail": _tail_for_context(session, tail_lines),
            "hint": (
                "Сессия выполняется в фоне и не держит тебя. Командуй дальше: "
                f"action=status/read/search/send/send_key/wait/kill с session_id={session.session_id}."
            ),
        })

    # ------------------------------------------------------- status/list
    if action == "list":
        items = reg.list()
        return _result({"sessions": items, "count": len(items)})

    if action == "status":
        s = _need_session(reg, session_id)
        if s is None:
            return _result({"error": f"сессия не найдена: {session_id}",
                            "available": reg.list()})
        return _result(s.status_dict(tail_lines=tail_lines))

    # ------------------------------------------------------------ read
    if action == "read":
        s = _need_session(reg, session_id)
        if s is None:
            return _result({"error": f"сессия не найдена: {session_id}",
                            "available": reg.list()})
        return _result({
            "session_id": s.session_id,
            "running": s.is_running(),
            "returncode": s.returncode,
            "lines_total": s.lines_total,
            "output_tail": _tail_for_context(s, tail_lines),
        })

    # ---------------------------------------------------------- search
    if action == "search":
        s = _need_session(reg, session_id)
        if s is None:
            return _result({"error": f"сессия не найдена: {session_id}",
                            "available": reg.list()})
        return _result({
            "session_id": s.session_id,
            "pattern": pattern,
            "matches": s.search_output(
                pattern, regex=regex,
                tail_lines=max(tail_lines, 2000),
                context=context,
            ),
        })

    # ----------------------------------------------------------- send
    if action == "send":
        s = _need_session(reg, session_id)
        if s is None:
            return _result({"error": f"сессия не найдена: {session_id}",
                            "available": reg.list()})
        sent = s.send_input(input)
        time.sleep(0.25)
        return _result({
            "session_id": s.session_id,
            "sent_bytes": sent,
            "input": input,
            "running": s.is_running(),
            "output_tail": _tail_for_context(s, tail_lines),
        })

    # ------------------------------------------------------- send_key
    if action == "send_key":
        s = _need_session(reg, session_id)
        if s is None:
            return _result({"error": f"сессия не найдена: {session_id}",
                            "available": reg.list()})
        sent = s.send_key(key)
        time.sleep(0.25)
        return _result({
            "session_id": s.session_id,
            "sent_bytes": sent,
            "key": key,
            "running": s.is_running(),
            "output_tail": _tail_for_context(s, tail_lines),
        })

    # ------------------------------------------------------------ wait
    if action == "wait":
        s = _need_session(reg, session_id)
        if s is None:
            return _result({"error": f"сессия не найдена: {session_id}",
                            "available": reg.list()})
        done = s.wait(wait_timeout)
        return _result({
            "session_id": s.session_id,
            "finished": done,
            "running": s.is_running(),
            "returncode": s.returncode,
            "elapsed": round(s.elapsed, 2),
            "output_tail": _tail_for_context(s, tail_lines),
        })

    # ------------------------------------------------------------ kill
    if action == "kill":
        s = _need_session(reg, session_id)
        if s is None:
            return _result({"error": f"сессия не найдена: {session_id}",
                            "available": reg.list()})
        s.kill()
        s.wait(3)
        return _result({
            "session_id": s.session_id,
            "killed": True,
            "running": s.is_running(),
            "returncode": s.returncode,
            "output_tail": _tail_for_context(s, tail_lines),
        })

    return _result({
        "error": f"неизвестное действие: {action}",
        "available_actions": ["run", "status", "read", "search", "send",
                              "send_key", "wait", "kill", "list"],
    })
