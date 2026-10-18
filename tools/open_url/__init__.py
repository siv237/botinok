#!/usr/bin/env python3
"""
open_url — legacy-обёртка над единым веб-добывателем `tools/web.py`.

Делегирует в web action=open (читаемый основной текст страницы в markdown).
Новый код должен использовать `web`.
"""

from tools import web as _web


def open_url(url: str, session_path: str = None, progress_callback=None) -> str:
    """Читаемый текст страницы через единый web-кит."""
    target = (url or "").strip()
    if target and "://" not in target:
        target = "https://" + target
    return _web.execute(url=target, action="open", session_path=session_path,
                        progress_callback=progress_callback)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(open_url(sys.argv[1]))
    else:
        print("Usage: python3 open_url.py <url>")
