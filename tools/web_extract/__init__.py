#!/usr/bin/env python3
"""
web_extract — legacy-обёртка над единым веб-добывателем `tools/web.py`.

Делегирует в web action=extract (структурированное извлечение:
links / images / headings / meta / tables). Новый код должен использовать `web`.
"""

from typing import List

from tools import web as _web


def execute(
    url: str,
    extract: List[str] = None,
    max_items: int = 100,
    timeout_sec: int = 15,
    headers: List[str] = None,
    session_path: str = None,
    progress_callback=None,
) -> str:
    """Структурированное извлечение через единый web-кит."""
    return _web.execute(
        url=url,
        action="extract",
        extract=extract,
        max_items=max_items,
        timeout_sec=timeout_sec,
        headers=headers,
        session_path=session_path,
        progress_callback=progress_callback,
    )


# Alias для совместимости
web_extract = execute


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
        extract = sys.argv[2:] if len(sys.argv) > 2 else ["all"]
        print(execute(url=url, extract=extract))
    else:
        print("Usage: python3 web_extract.py <url> [extract_types...]")
