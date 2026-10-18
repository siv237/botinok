#!/usr/bin/env python3
"""Регрессии переезда инструментов в папки-плагины (tools/<name>/).

Переезд из плоских `tools/<name>.py` в пакеты `tools/<name>/__init__.py` ломает
всё, что неявно опиралось на расположение файла или на список имён. Этот набор
систематически вскрывает такие поломки:

  1. корень установки: `install_root()` и три боевых потребителя путей
     (skills → вкомпонованные скиллы, web → config.cfg, code_editor → корень проекта);
  2. статический скан плагинов на шаблон «корень через __file__» (так считался бы
     `tools/`) и на смену рабочего каталога;
  3. модульные пути: каждая ссылка `from tools…`/`import tools…` из репозитория
     импортируется, плагины — папки с контрактом, библиотеки — плоские файлы;
  4. контракт каждого плагина: схема, entry-функция, `provides` ⊆ сигнатуры;
  5. smoke-вызовы безопасных действий каждого инструмента (без сети и без
     dangerous mode): не падает и не возвращает «Error calling tool»;
  6. относительные ссылки в сгенерированных README инструментов резолвятся;
  7. git трекает все файлы плагинов (иначе install.sh/update их не доставят);
  8. ссылки на пути инструментов в документации/промптах/тестах актуальны
     (`tools/<name>.py` — только библиотеки, `tools/<name>/` — только плагины;
     CHANGELOG и wiki/log.md — история, не проверяются).

Запуск: venv/bin/python -u tests/test_tool_regressions.py
        venv/bin/python -m pytest tests/test_tool_regressions.py -q
"""

import importlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.path_utils import install_root        # noqa: E402
from core.tool_manager import ToolManager       # noqa: E402
from core import tool_discovery as td           # noqa: E402
from tools import code_editor                   # noqa: E402
from tools import skills as skills_tool         # noqa: E402
from tools import web as web_tool               # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


# --------------------------------------------------------------------------
# 1. Корень установки и пути инструментов
# --------------------------------------------------------------------------

def part_paths() -> None:
    print("\n[1] корень установки и пути инструментов")
    root = install_root()
    check("install_root_has_marker", os.path.isfile(os.path.join(root, "botinok.py")), root)
    check("install_root_is_repo", os.path.realpath(root) == os.path.realpath(ROOT), root)

    # skills: вкомпонованные скиллы лежат в <install>/skills, а не в tools/skills
    bundled = skills_tool.BUNDLED_DIR
    check("skills_bundled_dir",
          os.path.realpath(str(bundled)) == os.path.realpath(os.path.join(root, "skills")),
          str(bundled))
    check("skills_bundled_exists", bundled.is_dir(), str(bundled))
    if bundled.is_dir():
        listed = str(skills_tool.skills(action="list"))
        for item in sorted(bundled.iterdir()):
            check(f"skills_listed_{item.name}", item.name in listed)
            check(f"skills_has_skill_md_{item.name}", (item / "SKILL.md").is_file())
        # find_skill обязан находить вкомпонованный скилл (источник — project,
        # если такой же скилл есть в проекте, иначе bundled)
        name = sorted(p.name for p in bundled.iterdir())[0]
        path, source = skills_tool.find_skill(name)
        check("find_skill_resolves", path is not None and (path / "SKILL.md").is_file(),
              f"{path} / {source}")
        check("find_skill_source_valid", source in ("personal", "project", "bundled"), str(source))

    # web: конфиг [Tools] Lynx* читается из <install>/config.cfg
    cfg_path = os.path.join(root, "config.cfg")
    check("web_config_path_is_root",
          os.path.join(root, "config.cfg") == os.path.join(install_root(), "config.cfg"))
    check("no_stray_tools_config", not os.path.isfile(os.path.join(root, "tools", "config.cfg")))
    if os.path.isfile(cfg_path):
        expected = _read_lynx_ua(cfg_path)
        if expected:
            check("web_reads_install_config", web_tool._config()["user_agent"] == expected,
                  str(web_tool._config())[:120])
            check("web_not_default_ua", web_tool._config()["user_agent"] != web_tool.DEFAULT_UA)

    # code_editor: корень проекта — корень установки, а не tools/
    check("code_editor_root", os.path.realpath(code_editor._project_root()) == os.path.realpath(root),
          code_editor._project_root())
    check("code_editor_root_not_tools",
          os.path.realpath(code_editor._project_root()) != os.path.realpath(os.path.join(root, "tools")),
          code_editor._project_root())


