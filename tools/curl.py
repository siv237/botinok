#!/usr/bin/env python3
"""
curl — legacy-обёртка над единым веб-добывателем `tools/web.py`.

Сохраняет прежнюю сигнатуру (включая `jq_filter`) и делегирует в web:
  * `jq_filter`   → web action=json (проекция JSON);
  * `output_path` → web action=download (сохранить в файл);
  * иначе         → web action=auto (по content-type).

Поддерживает HTTP-методы и тело запроса (POST/PUT/PATCH/DELETE), чтобы работать
с веб-API в обычном (неопасном) режиме. Новый код должен использовать `web`.
"""

from tools import web as _web


def execute(
    url: str,
    output_path: str = None,
    timeout_sec: int = 30,
    max_bytes: int = 5_000_000,
    follow_redirects: bool = True,
    headers: list = None,
    session_path: str = None,
    jq_filter: str = None,
    method: str = "GET",
    body: str = None,
    data=None,
    json_body=None,
    resume: bool = False,
    expected_sha256: str = None,
    progress_callback=None,
) -> str:
    """HTTP-запрос через единый web-кит (обратная совместимость)."""
    if jq_filter:
        action = "json"
    elif output_path:
        action = "download"
    else:
        action = "auto"
    return _web.execute(
        url=url,
        action=action,
        jq=jq_filter,
        output_path=output_path,
        timeout_sec=timeout_sec,
        max_bytes=max_bytes,
        follow_redirects=follow_redirects,
        headers=headers,
        session_path=session_path,
        method=method,
        body=body,
        data=data,
        json_body=json_body,
        resume=resume,
        expected_sha256=expected_sha256,
    )


# Alias для совместимости с системным вызовом
curl = execute


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(execute(url=sys.argv[1]))
    else:
        print("Usage: python3 curl.py <url>")
