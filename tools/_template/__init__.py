"""Скелет инструмента-плагина. НЕ подключается: имя папки начинается с ``_``.

Как сделать инструмент:

1. Скопируй папку: ``cp -r tools/_template tools/my_tool``
2. Реализуй :func:`execute` и заполни ``tool.json`` (см. README.md рядом).
3. Запусти ``venv/bin/python -u tests/test_plugin_folders.py`` и
   ``venv/bin/python -m pytest tests/test_plugin_folders.py -q``.

Всё: инструмент появится в каталоге и payload сам (``core/tool_discovery.py``).
Удалишь папку — исчезнет.
"""

from typing import Optional


def execute(query: str = "", action: str = "run",
            session_path: Optional[str] = None) -> str:
    """Короткое описание для модели: что делает и когда звать.

    Первый абзац докстроки становится description автосхемы, если в
    ``tool.json`` нет поля ``description``; аннотации параметров — их типами
    и обязательностью (``required`` = параметры без значения по умолчанию).

    Верни короткий отчёт строкой: что сделано, ключевые факты (путь:строка,
    размер, время) и следующий шаг. Ошибку верни строкой ``Error: …`` с
    причиной — модель прочитает её как результат инструмента.
    """
    if action == "help":
        return "help: run — сделать X; help — эта справка."
    return (f"TODO: реализуй инструмент (query={query!r}, "
            f"session_path={session_path!r})")
