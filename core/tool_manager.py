import json
from tools.web_search import ddg_search
from tools.open_url import open_url

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
            }
            ,
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