def _read_lynx_ua(cfg_path: str) -> str:
    import configparser
    cp = configparser.ConfigParser()
    try:
        cp.read(cfg_path, encoding="utf-8")
        return cp.get("Tools", "LynxUserAgent", fallback="")
    except Exception:
        return ""


# --------------------------------------------------------------------------
# 2. Статический скан плагинов
# --------------------------------------------------------------------------

_ROOT_BY_FILE = (
    re.compile(r"""dirname\(\s*__file__\s*\)\s*,\s*["']\.\.["']"""),
    re.compile(r"Path\(\s*__file__\s*\)[^\n]*\.parent\.parent"),
    re.compile(r"""os\.path\.dirname\(\s*os\.path\.dirname\(\s*os\.path\.abspath\(\s*__file__"""),
)


def part_static_scan() -> None:
    print("\n[2] статический скан плагинов")
    tools_dir = os.path.join(install_root(), "tools")
    root_offenders, chdir_offenders = [], []
    for entry in sorted(os.listdir(tools_dir)):
        init = os.path.join(tools_dir, entry, "__init__.py")
        if not os.path.isfile(init):
            continue
        text = open(init, encoding="utf-8").read()
        if any(p.search(text) for p in _ROOT_BY_FILE):
            root_offenders.append(entry)
        if re.search(r"os\.chdir\s*\(", text):
            chdir_offenders.append(entry)
    check("no_root_via_file_dirname", not root_offenders, ", ".join(root_offenders))
    check("no_chdir_in_plugins", not chdir_offenders, ", ".join(chdir_offenders))


# --------------------------------------------------------------------------
# 3. Модульные пути: ссылки из репозитория разрешаются
# --------------------------------------------------------------------------

_MODULE_REF = re.compile(
    r"^\s*(?:from\s+tools\s+import\s+([A-Za-z_]\w*)"
    r"|from\s+tools\.([A-Za-z_]\w*(?:\.\w+)*)\s+import"
    r"|import\s+tools\.([A-Za-z_]\w*(?:\.\w+)*))",
    re.MULTILINE)


def _collect_module_refs() -> dict:
    refs = {}
    scan_roots = [os.path.join(ROOT, "core"), os.path.join(ROOT, "tools"),
                  os.path.join(ROOT, "tests")]
    files = [os.path.join(ROOT, "botinok.py")]
    for base in scan_roots:
        for dirpath, dirnames, names in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".kilo")]
            files += [os.path.join(dirpath, n) for n in names if n.endswith(".py")]
    for path in files:
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        for m in _MODULE_REF.finditer(text):
            name = m.group(1) or m.group(2) or m.group(3)
            if not name:
                continue
            refs.setdefault(name.split(".")[0], set()).add(os.path.relpath(path, ROOT))
    return refs


def part_module_refs() -> None:
    print("\n[3] модульные пути tools.*")
    refs = _collect_module_refs()
    check("refs_found", bool(refs), str(sorted(refs)))
    tools_dir = os.path.join(install_root(), "tools")
    tm = ToolManager()
    for name, where in sorted(refs.items()):
        try:
            importlib.import_module(f"tools.{name}")
            imported = True
        except Exception as e:  # noqa: BLE001 — это и проверяем
            imported = False
            check(f"import_tools_{name}", False, f"{type(e).__name__}: {e} ({sorted(where)})")
            continue
        check(f"import_tools_{name}", imported)
        plugin = os.path.isdir(os.path.join(tools_dir, name))
        if plugin:
            check(f"plugin_folder_{name}", os.path.isfile(os.path.join(tools_dir, name, "tool.json")))
        else:
            check(f"lib_file_{name}", os.path.isfile(os.path.join(tools_dir, f"{name}.py")))
    # каждый подключённый инструмент — папка-плагин с контрактом
    for name, spec in sorted(td.discover().specs.items()):
        check(f"registry_folder_{name}", os.path.isdir(spec.path), spec.path)
        check(f"registry_manifest_{name}",
              os.path.isfile(os.path.join(spec.path, "tool.json")), spec.path)
    # каждая папка-плагин, на которую ссылается код, зарегистрирована как инструмент
    registered_folders = {s.folder for s in td.discover().specs.values()}
    unregistered = [n for n in sorted(refs)
                    if os.path.isdir(os.path.join(tools_dir, n)) and n not in registered_folders]
    check("refs_plugins_registered", not unregistered, ", ".join(unregistered))


