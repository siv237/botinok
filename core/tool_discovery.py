#!/usr/bin/env python3
"""Плагинные инструменты: папка = инструмент, манифест = контракт.

Контракт папки (образец — ``tools/_template/``):
  ``tools/<folder>/tool.json``   — манифест подключения;
  ``tools/<folder>/__init__.py`` — реализация (entry-функция);
  ``tools/<folder>/README.md``   — описание от разработчика (обязательно).

Правила:
  * папки, имя которых начинается с ``_`` или ``.`` — НЕ инструменты
    (например ``_template`` со скелетом для разработчика);
  * подключение «на лету»: :func:`discover` перечитывает папку инструментов и
    инвалидирует кэш по штампу (mtime манифеста/папки/реализации). Положили
    папку — инструмент появился, удалили — исчез, без перезапуска процесса;
  * папка с манифестом, но без ``README.md``, с битым JSON, неизвестным
    ``provides`` или неверной схемой — не подключается и попадает в
    ``invalid`` (ToolManager показывает её как сломанный инструмент).

Манифест ``tool.json`` (все поля кроме ``schema`` опциональны):
  ``name``        — id инструмента (по умолчанию имя папки);
  ``entry``       — путь к функции внутри пакета, точечный (по умолчанию
                    ``execute``); например ``main.execute``;
  ``aliases``     — дополнительные имена для вызова (без своей схемы);
  ``provides``    — что платформа передаёт в вызов: ``session_path``,
                    ``progress`` (``progress_callback``), ``dangerous_mode``;
  ``always_on``   — всегда в payload (ядро харнесса: tools/sign_step/...);
  ``description`` — короткое описание для каталога/автосхемы;
  ``schema``      — полная OpenAI-схема функции (если нет — генерируется из
                    сигнатуры entry-функции: типы и обязательность из аннотаций).

Импорт реализации ленив: если в манифесте есть схема, модуль при сканировании
не импортируется. Для автосхемы (или для сломанной реализации) импорт
выполняется один раз на скан и результат кэшируется.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import sys
import typing
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

MANIFEST_FILE = "tool.json"
README_FILE = "README.md"

PROVIDES_SESSION = "session_path"
PROVIDES_PROGRESS = "progress"
PROVIDES_DANGEROUS = "dangerous_mode"
PROVIDES_KNOWN = (PROVIDES_SESSION, PROVIDES_PROGRESS, PROVIDES_DANGEROUS)

# Контекстные kwargs, которые платформа передаёт в вызов по объявленному
# `provides` — единый словарь для discovery и для ToolManager.call_tool.
PROVIDES_KWARG = {
    PROVIDES_SESSION: "session_path",
    PROVIDES_PROGRESS: "progress_callback",
    PROVIDES_DANGEROUS: "dangerous_mode",
}

# Классы опасности: плагин сам объявляет в манифесте (`danger`), какие его
# действия требуют dangerous mode. Политику применяет ToolManager.
DANGER_SHELL = "shell"                    # опасные action целиком (shell-подобные)
DANGER_SESSION_WRITE = "session_write"    # мутации файлов внутри папки сессии
DANGER_SESSION_OUTPUT = "session_output"  # запись вывода в файл внутри сессии
DANGER_KNOWN = (DANGER_SHELL, DANGER_SESSION_WRITE, DANGER_SESSION_OUTPUT)

# Служебные параметры платформы: не показываем модели в автосхеме.
_PLATFORM_HIDDEN_PARAMS = ("progress_callback", "dangerous_mode")

_INSTALL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_JSON_TYPES = {str: "string", int: "integer", float: "number",
               bool: "boolean", list: "array", tuple: "array", dict: "object"}


def provides_kwarg(provide: str) -> str:
    """Имя kwargs, в который превращается объявленный ``provides``."""
    return PROVIDES_KWARG.get(provide, provide)


def install_tools_dir() -> str:
    """Папка инструментов установки (без учёта env-переопределения)."""
    return os.path.join(_INSTALL_DIR, "tools")


def default_tools_dir() -> str:
    """Папка инструментов: ``BOTINOK_TOOLS_DIR`` или ``<install>/tools``.

    Переопределение через env — это смена КОДА, который грузит ботинок
    (папки-плагины исполняются), поэтому при расхождении с папкой установки
    пишем громкое предупреждение (один раз на путь).
    """
    env = os.environ.get("BOTINOK_TOOLS_DIR", "").strip()
    if env:
        path = os.path.expanduser(os.path.expandvars(env))
        _warn_foreign_tools_dir(path)
        return path
    return install_tools_dir()


def _warn_foreign_tools_dir(path: str) -> None:
    if os.path.realpath(path) == os.path.realpath(install_tools_dir()):
        return
    if path in _WARNED_DIRS:
        return
    _WARNED_DIRS.add(path)
    print(f"[botinok] ⚠ Инструменты загружаются из сторонней папки "
          f"(BOTINOK_TOOLS_DIR={path}): код плагинов исполняется с правами "
          f"пользователя. Убери переменную, если это не задумано.", file=sys.stderr)


_WARNED_DIRS: set = set()


def _is_plugin_folder(name: str) -> bool:
    return not (name.startswith("_") or name.startswith("."))


# --------------------------------------------------------------------------
# Спека инструмента и её загрузка
# --------------------------------------------------------------------------

@dataclass
class ToolSpec:
    """Один инструмент-плагин (папка с манифестом)."""

    name: str
    folder: str
    path: str
    entry: str = "execute"
    aliases: Tuple[str, ...] = ()
    provides: Tuple[str, ...] = ()
    danger: Tuple[str, ...] = ()     # классы опасности (см. DANGER_*)
    always_on: bool = False
    description: str = ""
    schema: Optional[dict] = None
    stamp: Tuple = ()                # отпечаток файлов папки (для горячей правки)
    synthetic: bool = False          # импорт по пути (кастомный tools_dir)
    load_error: str = ""             # ошибка импорта/генерации схемы
    load_error_type: str = ""

    @property
    def readme_path(self) -> str:
        return os.path.join(self.path, README_FILE)

    @property
    def init_path(self) -> str:
        return os.path.join(self.path, "__init__.py")

    @property
    def module_path(self) -> str:
        """Точечное имя модуля пакета (для совместимости с реестром)."""
        if self.synthetic:
            return f"{self._pkg}.{self.folder}"
        return f"tools.{self.folder}"

    @property
    def _pkg(self) -> str:
        return "_btplugin_" + hashlib.sha1(self.path.encode("utf-8")).hexdigest()[:10]

    def load_module(self):
        """Импортировать пакет инструмента (кэшируется в sys.modules)."""
        if self.synthetic:
            full = self.module_path
            mod = sys.modules.get(full)
            if mod is not None:
                return mod
            # Синтетический родитель-неймспейс, чтобы работали относительные
            # импорты внутри папки плагина (from .helper import …).
            if self._pkg not in sys.modules:
                parent = importlib.util.module_from_spec(
                    importlib.util.spec_from_loader(self._pkg, loader=None))
                parent.__path__ = []          # type: ignore[attr-defined]
                sys.modules[self._pkg] = parent
            spec = importlib.util.spec_from_file_location(
                full, self.init_path,
                submodule_search_locations=[self.path])
            if spec is None or spec.loader is None:
                raise ImportError(f"не удалось загрузить {self.init_path}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[full] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                sys.modules.pop(full, None)
                raise
            return mod
        return importlib.import_module(self.module_path)

    def entry_func(self):
        """entry-функция из загруженного пакета (путь через точки).

        Поддерживается и атрибут пакета (`execute`), и функция в подмодуле
        папки (`main.run`): если атрибута нет — пробуем импортировать
        оставшийся путь как подмодуль пакета плагина.
        """
        parts = [p for p in str(self.entry).split(".") if p]
        if not parts:
            raise ValueError("пустой entry в манифесте")
        obj = self.load_module()
        for i, part in enumerate(parts):
            try:
                obj = getattr(obj, part)
            except AttributeError:
                sub = ".".join(parts[:i + 1])
                obj = importlib.import_module(f"{self.module_path}.{sub}")
        return obj


# --------------------------------------------------------------------------
# Автосхема из сигнатуры
# --------------------------------------------------------------------------

def _json_type(annotation) -> dict:
    if annotation is inspect.Parameter.empty or annotation is None:
        return {"type": "string"}
    if annotation in _JSON_TYPES:
        return {"type": _JSON_TYPES[annotation]}
    origin = typing.get_origin(annotation)
    if origin is typing.Union or isinstance(annotation, getattr(typing, "UnionType", ())):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _json_type(args[0]) if args else {"type": "string"}
    if origin in (list, tuple, set):
        args = typing.get_args(annotation)
        item = _json_type(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item}
    if origin is dict:
        return {"type": "object"}
    return {"type": "string"}


def schema_from_entry(name: str, func, description: str = "") -> dict:
    """Сгенерировать OpenAI-схему функции из сигнатуры entry-функции."""
    sig = inspect.signature(func)
    props: Dict[str, dict] = {}
    required: List[str] = []
    for pname, param in sig.parameters.items():
        if pname in _PLATFORM_HIDDEN_PARAMS:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL,
                          inspect.Parameter.VAR_KEYWORD):
            continue
        props[pname] = _json_type(param.annotation)
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    desc = (description or "").strip()
    if not desc:
        doc = (inspect.getdoc(func) or "").strip()
        desc = doc.split("\n\n")[0].strip() if doc else ""
    if not desc:
        desc = f"Инструмент '{name}'"
    if len(desc) > 400:
        desc = desc[:397] + "..."
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


def _schema_problem(name: str, schema) -> str:
    """Проверка формы схемы; '' — всё хорошо."""
    if not isinstance(schema, dict):
        return "schema должна быть объектом"
    if schema.get("type") != "function" or not isinstance(schema.get("function"), dict):
        return "schema должна быть OpenAI-схемой функции (type=function)"
    fn = schema["function"]
    if str(fn.get("name") or "") != name:
        return (f"schema.function.name='{fn.get('name')}' не совпадает "
                f"с именем инструмента '{name}'")
    if not isinstance(fn.get("parameters"), dict):
        return "schema.function.parameters должна быть объектом"
    return ""


# --------------------------------------------------------------------------
# Сканирование папки
# --------------------------------------------------------------------------

@dataclass
class Discovery:
    """Результат сканирования папки инструментов."""

    specs: Dict[str, ToolSpec] = field(default_factory=dict)      # primary name
    alias_map: Dict[str, str] = field(default_factory=dict)       # alias -> primary
    invalid: Dict[str, str] = field(default_factory=dict)         # folder -> reason
    error: str = ""                                               # скан не удался

    def by_name(self, name: str) -> Optional[ToolSpec]:
        spec = self.specs.get(name)
        if spec is not None:
            return spec
        primary = self.alias_map.get(name)
        return self.specs.get(primary) if primary else None

    def names(self) -> List[str]:
        """Все вызываемые имена: основные + алиасы."""
        return sorted(set(self.specs) | set(self.alias_map))

    @property
    def always_on(self) -> set:
        return {n for n, s in self.specs.items() if s.always_on}

    def danger(self, name: str) -> Tuple[str, ...]:
        """Классы опасности инструмента по имени (с учётом алиасов)."""
        spec = self.by_name(name)
        return tuple(spec.danger) if spec else ()


def _read_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("манифест должен быть JSON-объектом")
    return data


def _parse_manifest(folder: str, path: str, data: dict) -> ToolSpec:
    name = str(data.get("name") or folder).strip()
    if not name:
        raise ValueError("пустое имя инструмента")
    entry = str(data.get("entry") or "execute").strip()
    if not entry:
        raise ValueError("пустой entry")
    aliases = data.get("aliases") or []
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
        raise ValueError("aliases должен быть списком непустых строк")
    provides = data.get("provides") or []
    if not isinstance(provides, list):
        raise ValueError("provides должен быть списком")
    unknown = [p for p in provides if p not in PROVIDES_KNOWN]
    if unknown:
        raise ValueError(f"неизвестные provides: {', '.join(map(str, unknown))} "
                         f"(есть: {', '.join(PROVIDES_KNOWN)})")
    danger = data.get("danger") or []
    if not isinstance(danger, list):
        raise ValueError("danger должен быть списком")
    unknown_danger = [d for d in danger if d not in DANGER_KNOWN]
    if unknown_danger:
        raise ValueError(f"неизвестные danger: {', '.join(map(str, unknown_danger))} "
                         f"(есть: {', '.join(DANGER_KNOWN)})")
    schema = data.get("schema")
    if schema is not None:
        problem = _schema_problem(name, schema)
        if problem:
            raise ValueError(problem)
    if not os.path.isfile(os.path.join(os.path.dirname(path), README_FILE)):
        raise ValueError(f"нет {README_FILE}: папка инструмента обязана содержать "
                         "README с описанием для разработчика (образец: tools/_template)")
    return ToolSpec(
        name=name, folder=folder, path=os.path.dirname(path),
        entry=entry, aliases=tuple(dict.fromkeys(a.strip() for a in aliases)),
        provides=tuple(dict.fromkeys(provides)),
        danger=tuple(dict.fromkeys(danger)), always_on=bool(data.get("always_on")),
        description=str(data.get("description") or "").strip(), schema=schema,
        stamp=_folder_stamp(os.path.dirname(path)),
    )


def source_files(path: str) -> List[str]:
    """Исходники папки-плагина: сам манифест, README и все .py (рекурсивно).

    Считаем именно файлы, а не mtime самой папки: первый импорт создаёт
    ``__pycache__`` и меняет mtime каталога — это не изменение плагина и не
    должно перезагружать инструменты.
    """
    files = [os.path.join(path, MANIFEST_FILE), os.path.join(path, README_FILE)]
    for base, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
        for fn in sorted(names):
            if fn.endswith(".py"):
                files.append(os.path.join(base, fn))
    return files


def _folder_stamp(path: str) -> tuple:
    """Отпечаток файлов папки-плагина: (относительный путь, mtime_ns, размер)."""
    rows = []
    for probe in source_files(path):
        try:
            st = os.stat(probe)
            rows.append((os.path.relpath(probe, path), st.st_mtime_ns, st.st_size))
        except OSError:
            rows.append((os.path.relpath(probe, path), None, None))
    return tuple(rows)


def _stamp(tools_dir: str) -> tuple:
    """Штамп содержимого папки инструментов: по нему кэш инвалидируется."""
    try:
        entries = os.listdir(tools_dir)
    except OSError:
        return ()
    rows = []
    for folder in sorted(entries):
        if not _is_plugin_folder(folder):
            continue
        path = os.path.join(tools_dir, folder)
        if not os.path.isdir(path):
            continue
        rows.append((folder, _folder_stamp(path)))
    return tuple(rows)


def _scan(tools_dir: str) -> Discovery:
    result = Discovery()
    # Инструменты установки грузим как обычный пакет `tools.<folder>` (единый
    # объект модуля для всех потребителей); сторонние папки (env-переопределение,
    # тесты) — по пути файла, чтобы не подменять реальный пакет `tools`.
    synthetic = os.path.realpath(tools_dir) != os.path.realpath(install_tools_dir())
    try:
        entries = os.listdir(tools_dir)
    except OSError as e:
        # Папка недоступна: это НЕ «инструментов нет», а сломанная конфигурация
        # (опечатка в BOTINOK_TOOLS_DIR, права). Молча отдавать пустой набор
        # нельзя — агент остался бы вообще без инструментов.
        result.error = (f"папка инструментов недоступна: {tools_dir} "
                        f"({type(e).__name__}: {e})")
        return result
    for folder in sorted(entries):
        if not _is_plugin_folder(folder):
            continue
        path = os.path.join(tools_dir, folder)
        if not os.path.isdir(path):
            continue
        manifest = os.path.join(path, MANIFEST_FILE)
        if not os.path.isfile(manifest):
            continue  # не плагин (например, библиотека-помощник)
        try:
            data = _read_manifest(manifest)
            spec = _parse_manifest(folder, manifest, data)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            result.invalid[folder] = f"{type(e).__name__}: {e}"
            continue
        if spec.name in result.specs or spec.name in result.alias_map:
            result.invalid[folder] = f"имя '{spec.name}' уже занято другим инструментом"
            continue
        clash = [a for a in spec.aliases if a in result.specs or a in result.alias_map]
        if clash:
            result.invalid[folder] = f"алиасы заняты: {', '.join(clash)}"
            continue
        spec.synthetic = synthetic
        # Схемы нет — генерируем из сигнатуры (единственный случай, когда
        # реализация импортируется уже при сканировании).
        if spec.schema is None:
            try:
                func = spec.entry_func()
                spec.schema = schema_from_entry(spec.name, func, spec.description)
                if not spec.description:
                    spec.description = str(spec.schema["function"]["description"])
            except Exception as e:  # noqa: BLE001 — контракт: сломанный плагин
                spec.load_error = f"{type(e).__name__}: {e}"
                spec.load_error_type = type(e).__name__
        result.specs[spec.name] = spec
        for alias in spec.aliases:
            result.alias_map[alias] = spec.name
    return result


# --------------------------------------------------------------------------
# Кэш сканирования и публичные помощники
# --------------------------------------------------------------------------

_CACHE: Dict[str, object] = {"key": None, "value": None}


def discover(tools_dir: Optional[str] = None, force: bool = False) -> Discovery:
    """Сканировать папку инструментов (с кэшем по штампу содержимого)."""
    path = os.path.realpath(tools_dir or default_tools_dir())
    stamp = _stamp(path)
    key = (path, stamp)
    if not force and _CACHE.get("key") == key and _CACHE.get("value") is not None:
        return _CACHE["value"]  # type: ignore[return-value]
    value = _scan(path)
    _CACHE["key"], _CACHE["value"] = key, value
    return value


def clear_cache() -> None:
    _CACHE["key"] = None
    _CACHE["value"] = None


def always_on_names(tools_dir: Optional[str] = None) -> set:
    """Имена always-on инструментов. При сбое скана — None (см. tools_catalog)."""
    d = discover(tools_dir)
    return set(d.always_on) if not d.error else None  # type: ignore[return-value]


def known_names(tools_dir: Optional[str] = None):
    """Все подключённые имена. При сбое скана — None (фильтровать нельзя)."""
    d = discover(tools_dir)
    return None if d.error else set(d.names())


def danger_kinds(name: str, tools_dir: Optional[str] = None) -> Tuple[str, ...]:
    """Классы опасности инструмента по имени (манифест плагина)."""
    return discover(tools_dir).danger(name)


def template_dir() -> str:
    """Папка-скелет для разработчика (не подключается: имя с '_')."""
    return os.path.join(default_tools_dir(), "_template")
