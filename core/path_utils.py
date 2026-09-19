#!/usr/bin/env python3
"""Разрешение пользовательских путей инструментов относительно сессии.

Единая точка правды, чтобы не расходились `code_editor`, `file_system` и TUI.
"""

import os
from typing import Optional

PROJECT_SUBDIR = "project"


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
