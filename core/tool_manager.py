import json
import os
import sys
from tools.web_search import ddg_search
from tools.open_url import open_url
from tools.file_system import file_system_tool
from tools.journal import journal_tool
from tools.code_editor import code_editor
from tools.shell_exec import shell_exec

class ToolManager:
    def __init__(self):
        self.dangerous_mode = os.environ.get("BOTINOK_DANGEROUS", "0") == "1"
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
                                    "enum": ["list", "search", "grep", "read", "info", "inspect"],
                                    "description": "Действие: list (список), search (поиск по имени), grep (поиск текста), read (чтение), info (метаданные), inspect (read-only аналитика: fs/du/grep/log/sys/proc/service/journal)"
                                },
                                "path": {
                                    "type": "string",
                                    "description": "Путь к директории или файлу (по умолчанию '.')",
                                    "default": "."
                                },
                                "command": {
                                    "type": "string",
                                    "description": "Подкоманда для action='inspect' (например: fs.tree, du.dir_total, du.top_files, grep.regex, log.tail, sys.meminfo, proc.list, svc.status, journal.unit_tail)"
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
                                },
                                "depth": {
                                    "type": "integer",
                                    "description": "Глубина для fs.tree (inspect)",
                                    "default": 3
                                },
                                "sort": {
                                    "type": "string",
                                    "description": "Сортировка для list/inspect fs.list: name|size|mtime|type",
                                    "default": "name"
                                },
                                "reverse": {
                                    "type": "boolean",
                                    "description": "Реверс сортировки",
                                    "default": False
                                },
                                "max_bytes": {
                                    "type": "integer",
                                    "description": "Ограничение размера вывода (байт) для чтения/команд",
                                    "default": 256000
                                },
                                "pid": {
                                    "type": "integer",
                                    "description": "PID для proc.info (inspect)"
                                },
                                "unit": {
                                    "type": "string",
                                    "description": "systemd unit для svc.status/journal.unit_tail (inspect)"
                                },
                                "since": {
                                    "type": "string",
                                    "description": "journalctl --since значение для journal.since (inspect)"
                                },
                                "lines": {
                                    "type": "integer",
                                    "description": "Количество строк для tail/journal (inspect)",
                                    "default": 200
                                }
                            },
                            "required": ["action"]
                        }
                    }
                }
            },

            "journal": {
                "function": journal_tool,
                "description": {
                    "type": "function",
                    "function": {
                        "name": "journal",
                        "description": "Read-only анализ systemd journal через journalctl: tail/unit_tail/since/query/stats с фильтрами и лимитами вывода.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["tail", "unit_tail", "since", "query", "stats"],
                                    "description": "Действие: tail (последние строки), unit_tail (последние строки unit), since (с момента), query (tail/since + фильтры), stats (статистика уровней)"
                                },
                                "unit": {
                                    "type": "string",
                                    "description": "systemd unit (например ssh, docker, tor)"
                                },
                                "since": {
                                    "type": "string",
                                    "description": "journalctl --since значение (например '1 hour ago' или '2026-03-21 18:00:00')"
                                },
                                "until": {
                                    "type": "string",
                                    "description": "journalctl --until значение"
                                },
                                "lines": {
                                    "type": "integer",
                                    "description": "Сколько строк запрашивать у journalctl (-n)",
                                    "default": 200
                                },
                                "grep": {
                                    "type": "string",
                                    "description": "Фильтр подстрокой (case-insensitive) по полученному тексту"
                                },
                                "regex": {
                                    "type": "string",
                                    "description": "Фильтр regex (case-insensitive) по полученному тексту"
                                },
                                "priority": {
                                    "type": "string",
                                    "description": "journalctl -p priority (например err, warning, info, debug или 0..7)"
                                },
                                "boot": {
                                    "type": "integer",
                                    "description": "journalctl -b <boot> (0 текущий, -1 предыдущий и т.д.)"
                                },
                                "output": {
                                    "type": "string",
                                    "description": "journalctl -o формат (по умолчанию short-iso)",
                                    "default": "short-iso"
                                },
                                "max_bytes": {
                                    "type": "integer",
                                    "description": "Лимит размера вывода (байт)",
                                    "default": 256000
                                },
                                "max_lines": {
                                    "type": "integer",
                                    "description": "Лимит количества строк после фильтрации",
                                    "default": 500
                                }
                            },
                            "required": ["action"]
                        }
                    }
                }
            },

            "code_editor": {
                "function": code_editor,
                "description": {
                    "type": "function",
                    "function": {
                        "name": "code_editor",
                        "description": "ОПАСНО (только dangerous-mode): чтение/запись/точечная замена текста в файлах внутри проекта. Поддерживает expected_sha256 для защиты от гонок.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["read", "write", "replace", "apply"],
                                    "description": "read (прочитать), write (перезаписать), replace/apply (заменить old_text на new_text ровно 1 раз)"
                                },
                                "path": {"type": "string", "description": "Путь к файлу (только внутри project root)"},
                                "content": {"type": "string", "description": "Новый контент для write"},
                                "old_text": {"type": "string", "description": "Фрагмент для replace/apply (должен встретиться ровно 1 раз)"},
                                "new_text": {"type": "string", "description": "Новый фрагмент для replace/apply"},
                                "create": {"type": "boolean", "description": "Разрешить создание нового файла", "default": false},
                                "expected_sha256": {"type": "string", "description": "Если задано — операция разрешена только если sha256 текущего файла совпадает"},
                                "max_bytes": {"type": "integer", "description": "Ограничение на размер файла/контента", "default": 2000000}
                            },
                            "required": ["action", "path"]
                        }
                    }
                }
            },

            "shell_exec": {
                "function": shell_exec,
                "description": {
                    "type": "function",
                    "function": {
                        "name": "shell_exec",
                        "description": "ОПАСНО (только dangerous-mode): выполнить shell-команду. Перед выполнением требуется подтверждение пользователя в интерактивном режиме.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Команда для выполнения"},
                                "cwd": {"type": "string", "description": "Рабочая директория (по умолчанию project root)"},
                                "timeout_sec": {"type": "integer", "description": "Timeout выполнения", "default": 120},
                                "max_bytes": {"type": "integer", "description": "Лимит вывода (байты)", "default": 256000}
                            },
                            "required": ["command"]
                        }
                    }
                }
            }
        }

    def get_tool_definitions(self):
        """Возвращает список определений инструментов для Ollama API"""
        if self.dangerous_mode:
            return [tool["description"] for tool in self.tools.values()]
        safe = []
        for name, tool in self.tools.items():
            if name in ("code_editor", "shell_exec"):
                continue
            safe.append(tool["description"])
        return safe

    def call_tool(self, name, arguments, session_path=None):
        """Вызывает инструмент по имени с переданными аргументами"""
        if name in self.tools:
            tool_func = self.tools[name]["function"]
            try:
                if name in ("code_editor", "shell_exec") and not self.dangerous_mode:
                    return "Ошибка: dangerous-mode выключен. Запусти бота с флагом --dangerous чтобы разрешить изменения."

                if name == "shell_exec":
                    if not sys.stdin.isatty():
                        return "Ошибка: shell_exec запрещен без интерактивного TTY (нужно подтверждение пользователя)."
                    cmd_preview = ""
                    try:
                        cmd_preview = arguments.get("command", "")
                    except Exception:
                        cmd_preview = ""
                    print("\nBOTINOK shell_exec запрос на выполнение:")
                    print(cmd_preview)
                    ans = input("\nВыполнить? (y/N): ")
                    if str(ans).strip().lower() not in ("y", "yes", "д", "да"):
                        return "Отменено пользователем."

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
