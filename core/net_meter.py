# -*- coding: utf-8 -*-
"""Учёт сырого обмена с сервером модели: «АПИ отдано» и «АПИ принято».

Считаем ТОЛЬКО трафик к серверам моделей (Ollama / OpenAI-совместимым):
чат, список моделей, проверка памяти, выгрузка модели. Интернет-инструменты
(httpx: web/vision/audio) в эти цифры не входят — у них отдельный мир.

Перехват ставится один раз на уровне HTTP-адаптера `requests`, поэтому
покрываются ВСЕ обращения к модели, включая вызовы инструментов: они летят
внутри того же чат-запроса, отдельно считать их не нужно.

Счётчики потокобезопасны: запросы идут из рабочего потока, а панель читает
их из UI-потока.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict

_lock = threading.Lock()

_sent_turn = 0
_recv_turn = 0
_sent_total = 0
_recv_total = 0
_req_turn = 0
_req_total = 0

# Опорные точки (время, накопленный приём) для расчёта живой скорости.
_recv_samples: "deque[tuple[float, int]]" = deque(maxlen=256)


def format_bytes(n) -> str:
    """Человекочитаемый объём: Б → КБ → МБ."""
    try:
        n = float(n)
    except Exception:
        return "0 КБ"
    if n < 1024:
        return f"{n:.0f} Б"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} КБ"
    return f"{n / (1024 * 1024):.2f} МБ"


def add_sent(n: int) -> None:
    global _sent_turn, _sent_total
    if not n or n <= 0:
        return
    with _lock:
        _sent_turn += n
        _sent_total += n


def add_recv(n: int) -> None:
    global _recv_turn, _recv_total
    if not n or n <= 0:
        return
    now = time.time()
    with _lock:
        _recv_turn += n
        _recv_total += n
        _recv_samples.append((now, _recv_total))


def add_request() -> None:
    global _req_turn, _req_total
    with _lock:
        _req_turn += 1
        _req_total += 1


def reset_turn() -> None:
    """Сброс счётчиков «за текущий запрос» (сессионные не трогаем)."""
    global _sent_turn, _recv_turn, _req_turn
    with _lock:
        _sent_turn = 0
        _recv_turn = 0
        _req_turn = 0


def recv_rate(window: float = 3.0, max_gap: float = 1.0) -> float:
    """Средняя скорость приёма, байт/с, без учёта пауз.

    В знаменатель попадают только интервалы между данными (gap ≤ max_gap).
    Долгий простой не «размазывает» и не занижает скорость: пока данные не
    идут, скорость просто не считается.
    """
    now = time.time()
    with _lock:
        samples = list(_recv_samples)
    recent = [(t, c) for t, c in samples if now - t <= window]
    if len(recent) < 2:
        return 0.0
    bytes_sum = recent[-1][1] - recent[0][1]
    active = 0.0
    for (t0, _), (t1, _) in zip(recent, recent[1:]):
        gap = t1 - t0
        if 0 < gap <= max_gap:
            active += gap
    if active <= 0:
        return 0.0
    return bytes_sum / active


def snapshot() -> Dict[str, int]:
    with _lock:
        return {
            "sent_turn": _sent_turn,
            "recv_turn": _recv_turn,
            "sent_total": _sent_total,
            "recv_total": _recv_total,
            "req_turn": _req_turn,
            "req_total": _req_total,
        }


class _CountingRaw:
    """Прокси поверх urllib3-ответа: считает фактически прочитанные байты."""

    __slots__ = ("_raw",)

    def __init__(self, raw):
        self._raw = raw

    @staticmethod
    def _on(data) -> None:
        if data:
            add_recv(len(data))

    def read(self, amt=None, *args, **kwargs):
        data = self._raw.read(amt, *args, **kwargs)
        self._on(data)
        return data

    def stream(self, amt=2 ** 16, decode_content=None):
        try:
            for chunk in self._raw.stream(amt, decode_content=decode_content):
                self._on(chunk)
                yield chunk
        except TypeError:
            for chunk in self._raw.stream(amt):
                self._on(chunk)
                yield chunk

    def __getattr__(self, name):
        return getattr(self._raw, name)


_installed = False


def install() -> None:
    """Один раз оборачиваем HTTP-адаптер requests для подсчёта трафика."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        import requests
        from requests.adapters import HTTPAdapter
    except Exception:
        return
    orig_send = HTTPAdapter.send

    def metered_send(self, request, **kwargs):
        try:
            body = request.body
            if isinstance(body, (bytes, bytearray)):
                add_sent(len(body))
            elif isinstance(body, str):
                add_sent(len(body.encode("utf-8", "ignore")))
            elif body is not None:
                add_sent(len(str(body).encode("utf-8", "ignore")))
        except Exception:
            pass
        add_request()
        resp = orig_send(self, request, **kwargs)
        try:
            resp.raw = _CountingRaw(resp.raw)
        except Exception:
            pass
        return resp

    try:
        HTTPAdapter.send = metered_send
    except Exception:
        pass


install()
