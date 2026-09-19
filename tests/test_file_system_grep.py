#!/usr/bin/env python3
"""
Тест grep/search в `tools/file_system.py`.

Регрессии из живой сессии 20260919_090557:
  * grep по пути-ФАЙЛУ возвращал «Совпадений не найдено» (glob file/*);
  * grep не поддерживал regex (искал литерал `^## `, `3\\.8`, `a|b`);
  * grep с `pattern` вместо `content_query` падал «content_query обязателен»;
  * `search` с content_query просто перечислял все файлы.

Проверяем: grep по файлу/каталогу, regex и fallback на текст, рекурсию,
регистронезависимость (в т.ч. кириллица), алиас pattern→запрос, search+content.

Запуск: venv/bin/python -u tests/test_file_system_grep.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.file_system import file_system_tool as fs  # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


def _mk() -> str:
    d = tempfile.mkdtemp(prefix="botinok_fs_")
    with open(os.path.join(d, "manual.md"), "w", encoding="utf-8") as f:
        f.write("# Title\n## Section One\nQwen3.8-27B model\nVRAM 24GB\nПривет мир\n")
    with open(os.path.join(d, "code.py"), "w", encoding="utf-8") as f:
        f.write("def foo():\n    pass\n")
    sub = os.path.join(d, "sub")
    os.makedirs(sub, exist_ok=True)
    with open(os.path.join(sub, "deep.txt"), "w", encoding="utf-8") as f:
        f.write("needle in subdir\n")
    return d


def test_grep_file_literal() -> None:
    print("-- grep по файлу (текст) --")
    d = _mk()
    p = os.path.join(d, "manual.md")
    r = fs(action="grep", path=p, content_query="VRAM")
    check("file_literal_found", "manual.md" in r and "VRAM" in r, r[:150])
    check("file_literal_header", "Найдено совпадений" in r, r[:80])
    r = fs(action="grep", path=p, content_query="NOT_present_xyz")
    check("file_literal_empty", "Совпадений не найдено" in r and "1 файл" in r, r[:150])


def test_grep_regex() -> None:
    print("-- grep regex --")
    d = _mk()
    p = os.path.join(d, "manual.md")
    r = fs(action="grep", path=p, content_query=r"^## ")
    check("regex_heading", "Section One" in r, r[:150])
    r = fs(action="grep", path=p, content_query=r"Qwen3\.8")
    check("regex_escaped_dot", "Qwen3.8" in r, r[:150])
    r = fs(action="grep", path=p, content_query="Title|VRAM")
    check("regex_alternation", "Title" in r and "VRAM" in r, r[:200])


def test_grep_fallback_literal() -> None:
    print("-- grep fallback при некорректном regex --")
    d = _mk()
    p = os.path.join(d, "manual.md")
    with open(p, "a", encoding="utf-8") as f:
        f.write("bad ( paren\n")
    r = fs(action="grep", path=p, content_query="( paren")
    check("bad_regex_fallback", "bad ( paren" in r and "как текст" in r, r[:200])


def test_grep_directory_and_recursive() -> None:
    print("-- grep каталога / рекурсия --")
    d = _mk()
    r = fs(action="grep", path=d, content_query="needle")
    check("non_recursive_miss", "Совпадений не найдено" in r, r[:150])
    r = fs(action="grep", path=d, content_query="needle", recursive=True)
    check("recursive_found", "deep.txt" in r and "needle in subdir" in r, r[:200])
    r = fs(action="grep", path=d, content_query="pass", pattern="*.py", recursive=True)
    check("glob_mask", "code.py" in r and "manual.md" not in r, r[:200])


def test_grep_cyrillic_case() -> None:
    print("-- регистронезависимость (кириллица) --")
    d = _mk()
    p = os.path.join(d, "manual.md")
    r = fs(action="grep", path=p, content_query="привет")
    check("cyrillic_case", "Привет мир" in r, r[:150])


def test_pattern_as_query_alias() -> None:
    print("-- pattern вместо content_query (прощающий ввод) --")
    d = _mk()
    p = os.path.join(d, "manual.md")
    r = fs(action="grep", path=p, pattern="VRAM")
    check("pattern_alias", "VRAM" in r and "Found" not in r, r[:150])


def test_search_with_content() -> None:
    print("-- search с content_query ищет по содержимому --")
    d = _mk()
    r = fs(action="search", path=d, content_query="Qwen3")
    check("search_content", "manual.md" in r and "Qwen3" in r, r[:150])
    r = fs(action="search", path=d, pattern="*.py")
    check("search_by_name", "code.py" in r and "manual.md" not in r, r[:150])


def test_missing_and_max() -> None:
    print("-- отсутствующий путь / лимит --")
    r = fs(action="grep", path="/nope/none", content_query="x")
    check("missing_path", "не существует" in r, r[:120])
    d = _mk()
    big = os.path.join(d, "big.txt")
    with open(big, "w", encoding="utf-8") as f:
        for i in range(100):
            f.write(f"match line {i}\n")
    r = fs(action="grep", path=big, content_query="match", max_results=3)
    check("max_results", "Найдено совпадений: 3" in r and "увеличь max_results" in r, r[:120])


def main() -> int:
    print("=" * 70)
    print("file_system grep/search test")
    print("=" * 70)
    test_grep_file_literal()
    test_grep_regex()
    test_grep_fallback_literal()
    test_grep_directory_and_recursive()
    test_grep_cyrillic_case()
    test_pattern_as_query_alias()
    test_search_with_content()
    test_missing_and_max()
    print("=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ file_system grep/search: все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
