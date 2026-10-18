import json
import os
import sys
import inspect
import importlib
import importlib.util
import traceback
from datetime import datetime

from core import tool_discovery
from core.path_utils import resolve_session_path
from core.tool_discovery import (DANGER_SESSION_OUTPUT, DANGER_SESSION_WRITE,
                                 DANGER_SHELL, PROVIDES_DANGEROUS,
                                 PROVIDES_PROGRESS, PROVIDES_SESSION,
                                 provides_kwarg)

try:
    from tools import safe_ops as _safe_ops
except Exception:  # pragma: no cover
    _safe_ops = None

TOOLS_LOG = os.path.expanduser("~/.botinok/logs/tools.log")

DANGEROUS_FILESYSTEM_ACTIONS = ("delete", "move", "copy", "mkdir", "chmod", "symlink", "touch")
DANGEROUS_EDITOR_ACTIONS = ("write", "replace", "apply", "undo")
DANGEROUS_SHELL_ACTIONS = ("run", "send", "send_key", "kill", "wait")

# Классы опасности встроенных инструментов. Источник правды — манифест плагина
# (`danger`); таблица ниже — страховка на случай, если сканирование недоступно
# (и обратная совместимость для установок со старыми манифестами).
_LEGACY_DANGER = {
    "shell_exec": (DANGER_SHELL,),
    "code_editor": (DANGER_SESSION_WRITE,),
    "file_system": (DANGER_SESSION_WRITE,),
    "curl": (DANGER_SESSION_OUTPUT,),
    "web": (DANGER_SESSION_OUTPUT,),
}


def danger_kinds(name) -> tuple:
    """Классы опасности инструмента: из манифеста, иначе — легаси-таблица."""
    try:
        kinds = tool_discovery.danger_kinds(name)
    except Exception:
        kinds = ()
    return tuple(kinds) or _LEGACY_DANGER.get(name, ())


def path_within(base, path) -> bool:
    """True, если path лежит внутри base (или равен ему).

    Относительный path трактуется относительно base (папки сессии), а не
    текущей рабочей директории процесса — иначе легитимные пути внутри сессии
    ошибочно считались бы «вне».
    """
    if not base or not path:
        return False
    try:
        base = os.path.realpath(base)
        target = os.path.realpath(path) if os.path.isabs(path) \
            else os.path.realpath(os.path.join(base, path))
        return target == base or target.startswith(base + os.sep)
    except Exception:
        return False


def editor_action_of(args):
    """Канонический action code_editor (алиасы save/edit/patch/... → write/...).

    Гейты безопасности обязаны сравнивать канонический action, иначе алиас
    обходил бы подтверждение dangerous mode.
    """
    action = args.get("action") if isinstance(args, dict) else None
    try:
        from tools.code_editor import normalize_action
        return normalize_action(action)
    except Exception:
        return action


def _accepted_provides(func, declared):
    """Оставить из манифеста только те context-kwargs, что принимает функция.

    Контракт (манифест) декларативен, а сигнатура — источник правды о вызове:
    лишнее объявленное молча не передаём (иначе вызов падал бы с TypeError).
    """
    if not declared:
        return ()
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return tuple(declared)
    has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    accepted = []
    for item in declared:
        if has_kwargs or provides_kwarg(item) in params:
            accepted.append(item)
    return tuple(accepted)


def allowed_in_session(name, args, session_path) -> bool:
    """Опасное действие целиком внутри папки сессии — dangerous mode не нужен.

    Единый источник политики «внутри/вне сессии» для гейта `ToolManager.call_tool`
    и для TUI (окно переключения в dangerous mode). Классы опасности инструмент
    объявляет сам в манифесте (`danger`), поэтому политика не знает имён.
    """
    if not isinstance(args, dict) or not session_path:
        return False
    kinds = danger_kinds(name)
    if DANGER_SESSION_WRITE in kinds:
        action = editor_action_of(args) if name == "code_editor" else args.get("action")
        if action in (DANGEROUS_EDITOR_ACTIONS + DANGEROUS_FILESYSTEM_ACTIONS):
            if not path_within(session_path, resolve_session_path(args.get("path"), session_path)):
                return False
            if action in ("move", "copy", "symlink"):
                return path_within(session_path, resolve_session_path(args.get("dest"), session_path))
        return True
    if DANGER_SESSION_OUTPUT in kinds:
        out = args.get("output_path")
        return True if not out else path_within(session_path, resolve_session_path(out, session_path))
    # shell-подобные и всё необъявленное — всегда «вне сессии».
    return False


