#!/usr/bin/env python3
"""Интеграция «от и до»: что харнес реально кладёт в payload модели.

Проверяется боевой путь `botinok.ask_ollama_stealth` (CLI/stealth): набор
инструментов в запросе = результат сканирования папок `tools/` (плагины),
без рукописных таблиц. Убрали папку — инструмента нет в payload; положили
папку — появился, в том числе без перезапуска процесса.

Сетевой запрос перехватывается (payload сохраняется, ответ — заглушка),
чтобы проверка была детерминированной и без LLM-сервера.

Запуск: venv/bin/python -u tests/test_tool_payload_integration.py
        venv/bin/python -m pytest tests/test_tool_payload_integration.py -q
"""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import botinok                                 # noqa: E402
from core import tool_discovery as td          # noqa: E402
from core.session_manager import SessionManager  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class FakeResponse:
    """Минимальный поток Ollama: один текстовый чанк и done."""

    def __init__(self):
        self.status_code = 200

    def iter_lines(self):
        yield json.dumps({"message": {"role": "assistant", "content": "ок"},
                          "done": True}).encode("utf-8")

    def close(self):
        pass


def make_plugin(tools_dir: str, folder: str) -> str:
    path = os.path.join(tools_dir, folder)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "tool.json"), "w", encoding="utf-8") as f:
        json.dump({"description": "тестовый плагин"}, f, ensure_ascii=False)
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
        f.write("# probe\n")
    with open(os.path.join(path, "__init__.py"), "w", encoding="utf-8") as f:
        f.write('def execute(action="run"):\n    return "ok"\n')
    return path


def stealth_payload(session_path: str) -> dict:
    """Прогнать stealth-ход с перехватом payload (без сети)."""
    captured = {}

    def fake_post(url, json=None, **kwargs):  # noqa: A002 — имя как в requests
        captured["payload"] = json
        return FakeResponse()

    original = botinok.requests.post
    botinok.requests.post = fake_post
    try:
        botinok.ask_ollama_stealth(
            "probe-model",
            [{"role": "user", "content": "привет"}],
            session_path, 1, num_ctx=2048)
    finally:
        botinok.requests.post = original
    return captured.get("payload") or {}


def tool_names(payload: dict) -> set:
    return {((t or {}).get("function") or {}).get("name")
            for t in (payload.get("tools") or [])}


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="bt_payload_")
    tools_dir = os.path.join(tmp, "tools")
    os.makedirs(tools_dir)
    old_tools_env = os.environ.get("BOTINOK_TOOLS_DIR")
    old_sess_env = os.environ.get("BOTINOK_SESSIONS_DIR")
    os.environ["BOTINOK_TOOLS_DIR"] = tools_dir
    os.environ["BOTINOK_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
    td.clear_cache()
    try:
        sm = SessionManager()
        session = sm.create_session("plugin-payload")

        print("\n[1] stealth: payload = только подключённые плагины")
        path = make_plugin(tools_dir, "probe")
        names = tool_names(stealth_payload(session))
        check("plugin_in_payload", names == {"probe"}, str(names))

        print("\n[2] папка удалена — инструмента в payload нет")
        shutil.rmtree(path)
        names = tool_names(stealth_payload(session))
        check("removed_from_payload", names == set(), str(names))

        print("\n[3] папка вернулась — инструмент снова в payload (без перезапуска)")
        make_plugin(tools_dir, "probe")
        names = tool_names(stealth_payload(session))
        check("restored_in_payload", names == {"probe"}, str(names))

        print("\n[4] папка, добавленная на лету, попадает в payload следующего хода")
        make_plugin(tools_dir, "later")
        names = tool_names(stealth_payload(session))
        check("hot_added_in_payload", names == {"probe", "later"}, str(names))

        print("\n[5] реальная установка: payload = ровно рабочие инструменты")
        os.environ.pop("BOTINOK_TOOLS_DIR", None)
        td.clear_cache()
        session2 = sm.create_session("plugin-payload-real")
        names = tool_names(stealth_payload(session2))
        check("real_tools_in_payload", names == {
            "audio", "code_editor", "curl", "experience", "file_system", "github",
            "image", "journal", "open_url", "session_memory", "shell_exec",
            "sign_step", "skills", "tools", "vision", "web", "web_extract",
            "web_search"}, str(sorted(names)))
        check("aliases_not_in_payload", "web_extractor" not in names, str(sorted(names)))
    finally:
        if old_tools_env is None:
            os.environ.pop("BOTINOK_TOOLS_DIR", None)
        else:
            os.environ["BOTINOK_TOOLS_DIR"] = old_tools_env
        if old_sess_env is None:
            os.environ.pop("BOTINOK_SESSIONS_DIR", None)
        else:
            os.environ["BOTINOK_SESSIONS_DIR"] = old_sess_env
        td.clear_cache()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ PAYLOAD-ИНТЕГРАЦИЯ ПРОЙДЕНА")
    return 0


def test_tool_payload_integration() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