# --------------------------------------------------------------------------
# 4. Контракт каждого плагина: схема, entry, provides
# --------------------------------------------------------------------------

def part_plugin_contract() -> None:
    print("\n[4] контракт каждого плагина")
    d = td.discover()
    check("no_invalid_plugins", not d.invalid, str(d.invalid))
    for name, spec in sorted(d.specs.items()):
        schema = spec.schema or {}
        fn = schema.get("function") or {}
        check(f"schema_{name}", schema.get("type") == "function" and fn.get("name") == name)
        try:
            func = spec.entry_func()
            callable_ok = callable(func)
            err = ""
        except Exception as e:  # noqa: BLE001
            callable_ok, err = False, f"{type(e).__name__}: {e}"
        check(f"entry_callable_{name}", callable_ok, err)
        if not callable_ok:
            continue
        import inspect
        try:
            params = inspect.signature(func).parameters
        except (TypeError, ValueError):
            continue
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        for provide in spec.provides:
            kwarg = td.provides_kwarg(provide)
            check(f"provides_{name}_{provide}", has_kwargs or kwarg in params, str(list(params)))
        for kind in spec.danger:
            check(f"danger_known_{name}_{kind}", kind in td.DANGER_KNOWN, kind)


# --------------------------------------------------------------------------
# 5. Smoke-вызовы безопасных действий (без сети и dangerous mode)
# --------------------------------------------------------------------------

SMOKE_CALLS = {
    "web": {"action": "help"},
    "web_search": {"query": ""},
    "open_url": {"url": ""},
    "web_extract": {"url": ""},
    "curl": {"url": ""},
    "file_system": {"action": "help"},
    "code_editor": {"action": "help", "path": "."},
    "journal": {"action": "stats"},
    "experience": {"action": "list"},
    "github": {"action": "get_repo", "repo": ""},
    "skills": {"action": "list"},
    "image": {"action": "list"},
    "session_memory": {"action": "context_stats"},
    "sign_step": {"goal": "t", "done": "t", "status": "progress"},
    "tools": {"action": "list"},
}
# Намеренно не вызываем: shell_exec (dangerous), vision/audio (нужны файлы-медиа).
SMOKE_SKIPPED = ("shell_exec", "vision", "audio")


def part_smoke_calls() -> None:
    print("\n[5] smoke-вызовы инструментов")
    tm = ToolManager()
    with tempfile.TemporaryDirectory() as sess:
        for name, args in SMOKE_CALLS.items():
            if name not in tm._tool_registry:
                check(f"smoke_present_{name}", False, "инструмент не подключён")
                continue
            try:
                out = tm.call_tool(name, dict(args), session_path=sess)
            except Exception as e:  # noqa: BLE001 — падение инструмента и ловим
                check(f"smoke_{name}", False, f"raised {type(e).__name__}: {e}")
                continue
            text = str(out)
            check(f"smoke_{name}", out is not None
                  and "Error calling tool" not in text and "Traceback" not in text,
                  text[:140])
        # алиас legacy-инструмента остаётся вызываемым
        out = str(tm.call_tool("web_extractor", {"url": ""}, session_path=sess))
        check("smoke_alias_web_extractor", "Error calling tool" not in out, out[:120])
    for name in SMOKE_SKIPPED:
        check(f"skipped_present_{name}", name in ToolManager()._tool_registry, name)


# --------------------------------------------------------------------------
# 6. Ссылки в README инструментов резолвятся
# --------------------------------------------------------------------------