def requires_dangerous(name, args, session_path) -> bool:
    """True — вызов упрётся в гейт dangerous mode в `call_tool`.

    Тот же источник политики, что и гейт: используется, чтобы спросить
    пользователя ДО попытки выполнить опасное действие (headless-режим).
    """
    if not isinstance(args, dict):
        return False
    action = args.get("action")
    kinds = danger_kinds(name)
    if DANGER_SHELL in kinds:
        return (action or "run") in DANGEROUS_SHELL_ACTIONS
    if DANGER_SESSION_WRITE in kinds:
        gate_action = editor_action_of(args) if name == "code_editor" else action
        return (gate_action in (DANGEROUS_EDITOR_ACTIONS + DANGEROUS_FILESYSTEM_ACTIONS)
                and not allowed_in_session(name, args, session_path))
    if DANGER_SESSION_OUTPUT in kinds:
        return bool(args.get("output_path")) and not allowed_in_session(name, args, session_path)
    return False

def log_tool_error(tool_name, error_type, error_msg, traceback_str):
    """Логирует ошибку загрузки инструмента"""
    os.makedirs(os.path.dirname(TOOLS_LOG), exist_ok=True)
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "tool": tool_name,
        "error_type": error_type,
        "error": error_msg,
        "traceback": traceback_str
    }
    with open(TOOLS_LOG, "a") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

