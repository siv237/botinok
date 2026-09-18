#!/usr/bin/env python3
"""
web_search — legacy-обёртка над единым веб-добывателем `tools/web.py`.

Делегирует в web action=search (DuckDuckGo HTML, fallback lynx).
Новый код должен использовать `web`.
"""

from tools import web as _web


def ddg_search(query: str, session_path: str = None) -> str:
    """Поиск в интернете через единый web-кит."""
    return _web.execute(query=query, action="search", session_path=session_path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(ddg_search(sys.argv[1]))
    else:
        print("Usage: python3 web_search.py 'query'")
