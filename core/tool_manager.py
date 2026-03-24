import json
import os
import sys
import importlib
import traceback
from datetime import datetime

TOOLS_LOG = os.path.expanduser("~/.botinok/logs/tools.log")

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
    def __init__(self):
        self.dangerous_mode = os.environ.get("BOTINOK_DANGEROUS", "0") == "1"
        self.tools = {}
        self.broken_tools = {}  # {name: {error_type, error, traceback}}
        self._loaded = set()    # какие уже пробовали загружать
        
        # Регистрация инструментов: имя -> модуль.функция
        self._tool_registry = {
            "web_search": ("tools.web_search", "ddg_search"),
            "open_url": ("tools.open_url", "open_url"),
            "file_system": ("tools.file_system", "file_system_tool"),
            "journal": ("tools.journal", "journal_tool"),
            "code_editor": ("tools.code_editor", "code_editor"),
            "shell_exec": ("tools.shell_exec", "shell_exec"),
            "experience": ("tools.experience", "experience"),
            "github": ("tools.github", "github"),
            "skills": ("tools.skills", "skills"),
        }
        
        # Базовые описания (пока tool не загружен)
        self._descriptions = {
            "web_search": {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Поиск информации в интернете через DuckDuckGo (использует lynx)",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Поисковый запрос"}}, "required": ["query"]}
                }
            },
            "open_url": {
                "type": "function",
                "function": {
                    "name": "open_url",
                    "description": "Открыть ссылку и извлечь текст со страницы (использует lynx -dump)",
                    "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "URL страницы (http/https)"}}, "required": ["url"]}
                }
            },
            "file_system": {
                "type": "function",
                "function": {
                    "name": "file_system",
                    "description": "Инструмент для работы с файловой системой",
                    "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "search", "grep", "read", "info", "inspect"]}, "path": {"type": "string"}}, "required": ["action"]}
                }
            },
            "journal": {
                "type": "function",
                "function": {
                    "name": "journal",
                    "description": "Read-only анализ systemd journal через journalctl",
                    "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["tail", "unit_tail", "since", "query", "stats"]}}, "required": ["action"]}
                }
            },
            "code_editor": {
                "type": "function",
                "function": {
                    "name": "code_editor",
                    "description": "Редактирование файлов (dangerous mode)",
                    "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["read", "write", "replace", "apply"]}, "path": {"type": "string"}}, "required": ["action", "path"]}
                }
            },
            "shell_exec": {
                "type": "function",
                "function": {
                    "name": "shell_exec",
                    "description": "Выполнение shell команд (dangerous mode)",
                    "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout_sec": {"type": "integer"}}, "required": ["command"]}
                }
            },
            "experience": {
                "type": "function",
                "function": {
                    "name": "experience",
                    "description": "База опыта работы",
                    "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["add_positive", "add_negative", "search", "list", "check"]}, "title": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["action"]}
                }
            },
            "github": {
                "type": "function",
                "function": {
                    "name": "github",
                    "description": "Работа с GitHub API",
                    "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["search_repos", "get_repo", "get_readme", "get_file", "get_tags", "get_branches"]}, "query": {"type": "string"}, "repo": {"type": "string"}}, "required": ["action"]}
                }
            },
            "skills": {
                "type": "function",
                "function": {
                    "name": "skills",
                    "description": "Менеджер AI скиллов",
                    "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "search", "get", "add", "remove", "install", "run"]}, "name": {"type": "string"}, "query": {"type": "string"}}, "required": ["action"]}
                }
            },
        }
    
    def _load_tool(self, name):
        """Загружает инструмент по требованию (lazy load)"""
        if name in self._loaded:
            return name in self.tools
        
        self._loaded.add(name)
        
        if name not in self._tool_registry:
            return False
        
        module_name, func_name = self._tool_registry[name]
        
        try:
            module = importlib.import_module(module_name)
            func = getattr(module, func_name)
            
            self.tools[name] = {
                "function": func,
                "description": self._descriptions.get(name, {})
            }
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
        result = {}
        for name in self._tool_registry:
            desc = self._descriptions.get(name, {}).copy() if self._descriptions.get(name) else {}
            if name in self.broken_tools:
                # Добавляем инфу о том что инструмент сломан
                error_info = self.broken_tools[name]
                desc["broken"] = True
                desc["error_type"] = error_info["error_type"]
                desc["error_message"] = error_info["error"]
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

    def call_tool(self, name, args=None, session_path=None):
        """Выполнить инструмент по имени.

        args может быть dict или JSON-строкой (как в tool_calls от моделей).
        session_path прокидывается в инструменты, которые его поддерживают (например code_editor).
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

        if name not in self._tool_registry:
            return f"Error: unknown tool '{name}'"

        if (not self.dangerous_mode) and name in ("shell_exec", "code_editor"):
            return f"Error: tool '{name}' requires dangerous mode"

        tool = self.get_tool(name)
        if not tool or "function" not in tool:
            if name in self.broken_tools:
                return f"Error: tool '{name}' is broken ({self.broken_tools[name].get('error_type')}): {self.broken_tools[name].get('error')}"
            return f"Error: tool '{name}' is not available"

        func = tool["function"]
        try:
            if session_path is not None:
                try:
                    return func(session_path=session_path, **args)
                except TypeError:
                    return func(**args)
            return func(**args)
        except Exception as e:
            tb = traceback.format_exc()
            log_tool_error(name, type(e).__name__, str(e), tb)
            return f"Error calling tool '{name}': {type(e).__name__}: {str(e)}"
