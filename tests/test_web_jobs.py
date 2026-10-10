#!/usr/bin/env python3
"""
Smoke-тест фоновых веб-задач (`tools/web_jobs.py` + `web background=true`).

Локальный HTTP-сервер с медленным эндпоинтом; проверяем:
  * обычный (не фоновый) вызов не изменился;
  * background=true возвращает job_id немедленно;
  * action=job — статус во время работы, полный результат после;
  * action=jobs — список;
  * drain/format уведомлений — инкрементные (каждое событие один раз);
  * пачка задач выполняется параллельно;
  * command=kill — пометка убитой задачи;
  * неизвестный job_id — понятная ошибка.

Запуск: venv/bin/python -u tests/test_web_jobs.py
"""

import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import web as web_tool  # noqa: E402
from tools import web_jobs as wj  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/slow"):
            time.sleep(0.7)
            body = json.dumps({"ok": True, "slow": True}).encode()
        else:
            body = json.dumps({"hello": "world", "n": 42}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


JOB_ID_RE = re.compile(r"(w\d+-[0-9a-f]{6})")


def main() -> int:
    reg = wj.WebJobRegistry.instance()
    reg.clear()
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        # 1. Обычный вызов — как раньше (синхронно).
        out = web_tool.execute(url=f"{base}/data", action="json")
        check("sync_still_works", "hello" in out, out[:200])

        # 2. Фоновый запуск возвращается мгновенно.
        t0 = time.time()
        out = web_tool.execute(url=f"{base}/slow", action="json",
                               background=True, name="долгий")
        dt = time.time() - t0
        check("bg_returns_fast", dt < 0.3, f"{dt:.2f}s")
        m = JOB_ID_RE.search(out)
        check("bg_has_job_id", bool(m), out[:200])
        if not m:
            raise AssertionError("нет job_id в ответе запуска")
        jid = m.group(1)

        # 3. Во время работы — статус running, не результат.
        out = web_tool.execute(action="job", job_id=jid)
        check("job_running_status", "выполняется" in out, out[:200])

        # 4. Дождаться завершения.
        job = reg.get(jid)
        check("job_finishes", job is not None and job.wait(5), "timeout")

        # 5. action=job — полный результат задачи.
        out = web_tool.execute(action="job", job_id=jid)
        check("job_done_result", "slow" in out and "результат" in out, out[:300])

        # 6. action=jobs — список со статусами.
        out = web_tool.execute(action="jobs")
        check("jobs_lists", jid in out and "долгий" in out, out[:300])

        # 7. Уведомления инкрементные: событие отдаётся один раз.
        note = wj.format_notifications()
        check("notify_has_done", "готова" in note and "долгий" in note, note[:300])
        note2 = wj.format_notifications()
        check("notify_incremental", note2 == "", repr(note2[:120]))

        # 8. Пачка из 3 медленных задач — параллельно (< 2.1с последовательных).
        t0 = time.time()
        ids = []
        for i in range(3):
            out = web_tool.execute(url=f"{base}/slow", action="json",
                                   background=True, name=f"пакет{i}")
            mm = JOB_ID_RE.search(out)
            check(f"batch_launch_{i}", bool(mm), out[:150])
            if mm:
                ids.append(mm.group(1))
        for j in ids:
            reg.get(j).wait(10)
        dt = time.time() - t0
        check("parallel_batch", dt < 2.0, f"{dt:.2f}s (последовательно было бы ≥2.1s)")

        # 9. kill — задача помечается убитой.
        out = web_tool.execute(url=f"{base}/slow", action="json",
                               background=True, name="убей")
        mm = JOB_ID_RE.search(out)
        jid2 = mm.group(1)
        out = web_tool.execute(action="job", job_id=jid2, command="kill")
        check("kill_works", "убита" in out, out[:200])

        # 10. Неизвестный job_id.
        out = web_tool.execute(action="job", job_id="w999-zzzzzz")
        check("unknown_job_error", "не найдена" in out, out[:200])

        # 11. Фоновый поиск без url/query — ошибка сразу, тред не заводится.
        out = web_tool.execute(action="search", background=True, name="пусто")
        check("bg_requires_target", "url или query" in out, out[:200])
    finally:
        httpd.shutdown()
        httpd.server_close()
        reg.clear()

    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ WEB JOBS SMOKE-ТЕСТ ПРОЙДЕН")
    return 0


def test_web_jobs():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
