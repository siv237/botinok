#!/usr/bin/env python3
"""Контракт инструментов-плагинов (папка = инструмент) и жизненный цикл.

Проверяется:
  * контракт всех рабочих папок `tools/` (манифест + README + схема + вход);
  * `_template` и любые папки с `_` не подключаются;
  * подключение на лету: положили папку — инструмент появился в реестре,
    каталоге и payload; удалили — исчез отовсюду (включая вызов и enable);
  * контракт `provides` (session_path / progress / dangerous_mode) — передаётся
    только объявленное и принятое сигнатурой;
  * автосхема из сигнатуры, алиасы, always_on;
  * правка кода/манифеста плагина подхватывается на лету (без перезапуска) и
    состояние плагина не сбрасывается между ходами;
  * класс опасности объявляет сам плагин (`danger`), гейт работает и для
    сторонних имён; dotted `entry` в подмодуль папки; сбой скана виден;
  * нарушения контракта (битый JSON, нет README, чужая схема, неизвестный
    provides, падающий импорт) не ломают систему и видны как сломанный плагин.

Запуск: venv/bin/python -u tests/test_plugin_folders.py
        venv/bin/python -m pytest tests/test_plugin_folders.py -q
"""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import tool_discovery as td          # noqa: E402
from core.tool_manager import ToolManager, requires_dangerous  # noqa: E402
from tools import tools_catalog as tc          # noqa: E402

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        FAILURES.append(name)


# --------------------------------------------------------------------------
# Строители тестовых плагинов
# --------------------------------------------------------------------------

CALL_ECHO = '''
def execute(action="run", **kwargs):
    parts = ["action=%s" % action]
    for key in ("session_path", "progress_callback", "dangerous_mode"):
        if kwargs.get(key) is not None:
            parts.append("%s=yes" % key)
    return "; ".join(parts)
'''

CALL_ECHO_WITH_SESSION = '''
def execute(query="", session_path=None, **kwargs):
    parts = ["query=%s" % query]
    if session_path is not None:
        parts.append("session_path=yes")
    if kwargs.get("progress_callback") is not None:
        parts.append("progress_callback=yes")
    return "; ".join(parts)
'''


