#!/usr/bin/env python3
"""
Регрессия: 100% восстановимость сессии.

Проверяет, что сохраняемые данные достаточны для точной пересборки диалога:
  * tool_call_id сохраняется в tool-записях и в tools.log;
  * пары assistant.tool_calls ↔ tool-результат не теряются;
  * подряд идущие одинаковые записи дедуплицируются;
  * канонический снапшот messages.json сохраняется и восстанавливается,
    включая медиа (выносится в artifacts и рехидратируется);
  * log_step не затирает шаг с тем же именем.

Запуск: venv/bin/python tests/test_session_snapshot.py
или:     venv/bin/python -m pytest tests/test_session_snapshot.py
"""

import base64
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session_manager import SessionManager  # noqa: E402
from tools.session_memory import session_memory_tool  # noqa: E402

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE-IMAGE-BYTES").decode("ascii")


def _new_session(root: str) -> str:
    os.makedirs(os.path.join(root, "artifacts"), exist_ok=True)
    os.makedirs(os.path.join(root, "steps"), exist_ok=True)
    with open(os.path.join(root, "context.json"), "w", encoding="utf-8") as f:
        json.dump({"session_id": "test", "created_at": "now", "history": []}, f)
    return root


def _history(root: str):
    with open(os.path.join(root, "context.json"), "r", encoding="utf-8") as f:
        return json.load(f)["history"]


