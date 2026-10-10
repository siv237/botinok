#!/usr/bin/env python3
"""
web_jobs — реестр фоновых веб-задач (параллельность для `web`).

Обычный вызов `web` остаётся синхронным и последовательным. Когда агент
явно просит `background=true`, задача уходит в отдельный тред, а агент
получает короткий `job_id` сразу и может:
  • запустить пачку таких задач одним ходом;
  • опросить их (`web action=jobs` / `action=job`) — увидеть, что готово,
    а что ещё идёт (прогресс/проценты);
  • получить инкрементное уведомление о завершении/сбое в размышления.

По образцу ShellSessionRegistry: одиночка, живёт в процессе, тредобезопасен.
"""

import threading
import time
import uuid
from typing import Callable, Dict, List, Optional

# Статусы задачи
RUNNING = "running"
DONE = "done"
ERROR = "error"


class WebJob:
    """Одна фоновая веб-задача."""

    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, name: str, action: str, args_preview: str = "") -> None:
        with WebJob._seq_lock:
            WebJob._seq += 1
            n = WebJob._seq
        self.job_id = f"w{n:03d}-{uuid.uuid4().hex[:6]}"
        self.name = (name or "").strip() or f"{action}-{n}"
        self.action = action
        self.args_preview = args_preview
        self.status = RUNNING
        self.progress = ""
        self.result: Optional[str] = None
        self.error: Optional[str] = None
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.notified = False
        self.cancelled = False
        self._lock = threading.Lock()
        self._done = threading.Event()

    # -- обновление из рабочего треда ------------------------------------
    def set_progress(self, text: str = "", **_kw) -> None:
        if text:
            with self._lock:
                self.progress = str(text)

    def finish(self, result: Optional[str] = None, error: Optional[str] = None) -> None:
        with self._lock:
            if self.cancelled:
                return
            self.status = ERROR if error else DONE
            self.result = result
            self.error = error
            self.finished_at = time.time()
        self._done.set()

    def kill(self) -> bool:
        """Пометить задачу убитой (best-effort: тред-воркер завершится сам)."""
        with self._lock:
            if self.status in (DONE, ERROR):
                return False
            self.cancelled = True
            self.status = ERROR
            self.error = "убита пользователем (kill)"
            self.finished_at = time.time()
        self._done.set()
        return True

    # -- чтение из UI/агента ---------------------------------------------
    def is_running(self) -> bool:
        return self.status == RUNNING

    def wait(self, timeout: float) -> bool:
        return self._done.wait(timeout)

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = (self.finished_at or time.time()) - self.started_at
            return {
                "job_id": self.job_id,
                "name": self.name,
                "action": self.action,
                "args": self.args_preview,
                "status": self.status,
                "progress": self.progress,
                "elapsed": round(elapsed, 1),
                "has_result": bool(self.result),
                "result_len": len(self.result) if self.result else 0,
                "result_preview": (self.result or "")[:400],
                "error": self.error,
            }


class WebJobRegistry:
    """Одиночка: хранит фоновые веб-задачи, чтобы агент и UI обращались к ним."""

    _instance: Optional["WebJobRegistry"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._jobs: Dict[str, WebJob] = {}
        self._order: List[str] = []
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "WebJobRegistry":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -- создание --------------------------------------------------------
    def submit(self, name: str, action: str, run: Callable[[Callable], str],
               args_preview: str = "") -> WebJob:
        """Завести задачу и запустить `run(progress_cb)` в daemon-треде.

        `run` возвращает строку-результат; исключение превращается в error.
        """
        job = WebJob(name, action, args_preview)
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            self._cleanup_locked()

        def _worker():
            try:
                res = run(job.set_progress)
                job.finish(result=res)
            except Exception as e:  # noqa: BLE001
                job.finish(error=f"{type(e).__name__}: {e}")

        threading.Thread(target=_worker, name=f"webjob-{job.job_id}", daemon=True).start()
        return job

    # -- чтение ----------------------------------------------------------
    def get(self, job_id: str) -> Optional[WebJob]:
        if not job_id:
            return None
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> List[dict]:
        with self._lock:
            return [self._jobs[jid].snapshot() for jid in self._order if jid in self._jobs]

    def running(self) -> List[dict]:
        return [s for s in self.list() if s["status"] == RUNNING]

    def has_running(self) -> bool:
        with self._lock:
            return any(self._jobs[jid].is_running() for jid in self._order
                       if jid in self._jobs)

    # -- инкрементные уведомления ----------------------------------------
    def drain_notifications(self) -> List[dict]:
        """Завершённые задачи, о которых агент ещё не слышал (однократно)."""
        out: List[dict] = []
        with self._lock:
            for jid in self._order:
                job = self._jobs.get(jid)
                if job is None:
                    continue
                if job.status in (DONE, ERROR) and not job.notified:
                    job.notified = True
                    out.append(job.snapshot())
        return out

    # -- уборка ----------------------------------------------------------
    def _cleanup_locked(self, max_done: int = 40, max_age: float = 3600.0) -> None:
        done_ids = [jid for jid in self._order
                    if jid in self._jobs and self._jobs[jid].status in (DONE, ERROR)]
        if len(done_ids) <= max_done:
            return
        # удаляем самые старые завершённые сверх лимита
        for jid in done_ids[:len(done_ids) - max_done]:
            self._jobs.pop(jid, None)
            if jid in self._order:
                self._order.remove(jid)

    def cleanup_old(self, max_age: float = 3600.0) -> None:
        with self._lock:
            stale = [jid for jid in self._order
                     if jid in self._jobs
                     and self._jobs[jid].status in (DONE, ERROR)
                     and (time.time() - (self._jobs[jid].finished_at or 0)) > max_age]
            for jid in stale:
                self._jobs.pop(jid, None)
                if jid in self._order:
                    self._order.remove(jid)

    def clear(self) -> None:
        """Только для тестов: сбросить всё."""
        with self._lock:
            self._jobs.clear()
            self._order.clear()


def format_notifications() -> str:
    """Инкрементная сводка для модели: завершённые (один раз) + висящие задачи.

    Пустая строка — сообщать нечего. Вызывается харнесом на границах раундов:
    агент «помнит» о задачах, получает ✅/❌ по мере завершения и напоминание
    о тех, что ещё идут.
    """
    try:
        reg = WebJobRegistry.instance()
        events = reg.drain_notifications()
        running = reg.running()
    except Exception:
        return ""
    if not events and not running:
        return ""
    lines = ["🌐 WEB-ЗАДАЧИ (фон):"]
    for s in events:
        if s["status"] == DONE:
            lines.append(f"✅ готова «{s['name']}» (job_id={s['job_id']}) — "
                         f"забери: web action=job job_id={s['job_id']}")
        else:
            lines.append(f"❌ «{s['name']}» (job_id={s['job_id']}): {s['error']}; "
                         f"детали: web action=job job_id={s['job_id']}")
    if running:
        parts = []
        for s in running:
            p = f"«{s['name']}» job_id={s['job_id']}"
            if s["progress"]:
                p += f" {s['progress']}"
            p += f" · {s['elapsed']}s"
            parts.append(p)
        lines.append("⏳ ещё в работе: " + "; ".join(parts))
        lines.append("Опрос: web action=jobs. Не считай эти задачи готовыми, "
                     "пока не придёт ✅.")
    return "\n".join(lines)