def part_tool_readmes() -> None:
    print("\n[6] ссылки в README инструментов")
    tools_dir = os.path.join(install_root(), "tools")
    bad = []
    for entry in sorted(os.listdir(tools_dir)):
        readme = os.path.join(tools_dir, entry, "README.md")
        if not os.path.isfile(readme):
            continue
        base = os.path.dirname(readme)
        text = open(readme, encoding="utf-8").read()
        for target in re.findall(r"\]\(([^)#\s]+)", text):
            if target.startswith(("http://", "https://")):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(base, target))):
                bad.append(f"{entry}: {target}")
    check("tool_readme_links_ok", not bad, "; ".join(bad[:5]))


# --------------------------------------------------------------------------
# 7. git трекает файлы плагинов (иначе install/update их не доставит)
# --------------------------------------------------------------------------

def part_git_tracking() -> None:
    print("\n[7] git трекает файлы плагинов")
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        check("git_available", True, "нет .git — пропуск")
        return
    tools_dir = os.path.join(install_root(), "tools")
    required = []
    for entry in sorted(os.listdir(tools_dir)):
        path = os.path.join(tools_dir, entry)
        if not os.path.isdir(path) or entry.startswith(("_", ".")):
            continue
        for fname in ("tool.json", "README.md", "__init__.py"):
            required.append(os.path.relpath(os.path.join(path, fname), ROOT))
    required.append(os.path.relpath(os.path.join(tools_dir, "_template", "README.md"), ROOT))
    try:
        tracked = set(subprocess.run(
            ["git", "-C", ROOT, "ls-files", "--", "tools"],
            capture_output=True, text=True, timeout=30).stdout.splitlines())
    except Exception as e:  # noqa: BLE001
        check("git_ls_files", False, f"{type(e).__name__}: {e}")
        return
    missing = [f for f in required if f not in tracked]
    check("all_plugin_files_tracked", not missing, ", ".join(missing[:6]))


# --------------------------------------------------------------------------
# 8. Ссылки на пути инструментов в документации/промптах не устарели
# --------------------------------------------------------------------------

_DOC_PATH_RE = re.compile(r"tools/([a-z_][a-z_0-9]*)(\.py|/)")
_DOC_SKIP_DIRS = {".git", ".kilo", "venv", ".venv", "__pycache__", ".pytest_cache",
                  "sessions", ".browser_profile", ".tmp", ".sixth", ".windsurf"}
# История: записи о прошлом не переписываем (журнал и changelog append-only).
_DOC_SKIP_FILES = {"CHANGELOG.md", os.path.join("wiki", "log.md")}


def part_doc_paths() -> None:
    print("\n[8] ссылки на пути инструментов в документации")
    tools_dir = os.path.join(install_root(), "tools")

    def is_plugin(name: str) -> bool:
        return os.path.isfile(os.path.join(tools_dir, name, "tool.json"))

    def is_lib(name: str) -> bool:
        return os.path.isfile(os.path.join(tools_dir, f"{name}.py"))

    offenders = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in _DOC_SKIP_DIRS]
        for fn in names:
            if not fn.endswith((".md", ".txt", ".py", ".sh", ".json")):
                continue
            path = os.path.join(base, fn)
            rel = os.path.relpath(path, ROOT)
            if rel in _DOC_SKIP_FILES:
                continue
            try:
                text = open(path, encoding="utf-8").read()
            except OSError:
                continue
            for m in _DOC_PATH_RE.finditer(text):
                name, suffix = m.group(1), m.group(2)
                if suffix == ".py":
                    if not is_lib(name) and is_plugin(name):
                        offenders.append(f"{rel}: tools/{name}.py → tools/{name}/")
                else:  # ссылка на папку
                    if not is_plugin(name) and is_lib(name):
                        offenders.append(f"{rel}: tools/{name}/ → tools/{name}.py")
    check("doc_tool_paths_actual", not offenders, "; ".join(offenders[:6]))


# --------------------------------------------------------------------------

def main() -> int:
    part_paths()
    part_static_scan()
    part_module_refs()
    part_plugin_contract()
    part_smoke_calls()
    part_tool_readmes()
    part_git_tracking()
    part_doc_paths()
    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ РЕГРЕССИИ ПЛАГИНОВ НЕ ОБНАРУЖЕНЫ")
    return 0


def test_tool_regressions() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