def make_plugin(tools_dir: str, folder: str, manifest: dict = None,
                code: str = CALL_ECHO, readme: str = "# test plugin\n",
                raw_manifest: str = None) -> str:
    path = os.path.join(tools_dir, folder)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(code)
    if raw_manifest is not None:
        with open(os.path.join(path, "tool.json"), "w", encoding="utf-8") as f:
            f.write(raw_manifest)
    elif manifest is not None:
        with open(os.path.join(path, "tool.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    if readme is not None:
        with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
            f.write(readme)
    return path


class TempTools:
    """Временная папка инструментов, подсунутая через BOTINOK_TOOLS_DIR."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="bt_tools_")
        self.dir = os.path.join(self.tmp, "tools")
        os.makedirs(self.dir)
        self._old_env = os.environ.get("BOTINOK_TOOLS_DIR")

    def __enter__(self):
        os.environ["BOTINOK_TOOLS_DIR"] = self.dir
        td.clear_cache()
        return self

    def __exit__(self, *exc):
        if self._old_env is None:
            os.environ.pop("BOTINOK_TOOLS_DIR", None)
        else:
            os.environ["BOTINOK_TOOLS_DIR"] = self._old_env
        td.clear_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# 1. Контракт рабочих инструментов репозитория
# --------------------------------------------------------------------------

EXPECTED_PRIMARIES = {
    "audio", "code_editor", "curl", "experience", "file_system", "github",
    "image", "journal", "open_url", "session_memory", "shell_exec", "sign_step",
    "skills", "tools", "vision", "web", "web_extract", "web_search",
}
EXPECTED_ALIASES = {"web_extractor"}


def part_repo_contract() -> None:
    print("\n[1] контракт рабочих папок tools/")
    d = td.discover()
    check("primaries_exact", set(d.specs) == EXPECTED_PRIMARIES,
          f"{sorted(set(d.specs) ^ EXPECTED_PRIMARIES)}")
    check("aliases_exact", set(d.alias_map) == EXPECTED_ALIASES, str(d.alias_map))
    check("no_invalid", not d.invalid, str(d.invalid))
    check("always_on_exact", d.always_on == {"tools", "sign_step", "session_memory"},
          str(d.always_on))

    for name, spec in sorted(d.specs.items()):
        check(f"folder_{name}", os.path.isdir(spec.path) and os.path.isfile(spec.init_path))
        check(f"readme_{name}", os.path.isfile(spec.readme_path))
        schema = spec.schema or {}
        fn = schema.get("function") or {}
        check(f"schema_{name}",
              schema.get("type") == "function" and fn.get("name") == name
              and isinstance(fn.get("parameters"), dict),
              str(schema)[:120])

    tm = ToolManager()
    defs = tm.get_tool_definitions()
    check("all_primaries_in_payload", set(defs) == EXPECTED_PRIMARIES,
          f"{sorted(set(defs) ^ EXPECTED_PRIMARIES)}")
    tm.get_all_tools()
    check("no_broken_in_repo", not tm.broken_tools, str(tm.broken_tools))
    check("template_not_connected",
          "example_tool" not in tm._tool_registry
          and os.path.isdir(os.path.join(ROOT, "tools", "_template")))


# --------------------------------------------------------------------------
# 2. Подключение на лету: положили папку — инструмент появился
# --------------------------------------------------------------------------

def part_dropin_live() -> None:
    print("\n[2] подключение на лету (положили папку)")
    with TempTools() as tt:
        make_plugin(tt.dir, "hello", {"description": "привет из плагина",
                                      "provides": ["session_path"]},
                    code=CALL_ECHO_WITH_SESSION)
        tm = ToolManager()
        check("dropin_registered", "hello" in tm._tool_registry)
        check("dropin_in_payload", "hello" in tm.get_tool_definitions())

        with tempfile.TemporaryDirectory() as sess:
            # каталог и enable
            cat = tc.catalog_text(tm)
            check("dropin_in_catalog", "- hello:" in cat)
            check("dropin_not_enabled_by_default", "hello" not in tc.enabled_tools(sess))
            r = tc.tools_catalog_tool(action="enable", name="hello", session_path=sess)
            check("dropin_enable_ok", r.startswith("ok"), r[:120])
            check("dropin_enabled", "hello" in tc.enabled_tools(sess))

            # payload-фильтр (логика textual_integration)
            defs = tm.get_tool_definitions()
            allowed = tc.enabled_tools(sess)
            payload = [t for t in defs.values()
                       if ((t or {}).get("function") or {}).get("name") in allowed]
            check("dropin_payload_filtered",
                  "hello" in {t["function"]["name"] for t in payload})

            # вызов: session_path передан (объявлен в provides)
            out = tm.call_tool("hello", {"action": "ping"}, session_path=sess)
            check("dropin_call_session_path", "session_path=yes" in out, out)

        # вторая папка появляется без пересоздания менеджера (hot add)
        make_plugin(tt.dir, "later", {"description": "поздний плагин"}, code=CALL_ECHO)
        check("hot_add_invisible_until_call", "later" not in tm._tool_registry)
        out = tm.call_tool("later", {"action": "x"})
        check("hot_add_after_call", out == "action=x", out)
        check("hot_add_in_payload", "later" in tm.get_tool_definitions())


# --------------------------------------------------------------------------
# 3. Отключение удалением папки — исчезает отовсюду
# --------------------------------------------------------------------------

def part_removal_live() -> None:
    print("\n[3] удаление папки — инструмент исчезает")
    with TempTools() as tt:
        path = make_plugin(tt.dir, "gone", {"description": "временный"},
                           code=CALL_ECHO)
        tm = ToolManager()
        with tempfile.TemporaryDirectory() as sess:
            tc.tools_catalog_tool(action="enable", name="gone", session_path=sess)
            check("before_removal_enabled", "gone" in tc.enabled_tools(sess))
            check("before_removal_callable", tm.call_tool("gone", {}) == "action=run")

            shutil.rmtree(path)
            out = tm.call_tool("gone", {})
            check("after_removal_unknown", out.startswith("Error: unknown tool"), out)
            check("after_removal_not_in_registry", "gone" not in tm._tool_registry)
            check("after_removal_not_in_payload", "gone" not in tm.get_tool_definitions())
            check("after_removal_not_in_catalog", "- gone:" not in tc.catalog_text(tm))
            check("after_removal_enabled_filtered", "gone" not in tc.enabled_tools(sess))
            r = tc.tools_catalog_tool(action="enable", name="gone", session_path=sess)
            check("after_removal_enable_error", r.startswith("Error"), r[:120])
            check("after_removal_no_broken_nag", tm.get_broken_tools_info() is None,
                  str(tm.broken_tools))
            # папка вернулась — инструмент снова работает (без перезапуска)
            make_plugin(tt.dir, "gone", {"description": "вернулся"}, code=CALL_ECHO)
            check("re_added_works", tm.call_tool("gone", {"action": "back"}) == "action=back")


# --------------------------------------------------------------------------
# 4. Контракт provides: что объявлено и принято — только то и передаётся
# --------------------------------------------------------------------------

def part_provides_contract() -> None:
    print("\n[4] контракт provides")
    with TempTools() as tt:
        # объявлен session_path и функция его принимает → передан
        make_plugin(tt.dir, "takes", {"provides": ["session_path"]},
                    code=CALL_ECHO_WITH_SESSION)
        # session_path принимается, но НЕ объявлен → не передан
        make_plugin(tt.dir, "ignores", {}, code=CALL_ECHO_WITH_SESSION)
        # progress объявлен, но функция его не принимает → не передан, без TypeError
        make_plugin(tt.dir, "noparam", {"provides": ["progress"]}, code=CALL_ECHO)
        tm = ToolManager()
        with tempfile.TemporaryDirectory() as sess:
            out = tm.call_tool("takes", {"query": "q"}, session_path=sess)
            check("declared_and_accepted_passed", "session_path=yes" in out, out)
            out = tm.call_tool("ignores", {"query": "q"}, session_path=sess)
            check("not_declared_not_passed", "session_path=yes" not in out, out)
            out = tm.call_tool("noparam", {"action": "a"}, session_path=sess)
            check("declared_but_unsupported_skipped", out == "action=a", out)
            # progress передаётся, когда объявлен и принимается
            make_plugin(tt.dir, "withprogress",
                        {"provides": ["progress"]}, code=CALL_ECHO_WITH_SESSION)
            tm.rediscover()
            out = tm.call_tool("withprogress", {"query": "q"},
                               progress_callback=lambda *a: None)
            check("progress_passed", "progress_callback=yes" in out, out)


# --------------------------------------------------------------------------
# 5. Автосхема из сигнатуры, алиасы, always_on
# --------------------------------------------------------------------------

def part_auto_schema_alias_alwayson() -> None:
    print("\n[5] автосхема, алиасы, always_on")
    with TempTools() as tt:
        make_plugin(tt.dir, "auto", {"description": "авто-схема"},
                    code='def execute(query: str, limit: int = 5, flag: bool = False):\n'
                         '    return "ok"\n')
        make_plugin(tt.dir, "aliased", {"aliases": ["alias_name"]}, code=CALL_ECHO)
        make_plugin(tt.dir, "core_extra", {"always_on": True}, code=CALL_ECHO)
        tm = ToolManager()
        defs = tm.get_tool_definitions()
        auto = ((defs.get("auto") or {}).get("function") or {})
        params = (auto.get("parameters") or {})
        check("auto_description", auto.get("description") == "авто-схема", str(auto)[:120])
        check("auto_types",
              (params.get("properties") or {}).get("query") == {"type": "string"}
              and (params.get("properties") or {}).get("limit") == {"type": "integer"}
              and (params.get("properties") or {}).get("flag") == {"type": "boolean"},
              str(params))
        check("auto_required", params.get("required") == ["query"], str(params))
        check("alias_callable", tm.call_tool("alias_name", {}) == "action=run")
        check("alias_not_in_payload", "alias_name" not in defs)
        check("always_on_in_enabled", "core_extra" in tc.enabled_tools(None))
        check("always_on_not_in_catalog", "- core_extra:" not in tc.catalog_text(tm))


# --------------------------------------------------------------------------
# 6. Нарушения контракта — не ломают систему, видны как сломанный плагин
# --------------------------------------------------------------------------

def part_contract_violations() -> None:
    print("\n[6] нарушения контракта")
    with TempTools() as tt:
        make_plugin(tt.dir, "no_readme", {"description": "x"}, readme=None)
        make_plugin(tt.dir, "bad_json", raw_manifest="{ это не json")
        make_plugin(tt.dir, "wrong_name",
                    {"schema": {"type": "function",
                                "function": {"name": "other", "description": "d",
                                             "parameters": {"type": "object"}}}})
        make_plugin(tt.dir, "bad_provides", {"provides": ["teleport"]})
        make_plugin(tt.dir, "broken_import", {}, code="import no_such_module_xyz\n")
        make_plugin(tt.dir, "broken_entry",
                    {"entry": "nope",
                     "schema": {"type": "function",
                                "function": {"name": "broken_entry", "description": "d",
                                             "parameters": {"type": "object"}}}},
                    code=CALL_ECHO)
        # папка с '_' игнорируется целиком, даже если внутри мусор
        make_plugin(tt.dir, "_junk", raw_manifest="{ мусор")
        # папка без манифеста — не плагин
        os.makedirs(os.path.join(tt.dir, "not_a_plugin"), exist_ok=True)

        tm = ToolManager()
        check("no_readme_rejected", "no_readme" not in tm._tool_registry)
        check("bad_json_rejected", "bad_json" not in tm._tool_registry)
        check("wrong_schema_rejected", "wrong_name" not in tm._tool_registry)
        check("bad_provides_rejected", "bad_provides" not in tm._tool_registry)
        check("underscore_ignored", "_junk" not in tm._tool_registry)
        check("folder_without_manifest_ignored", "not_a_plugin" not in tm._tool_registry)
        invalid_keys = " ".join(tm.broken_tools)
        check("invalid_reported", "no_readme" in invalid_keys and "bad_json" in invalid_keys
              and "wrong_name" in invalid_keys and "bad_provides" in invalid_keys,
              invalid_keys)
        check("junk_not_reported", "_junk" not in invalid_keys, invalid_keys)
        check("broken_import_reported", "broken_import" in tm.broken_tools,
              str(tm.broken_tools))
        check("broken_nag_has_reason", "PluginContractError" in tm.get_broken_tools_info()
              or "no_such_module_xyz" in tm.get_broken_tools_info())

        out = tm.call_tool("broken_entry", {})
        check("broken_entry_error", out.startswith("Error: tool 'broken_entry' is broken"), out)
        out = tm.call_tool("bad_json", {})
        check("rejected_tool_unknown", out.startswith("Error: unknown tool"), out)


# --------------------------------------------------------------------------
# 7. Правка плагина подхватывается на лету
# --------------------------------------------------------------------------

def part_hot_reload() -> None:
    print("\n[7] правка плагина подхватывается на лету")
    with TempTools() as tt:
        path = make_plugin(tt.dir, "editme", {"description": "v1"}, code=CALL_ECHO)
        tm = ToolManager()
        check("before_edit", tm.call_tool("editme", {"action": "x"}) == "action=x")
        # Правка кода того же размера и в ту же секунду: проверяем и то, что
        # байткод-кэш не отдаёт старую версию.
        with open(os.path.join(path, "__init__.py"), "w", encoding="utf-8") as f:
            f.write(CALL_ECHO.replace('"action=%s" % action', '"ACTION=%s" % action'))
        out = tm.call_tool("editme", {"action": "x"})
        check("code_edit_reloaded", out == "ACTION=x", out)
        # Правка манифеста видна в payload
        with open(os.path.join(path, "tool.json"), "w", encoding="utf-8") as f:
            json.dump({"description": "новое описание"}, f, ensure_ascii=False)
        desc = ((tm.get_tool_definitions().get("editme") or {}).get("function") or {}).get("description")
        check("manifest_edit_reloaded", desc == "новое описание", str(desc))
        # Правка вспомогательного файла папки тоже подхватывается
        with open(os.path.join(path, "helper.py"), "w", encoding="utf-8") as f:
            f.write('VALUE = "h1"\n')
        with open(os.path.join(path, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("from .helper import VALUE\n\n\ndef execute():\n    return VALUE\n")
        check("helper_edit_1", tm.call_tool("editme", {}) == "h1", tm.call_tool("editme", {}))
        with open(os.path.join(path, "helper.py"), "w", encoding="utf-8") as f:
            f.write('VALUE = "h2"\n')
        check("helper_edit_reloaded", tm.call_tool("editme", {}) == "h2", tm.call_tool("editme", {}))


# --------------------------------------------------------------------------
# 8. Работа плагина не сбрасывается сама собой
# --------------------------------------------------------------------------

def part_no_spurious_reload() -> None:
    print("\n[8] состояние плагина не сбрасывается между ходами")
    with TempTools() as tt:
        # Манифест со схемой — как у 18 рабочих инструментов (модуль не
        # импортируется при сканировании).
        make_plugin(tt.dir, "counter", {
            "description": "counter",
            "schema": {"type": "function", "function": {
                "name": "counter", "description": "counter",
                "parameters": {"type": "object", "properties": {}}}}},
            code="N = 0\ndef execute():\n    global N\n    N += 1\n    return 'n=%d' % N\n")
        tm = ToolManager()
        check("first_call", tm.call_tool("counter", {}) == "n=1")
        check("second_call", tm.call_tool("counter", {}) == "n=2")
        # Между ходами харнес собирает payload — импорт создал __pycache__,
        # но это не правка плагина и не должно выгружать инструмент.
        tm.get_tool_definitions()
        check("state_kept_after_payload", tm.call_tool("counter", {}) == "n=3",
              tm.call_tool("counter", {}))


# --------------------------------------------------------------------------
# 9. Класс опасности объявляет сам плагин (`danger` в манифесте)
# --------------------------------------------------------------------------

def part_danger_capability() -> None:
    print("\n[9] danger-возможности плагина")
    with TempTools() as tt:
        make_plugin(tt.dir, "fake_shell", {"danger": ["shell"]},
                    code='def execute(action="run", command=""):\n    return "ran"\n')
        make_plugin(tt.dir, "bad_danger", {"danger": ["teleport"]})
        tm = ToolManager()
        check("danger_registered", "fake_shell" in tm._tool_registry)
        check("danger_from_manifest", td.danger_kinds("fake_shell") == ("shell",),
              str(td.danger_kinds("fake_shell")))
        check("bad_danger_rejected", "bad_danger" not in tm._tool_registry)
        with tempfile.TemporaryDirectory() as sess:
            out = tm.call_tool("fake_shell", {"action": "run", "command": "ls"}, session_path=sess)
            check("danger_gate_blocks", out.startswith("Error: fake_shell action 'run'"), out)
            check("requires_dangerous_true",
                  requires_dangerous("fake_shell", {"action": "run"}, sess))
            tm.dangerous_mode = True
            check("danger_gate_allows_when_on",
                  tm.call_tool("fake_shell", {"action": "run", "command": "ls"},
                               session_path=sess) == "ran")
        # Без объявленного danger инструмент не гейтится
        make_plugin(tt.dir, "plain", {}, code='def execute(action="run"):\n    return "ok"\n')
        tm.rediscover()
        with tempfile.TemporaryDirectory() as sess:
            check("plain_not_gated", tm.call_tool("plain", {"action": "run"}, session_path=sess) == "ok")


# --------------------------------------------------------------------------
# 10. dotted entry (функция в подмодуле папки) и сбой скана
# --------------------------------------------------------------------------

def part_entry_and_scan_errors() -> None:
    print("\n[10] dotted entry и сбой скана")
    with TempTools() as tt:
        path = os.path.join(tt.dir, "multi")
        os.makedirs(path)
        with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
            f.write("# multi\n")
        with open(os.path.join(path, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(path, "main.py"), "w", encoding="utf-8") as f:
            f.write('def execute():\n    return "from submodule"\n')
        with open(os.path.join(path, "tool.json"), "w", encoding="utf-8") as f:
            json.dump({"entry": "main.execute"}, f)
        tm = ToolManager()
        check("dotted_entry_works", tm.call_tool("multi", {}) == "from submodule",
              tm.call_tool("multi", {}))
    check("template_dir_exists", os.path.isdir(td.template_dir()), td.template_dir())

    # Сбой скана (нет папки) — не «ноль инструментов молча», а видимая ошибка.
    old = os.environ.get("BOTINOK_TOOLS_DIR")
    os.environ["BOTINOK_TOOLS_DIR"] = "/tmp/kilo/no_such_tools_dir_for_test"
    td.clear_cache()
    try:
        tm = ToolManager()
        check("scan_error_reported", "tools/" in tm.broken_tools, str(tm.broken_tools))
        check("scan_error_has_reason",
              "недоступна" in tm.get_broken_tools_info(), str(tm.get_broken_tools_info())[:120])
        check("scan_error_keeps_core_fallback",
              {"tools", "sign_step", "session_memory"} <= tc.enabled_tools(None))
    finally:
        if old is None:
            os.environ.pop("BOTINOK_TOOLS_DIR", None)
        else:
            os.environ["BOTINOK_TOOLS_DIR"] = old
        td.clear_cache()


# --------------------------------------------------------------------------

def main() -> int:
    part_repo_contract()
    part_dropin_live()
    part_removal_live()
    part_provides_contract()
    part_auto_schema_alias_alwayson()
    part_contract_violations()
    part_hot_reload()
    part_no_spurious_reload()
    part_danger_capability()
    part_entry_and_scan_errors()
    print("\n" + "=" * 70)
    if FAILURES:
        print(f"❌ ПРОВАЛЕНО: {len(FAILURES)} — {FAILURES}")
        return 1
    print("✅ КОНТРАКТ ПЛАГИНОВ ПРОЙДЕН")
    return 0


def test_plugin_folders() -> None:
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
