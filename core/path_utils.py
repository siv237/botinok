#!/usr/bin/env python3
"""Разрешение пользовательских путей инструментов относительно сессии.

Единая точка правды, чтобы не расходились `code_editor`, `file_system` и TUI.
"""

import os
from typing import Optional

PROJECT_SUBDIR = "project"


def install_root() -> str:
    """Корень установки ботинка (папка с ``botinok.py``).

    Нужен инструментам-плагинам: модуль плагина лежит в своей папке
    (``tools/<name>/__init__.py``), поэтому ``dirname(__file__)/..`` больше не
    указывает на корень — только на ``tools/``. Ходим вверх до маркера
    установки, чтобы путь не зависел от глубины папки плагина.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.dirname(here)          # core/ → корень установки
    for _ in range(4):
        if os.path.isfile(os.path.join(candidate, "botinok.py")):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return os.path.dirname(here)


def resolve_session_path(raw_path: str, session_path: Optional[str]) -> str:
    """Резолвит путь для инструментов, работающих с папкой сессии.

    - абсолютный путь — как есть (`realpath`);
    - относительный при наличии `session_path` — в `<session>/project/`,
      при этом ведущий сегмент `project/` **не дублируется**
      (ловушка `project/project/…`);
    - иначе — `realpath(raw_path)`.
    """
    if not raw_path:
        return raw_path
    if os.path.isabs(raw_path):
        return os.path.realpath(raw_path)
    if not session_path:
        return os.path.realpath(raw_path)

    project_dir = os.path.join(os.path.realpath(session_path), PROJECT_SUBDIR)
    rel = raw_path.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    parts = rel.split("/")
    if parts and parts[0] == PROJECT_SUBDIR:
        parts = parts[1:]
    rel = "/".join(parts)
    return os.path.realpath(os.path.join(project_dir, rel))