class ToolManager:
    def __init__(self, tools_dir=None):
        self.dangerous_mode = os.environ.get("BOTINOK_DANGEROUS", "0") == "1"
        self.tools = {}
        self.broken_tools = {}  # {name: {error_type, error, traceback}}
        self._loaded = set()    # какие уже пробовали загружать
        
        # Плагинные инструменты: папка tools/<name>/ с манифестом tool.json —
        # единственный контракт подключения (core/tool_discovery.py). Реестр и
        # схемы собираются сканированием, а не рукописными таблицами: положили
        # папку — инструмент появился, удалили — исчез из реестра, каталога и
        # payload; правок в ядре не требуется.
        self._tools_dir = tools_dir
        self._discovery = None
        self._loaded_module_names = {}  # name -> модуль (для горячего отключения)
        self._sync_discovery()

    def _sync_discovery(self):
        """Собрать реестр/схемы/состояние сломанных из папки инструментов.

        Если с прошлой синхронизации плагин изменился или исчез — сбрасываем
        закэшированный вызов (и модуль), чтобы правка/удаление папки действовали
        сразу, без перезапуска процесса. Сравнение — по отпечатку файлов плагина
        (`spec.stamp`), а не по идентичности объекта: иначе пересканирование
        из-за соседнего плагина выгружало бы все загруженные инструменты.
        """
        d = tool_discovery.discover(self._tools_dir)
        prev = getattr(self, "_spec_by_name", {})
        new_specs = {}
        for name, spec in d.specs.items():
            new_specs[name] = spec
            for alias in spec.aliases:
                new_specs[alias] = spec
        for name, old_spec in prev.items():
            new_spec = new_specs.get(name)
            if new_spec is old_spec or (new_spec is not None
                                        and new_spec.stamp == old_spec.stamp):
                continue
            # Инструмент исчез или его файлы изменились — старый вызов невалиден.
            self.tools.pop(name, None)
            self._loaded.discard(name)
            module = self._loaded_module_names.pop(name, None)
            if module:
                sys.modules.pop(module, None)
                # Подмодули плагина (from .helper import …) тоже кэшируются.
                for cached in [m for m in sys.modules if m.startswith(module + ".")]:
                    sys.modules.pop(cached, None)
            # Байткод .pyc инвалидируется по (секунды, размер) — правка кода
            # того же размера в ту же секунду осталась бы «старой». Для
            # горячей перезагрузки плагина сносим кэш явно.
            for source in tool_discovery.source_files(old_spec.path):
                try:
                    pyc = importlib.util.cache_from_source(source)
                    if os.path.isfile(pyc):
                        os.remove(pyc)
                except (OSError, ValueError, AttributeError):
                    pass
        self._spec_by_name = new_specs

        self._discovery = d
        self.broken_tools = {}
        self._tool_registry = {}
        self._descriptions = {}
        if d.error:
            # Скан не удался (нет папки/прав): это сломанная конфигурация, о ней
            # надо сказать громко, а не молча остаться без инструментов.
            self.broken_tools["tools/"] = {
                "error_type": "ToolsDirError",
                "error": d.error,
                "traceback": "",
            }
        for name, spec in d.specs.items():
            self._tool_registry[name] = (spec.module_path, spec.entry)
            if spec.schema:
                self._descriptions[name] = spec.schema
            if spec.load_error:
                self.broken_tools[name] = {
                    "error_type": spec.load_error_type or "PluginError",
                    "error": spec.load_error,
                    "traceback": "",
                }
            for alias in spec.aliases:
                self._tool_registry[alias] = (spec.module_path, spec.entry)
        # Папки-плагины, нарушившие контракт (битый манифест, нет README, …).
        for folder, reason in d.invalid.items():
            self.broken_tools[f"tools/{folder}/"] = {
                "error_type": "PluginContractError",
                "error": reason,
                "traceback": "",
            }

    def _refresh_if_stale(self):
        """Дёшево проверить, не изменилась ли папка инструментов.

        ``tool_discovery.discover`` возвращает тот же объект, пока штамп
        содержимого не изменился, поэтому проверка стоит один обход папки и не
        требует перезапуска: удалили/положили/поправили плагин — видно сразу.
        """
        try:
            if tool_discovery.discover(self._tools_dir) is not self._discovery:
                self._sync_discovery()
        except Exception:
            pass

    def rediscover(self):
        """Пересканировать папку инструментов: подключить/отключить плагины."""
        tool_discovery.clear_cache()
        self._sync_discovery()
        return self._tool_registry

    def _load_tool(self, name):
        """Загружает инструмент по требованию (lazy load)"""
        if name in self._loaded:
            return name in self.tools

        self._loaded.add(name)

        spec = self._discovery.by_name(name) if self._discovery else None
        if spec is None:
            return False

        try:
            func = spec.entry_func()

            self.tools[name] = {
                "function": func,
                "description": self._descriptions.get(name, {}),
                # Что из контекста реально принимает функция (проверка по
                # сигнатуре: манифест мог объявить лишнее, **kwargs — принять всё).
                "provides": _accepted_provides(func, spec.provides),
            }
            self._loaded_module_names[name] = spec.module_path
            return True

        except SyntaxError as e:
            tb = traceback.format_exc()
            error_msg = f"SyntaxError: {e}"
            self.broken_tools[name] = {
                "error_type": "SyntaxError",
                "error": error_msg,
                "traceback": tb
            }
            log_tool_error(name, "SyntaxError", error_msg, tb)
            return False
            
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"{type(e).__name__}: {e}"
            self.broken_tools[name] = {
                "error_type": type(e).__name__,
                "error": error_msg,
                "traceback": tb
            }
            log_tool_error(name, type(e).__name__, error_msg, tb)
            return False
    
    def get_tool(self, name):
        """Получить инструмент, загрузив если нужно"""
        if name in self.tools:
            return self.tools[name]
        
        try:
            self._load_tool(name)
        except SyntaxError as e:
            tb = traceback.format_exc()
            error_msg = f"SyntaxError: {e}"
            self.broken_tools[name] = {
                "error_type": "SyntaxError",
                "error": error_msg,
                "traceback": tb
            }
            log_tool_error(name, "SyntaxError", error_msg, tb)
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"{type(e).__name__}: {e}"
            self.broken_tools[name] = {
                "error_type": type(e).__name__,
                "error": error_msg,
                "traceback": tb
            }
            log_tool_error(name, type(e).__name__, error_msg, tb)
        
        return self.tools.get(name)
    
    def get_all_tools(self):
        """Получить все инструменты (загружает по требованию)"""
        for name in self._tool_registry:
            self.get_tool(name)
        return self.tools
    
    def get_all_descriptions(self):
        """Описания всех инструментов (включая сломанные с пометкой)"""
        self._refresh_if_stale()
        result = {}
        for name in self._tool_registry:
            desc = self._descriptions.get(name, {}).copy() if self._descriptions.get(name) else {}
            if name in self.broken_tools:
                # Добавляем инфу о том что инструмент сломан
                error_info = self.broken_tools[name]
                desc["broken"] = True
                desc["error_type"] = error_info["error_type"]
                desc["error_message"] = error_info["error"]
            # Не отдаем инструменты без валидной схемы (например алиасы) —
            # OpenAI-совместимые бэкенды отвергают их с ошибкой парсинга tools.
            if not (isinstance(desc, dict) and desc.get("type") == "function" and isinstance(desc.get("function"), dict)):
                continue
            result[name] = desc
        return result
    
    # Алиас для обратной совместимости
    def get_tool_definitions(self):
        """Тоже что get_all_descriptions()"""
        return self.get_all_descriptions()
    
    def get_broken_tools_info(self):
        """Информация о сломанных инструментах для агента"""
        if not self.broken_tools:
            return None
        
        info = "⚠️ **Сломанные инструменты обнаружены:**\n\n"
        for name, data in self.broken_tools.items():
            info += f"### `{name}`\n"
            info += f"- **Ошибка:** {data['error_type']}\n"
            info += f"- **Сообщение:** {data['error']}\n"
            info += f"- **Лог:** см. `~/.botinok/logs/tools.log`\n\n"
        
        info += "Агент может исправить инструменты изучив лог и исходный код."
        return info

    def call_tool(self, name, args=None, session_path=None, progress_callback=None):
        """Выполнить инструмент по имени.

        args может быть dict или JSON-строкой (как в tool_calls от моделей).
        session_path прокидывается в инструменты, которые его поддерживают (например code_editor).
        progress_callback используется для curl/web чтобы обновлять прогресс (скорость, найдено и т.п.).
        """
        if args is None:
            args = {}

        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except Exception as e:
                return f"Error: invalid JSON arguments for tool '{name}': {str(e)}"

        if not isinstance(args, dict):
            return f"Error: tool arguments must be an object/dict for tool '{name}'"

        if not name or not isinstance(name, str):
            return "Error: tool name is empty"

        # Папку могли удалить/положить прямо сейчас — сначала свериться с диском.
        self._refresh_if_stale()
        if name not in self._tool_registry:
            # Плагин могли положить в этом же ходе — пересканировать папку.
            self.rediscover()
        if name not in self._tool_registry:
            return f"Error: unknown tool '{name}'"

        # Опасные действия в простом режиме: разрешены только внутри папки сессии.
        # Классы опасности берём из манифеста плагина (`danger`), а не из имён —
        # сторонний плагин с shell-подобными действиями тоже упрётся в гейт.
        if not self.dangerous_mode:
            action = args.get("action") if isinstance(args, dict) else None
            gate_action = editor_action_of(args) if name == "code_editor" else action
            kinds = danger_kinds(name)
            if DANGER_SHELL in kinds and (action or "run") in DANGEROUS_SHELL_ACTIONS:
                msg = (f"Error: {name} action '{action or 'run'}' requires dangerous mode "
                       "(пользователь может разрешить переключение).")
                if _safe_ops is not None:
                    suggestion = _safe_ops.suggest_for_shell(
                        (args or {}).get("command", "") if isinstance(args, dict) else "")
                    if suggestion:
                        msg += (f"\nБезопасный эквивалент без dangerous mode: {suggestion}"
                                f"\nПолный список: file_system action=help")
                    else:
                        msg += f"\n{_safe_ops.catalog_short()}"
                return msg
            if (DANGER_SESSION_WRITE in kinds
                    and gate_action in (DANGEROUS_EDITOR_ACTIONS + DANGEROUS_FILESYSTEM_ACTIONS)
                    and not allowed_in_session(name, args, session_path)):
                return (f"Error: {name} action '{gate_action}' outside session requires dangerous mode "
                        "(пользователь может разрешить переключение)")
            if DANGER_SESSION_OUTPUT in kinds and isinstance(args, dict) and args.get("output_path") \
                    and not allowed_in_session(name, args, session_path):
                return (f"Error: {name} output_path outside session requires dangerous mode "
                        "(пользователь может разрешить переключение)")

        tool = self.get_tool(name)
        if not tool or "function" not in tool:
            if name in self.broken_tools:
                return f"Error: tool '{name}' is broken ({self.broken_tools[name].get('error_type')}): {self.broken_tools[name].get('error')}"
            return f"Error: tool '{name}' is not available"

        func = tool["function"]
        # Контекст передаём строго по контракту плагина (манифест `provides`,
        # отфильтрованный по сигнатуре при загрузке) — без списков имён в ядре.
        provided = tool.get("provides") or ()
        kwargs = dict(args)
        if session_path is not None and PROVIDES_SESSION in provided:
            kwargs[provides_kwarg(PROVIDES_SESSION)] = session_path
        if PROVIDES_PROGRESS in provided and progress_callback is not None:
            kwargs[provides_kwarg(PROVIDES_PROGRESS)] = progress_callback
        if PROVIDES_DANGEROUS in provided:
            kwargs[provides_kwarg(PROVIDES_DANGEROUS)] = self.dangerous_mode
        try:
            return func(**kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            log_tool_error(name, type(e).__name__, str(e), tb)
            return f"Error calling tool '{name}': {type(e).__name__}: {str(e)}"
