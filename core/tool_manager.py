import json
from tools.web_search import ddg_search
from tools.open_url import open_url
from tools.file_system import file_system_tool

class ToolManager:
    def __init__(self):
        self.tools = {
            "web_search": {
                "function": ddg_search,
                "description": {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Поиск информации в интернете через DuckDuckGo (использует lynx)",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Поисковый запрос"
                                }
                            },
                            "required": ["query"]
                        }
                    }
                }
            },
            "open_url": {
                "function": open_url,
                "description": {
                    "type": "function",
                    "function": {
                        "name": "open_url",
                        "description": "Открыть ссылку и извлечь текст со страницы (использует lynx -dump)",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "URL страницы (http/https)"
                                }
                            },
                            "required": ["url"]
                        }
                    }
                }
            },
            "file_system": {
                "function": file_system_tool,
                "description": {
                    "type": "function",
                    "function": {
                        "name": "file_system",
                        "description": "Инструмент для работы с файловой системой: листинг, поиск файлов, поиск текста (grep), чтение файлов и получение метаданных.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["list", "search", "grep", "read", "info"],
                                    "description": "Действие: list (список), search (поиск по имени), grep (поиск текста), read (чтение), info (метаданные)"
                                },
                                "path": {
                                    "type": "string",
                                    "description": "Путь к директории или файлу (по умолчанию '.')",
                                    "default": "."
                                },
                                "pattern": {
                                    "type": "string",
                                    "description": "Паттерн для поиска (например, '*.py' или 'config*')",
                                    "default": "*"
                                },
                                "recursive": {
                                    "type": "boolean",
                                    "description": "Рекурсивный поиск в поддиректориях",
                                    "default": False
                                },
                                "content_query": {
                                    "type": "string",
                                    "description": "Текст для поиска внутри файлов (используется только для action='grep')"
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "Максимальное количество результатов (по умолчанию 50)",
                                    "default": 50
                                },
                                "offset": {
                                    "type": "integer",
                                    "description": "Смещение строк для чтения (по умолчанию 0)",
                                    "default": 0
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Количество строк для чтения (по умолчанию 1000)",
                                    "default": 1000
                                }
                            },
                            "required": ["action"]
                        }
                    }
                }
            }
        }

    def get_tool_definitions(self):
        """Возвращает список определений инструментов для Ollama API"""
        return [tool["description"] for tool in self.tools.values()]

    def call_tool(self, name, arguments, session_path=None):
        """Вызывает инструмент по имени с переданными аргументами"""
        if name in self.tools:
            tool_func = self.tools[name]["function"]
            try:
                # Если передан session_path, передаем его в инструмент (если он его поддерживает)
                if session_path:
                    import inspect
                    sig = inspect.signature(tool_func)
                    if 'session_path' in sig.parameters:
                        arguments['session_path'] = session_path
                
                # Аргументы приходят как словарь из JSON
                result = tool_func(**arguments)
                return str(result)
            except Exception as e:
                return f"Ошибка при вызове инструмента {name}: {str(e)}"
        return f"Инструмент {name} не найден"