def test_tool_call_pairing_and_dedupe():
    sm = SessionManager()
    root = _new_session(tempfile.mkdtemp(prefix="botinok_test_"))
    try:
        sm.update_context(root, "user", "привет")
        # точный дубль подряд — должен схлопнуться
        sm.update_context(root, "user", "привет")

        tool_calls = [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "file_system", "arguments": {"action": "list"}},
        }]
        sm.update_context(root, "assistant", "", tool_calls=tool_calls)
        sm.update_context(root, "tool", "TOOL_RESULT_SUMMARY\nresult", 
                          tool_call_id="call_1", name="file_system")
        sm.update_context(root, "assistant", "готово")

        hist = _history(root)
        users = [e for e in hist if e.get("role") == "user"]
        assert len(users) == 1, f"дедупликация не сработала: {len(users)}"
        tool_entries = [e for e in hist if e.get("role") == "tool"]
        assert tool_entries and tool_entries[0].get("tool_call_id") == "call_1"
        assert tool_entries[0].get("name") == "file_system"

        audit = sm.audit_context(root)
        assert audit["tool_calls"] == 1, audit
        assert audit["tool_results_with_id"] == 1, audit
        assert audit["tool_calls_without_result"] == 0, audit

        msgs = sm.load_context_messages(root)
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "tool", "assistant"], roles
        assert msgs[2]["tool_call_id"] == "call_1"
        assert msgs[1]["tool_calls"][0]["id"] == "call_1"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_messages_snapshot_roundtrip_with_media():
    sm = SessionManager()
    root = _new_session(tempfile.mkdtemp(prefix="botinok_test_"))
    try:
        original = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "посмотри картинку",
             "images": [f"data:image/png;base64,{PNG}"]},
            {"role": "assistant", "content": "вижу"},
            {"role": "tool", "content": "ok", "tool_call_id": "call_9", "name": "vision"},
        ]
        path = sm.save_messages_snapshot(root, original, model="test-model", num_ctx=8192)
        assert path and os.path.isfile(path)

        # снапшот на диске не должен содержать сырой base64
        raw = open(path, "r", encoding="utf-8").read()
        assert PNG[:24] not in raw, "медиа не вынесено в artifacts"
        assert "media_ref" in raw

        restored = sm.load_messages_snapshot(root)
        assert restored == original, f"round-trip не совпал:\n{restored}\n!=\n{original}"

        # load_context_messages предпочитает снапшот
        assert sm.load_context_messages(root) == original
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_tools_log_call_id_and_step_collision():
    sm = SessionManager()
    root = _new_session(tempfile.mkdtemp(prefix="botinok_test_"))
    try:
        sm.log_tool_call(root, "shell_exec", {"command": "ls"}, "out", call_id="call_42")
        with open(os.path.join(root, "tools.log"), "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())
        assert entry.get("call_id") == "call_42", entry

        sm.log_step(root, "tool_shell_exec_1", {"id": "a"}, {"result": 1}, {})
        sm.log_step(root, "tool_shell_exec_1", {"id": "b"}, {"result": 2}, {})
        steps = os.listdir(os.path.join(root, "steps"))
        assert "tool_shell_exec_1.json" in steps
        assert "tool_shell_exec_1_1.json" in steps, steps
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_old_session_roundtrip_without_ids_or_snapshot():
    """Старый формат: нет tool_call_id, нет messages.json — но диалог валиден."""
    sm = SessionManager()
    root = _new_session(tempfile.mkdtemp(prefix="botinok_test_"))
    try:
        history = {
            "session_id": "old", "created_at": "old", "history": [
                {"role": "user", "content": "сделай"},
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "old_a", "type": "function",
                     "function": {"name": "file_system", "arguments": {"action": "list"}}},
                    {"id": "old_b", "type": "function",
                     "function": {"name": "shell_exec", "arguments": {"command": "ls"}}},
                ]},
                # старый формат: без tool_call_id, имя есть; это результат old_a
                {"role": "tool", "name": "file_system", "content": "SUMMARY fS"},
                # результат old_b отсутствует в context.json вовсе
                {"role": "assistant", "content": "готово"},
            ],
        }
        with open(os.path.join(root, "context.json"), "w", encoding="utf-8") as f:
            json.dump(history, f)

        # tools.log старого формата (без call_id), порядок намеренно перемешан
        with open(os.path.join(root, "tools.log"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"tool": "shell_exec", "arguments": {"command": "ls"},
                                "full_result": "FULL shell out"}) + "\n")
            f.write(json.dumps({"tool": "file_system", "arguments": {"action": "list"},
                                "full_result": "FULL fs out"}) + "\n")

        msgs = sm.load_context_messages(root)
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "tool", "tool", "assistant"], roles
        assert msgs[2]["tool_call_id"] == "old_a" and msgs[2]["name"] == "file_system"
        assert msgs[3]["tool_call_id"] == "old_b"
        # отсутствующий результат результата old_b подставлен из tools.log
        assert "FULL shell out" in msgs[3]["content"], msgs[3]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_resume_brief_state_and_last_final_answer():
    """Резюме: прерванный ход распознаётся, а последний ответ берётся финальный."""
    sm = SessionManager()
    root = _new_session(tempfile.mkdtemp(prefix="botinok_test_"))
    try:
        history = [
            {"role": "user", "content": "задача"},
            {"role": "assistant", "content": "ФИНАЛЬНЫЙ ОТЧЁТ"},
            {"role": "user", "content": "ещё"},
            # прерванный ход: assistant с tool_calls и без текста
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "shell_exec", "arguments": {"action": "run"}}}]},
        ]
        with open(os.path.join(root, "context.json"), "w", encoding="utf-8") as f:
            json.dump({"session_id": "r", "created_at": "now", "history": history}, f)

        b = sm.build_resume_brief(root)
        assert b["RESUME_STATE"].startswith("прервана"), b["RESUME_STATE"]
        assert b["LAST_ASSISTANT_ANSWER"] == "ФИНАЛЬНЫЙ ОТЧЁТ", b["LAST_ASSISTANT_ANSWER"]
        assert sm.load_last_assistant_answer(root) == "ФИНАЛЬНЫЙ ОТЧЁТ"

        # Добавляем финальный ответ — ход считается завершённым.
        history.append({"role": "assistant", "content": "готово"})
        with open(os.path.join(root, "context.json"), "w", encoding="utf-8") as f:
            json.dump({"session_id": "r", "created_at": "now", "history": history}, f)
        b2 = sm.build_resume_brief(root)
        assert b2["RESUME_STATE"].startswith("завершена"), b2["RESUME_STATE"]
        assert b2["LAST_ASSISTANT_ANSWER"] == "готово", b2["LAST_ASSISTANT_ANSWER"]

        # YAML-метаданные турнов вырезаются из ответа.
        cleaned = SessionManager._clean_answer(
            "```yaml\ntype: BOTINOK_SESSION_METADATA\nstatus: START\n```\n\nтекст")
        assert "BOTINOK_SESSION_METADATA" not in cleaned and "текст" in cleaned
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_exact_restore_and_provenance():
    """restore: EXACT из messages.json, DERIVED из context.json, HIT для поиска."""
    sm = SessionManager()
    root = _new_session(tempfile.mkdtemp(prefix="botinok_test_"))
    try:
        # 1. Без снапшота — derived из context.json.
        sm.update_context(root, "user", "задача")
        sm.update_context(root, "assistant", "ответ")
        out = json.loads(session_memory_tool(
            action="restore", session_path=root, format="json"))
        assert out["exact"] is False and out["source"] == "context.json", out
        assert out["_confidence"] == "DERIVED", out

        # 2. Со снапшотом — exact.
        msgs = [{"role": "user", "content": "задача"}, {"role": "assistant", "content": "ответ"}]
        sm.save_messages_snapshot(root, msgs, model="m", num_ctx=8192)
        out2 = json.loads(session_memory_tool(
            action="restore", session_path=root, format="json"))
        assert out2["exact"] is True and out2["source"] == "messages.json", out2
        assert out2["_confidence"] == "EXACT", out2
        assert out2["messages"] == msgs, out2["messages"]

        # 3. Неизвестное действие — строгая неоднозначность, без подмены.
        amb = json.loads(session_memory_tool(action="блабла", session_path=root))
        assert amb.get("ambiguous") is True and "candidates" in amb, amb

        # 4. Поиск помечается как HINT.
        srch = json.loads(session_memory_tool(
            action="search", query="ответ", session_path=root, format="json"))
        assert srch["_confidence"] == "HINT", srch
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    failures = []
    for name, fn in [
        ("tool_call_pairing_and_dedupe", test_tool_call_pairing_and_dedupe),
        ("messages_snapshot_roundtrip_with_media", test_messages_snapshot_roundtrip_with_media),
        ("tools_log_call_id_and_step_collision", test_tools_log_call_id_and_step_collision),
        ("old_session_roundtrip_without_ids_or_snapshot", test_old_session_roundtrip_without_ids_or_snapshot),
        ("resume_brief_state_and_last_final_answer", test_resume_brief_state_and_last_final_answer),
        ("exact_restore_and_provenance", test_exact_restore_and_provenance),
    ]:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name} — {e}")
            failures.append(name)
        except Exception as e:
            print(f"  [ERROR] {name} — {type(e).__name__}: {e}")
            failures.append(name)
    if failures:
        print(f"\nFAILED: {failures}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
