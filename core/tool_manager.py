import json
import os
import sys
import importlib
import traceback
from datetime import datetime

try:
    from tools import safe_ops as _safe_ops
except Exception:  # pragma: no cover
    _safe_ops = None

TOOLS_LOG = os.path.expanduser("~/.botinok/logs/tools.log")

DANGEROUS_FILESYSTEM_ACTIONS = ("delete", "move", "copy", "mkdir", "chmod", "symlink", "touch")
DANGEROUS_EDITOR_ACTIONS = ("write", "replace", "apply", "undo")
DANGEROUS_SHELL_ACTIONS = ("run", "send", "send_key", "kill", "wait")


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


def allowed_in_session(name, args, session_path) -> bool:
    """Опасное действие целиком внутри папки сессии — dangerous mode не нужен.

    Единый источник политики «внутри/вне сессии» для гейта `ToolManager.call_tool`
    и для TUI (окно переключения в dangerous mode).
    """
    if not isinstance(args, dict) or not session_path:
        return False
    if name == "code_editor":
        if editor_action_of(args) in DANGEROUS_EDITOR_ACTIONS:
            return path_within(session_path, args.get("path"))
        return True
    if name == "file_system":
        action = args.get("action")
        if action in DANGEROUS_FILESYSTEM_ACTIONS:
            if not path_within(session_path, args.get("path")):
                return False
            if action in ("move", "copy", "symlink"):
                return path_within(session_path, args.get("dest"))
            return True
        return True
    if name in ("curl", "web"):
        out = args.get("output_path")
        return True if not out else path_within(session_path, out)
    # shell_exec всегда опасен и не привязан к папке сессии.
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
    def __init__(self):
        self.dangerous_mode = os.environ.get("BOTINOK_DANGEROUS", "0") == "1"
        self.tools = {}
        self.broken_tools = {}  # {name: {error_type, error, traceback}}
        self._loaded = set()    # какие уже пробовали загружать
        
        # Регистрация инструментов: имя -> модуль.функция
        self._tool_registry = {
            "web": ("tools.web", "execute"),
            "web_search": ("tools.web_search", "ddg_search"),
            "open_url": ("tools.open_url", "open_url"),
            "web_extract": ("tools.web_extract", "web_extract"),
            "web_extractor": ("tools.web_extract", "web_extract"),  # alias для совместимости
            "file_system": ("tools.file_system", "file_system_tool"),
            "journal": ("tools.journal", "journal_tool"),
            "code_editor": ("tools.code_editor", "code_editor"),
            "shell_exec": ("tools.shell_exec", "shell_exec"),
            "experience": ("tools.experience", "experience"),
            "github": ("tools.github", "github"),
            "skills": ("tools.skills", "skills"),
            "curl": ("tools.curl", "curl"),
            "vision": ("tools.vision", "execute"),
            "audio": ("tools.audio", "execute"),
            "session_memory": ("tools.session_memory", "session_memory_tool"),
        }
        
        # Базовые описания (пока tool не загружен)
        self._descriptions = {
            "web": {
                "type": "function",
                "function": {
                    "name": "web",
                    "description": ("Единый добыватель данных из сети. Один инструмент вместо web_search/open_url/web_extract/curl. "
                                    "action: auto — сам выберет стратегию по типу данных; open — читаемый текст страницы; "
                                    "extract — структура (links/images/headings/meta/tables/css); json — JSON + jq-фильтр; "
                                    "download — скачать файл (aria2c, докачка, торренты/magnet, проверка sha256; память загрузок action=downloads); "
                                    "search — поиск в интернете; help — справка. "
                                    "Возвращает мета-данные, совет и следующие шаги. Запись вне папки сессии требует dangerous mode."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["auto", "open", "extract", "json", "download", "downloads", "search", "help"],
                                       "description": "Что сделать (по умолчанию auto). downloads — память загрузок (что/куда/целое)"},
                            "url": {"type": "string", "description": "URL http/https (для auto/open/extract/json/download)"},
                            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "description": "HTTP-метод (по умолчанию GET). Для API, требующих POST (например Ollama /api/generate), задай method=POST"},
                            "json_body": {"type": "object", "description": ("Тело запроса как JSON-объект (POST/PUT/PATCH) — для веб-API. "
                                           "Чтобы передать локальный файл без ручного base64, используй маркер "
                                           "{\"$file_base64\":\"/путь/к/файлу\"} — web сам прочитает и закодирует его "
                                           "(например в messages[].images для Ollama)")},
                            "body": {"type": "string", "description": "Тело запроса строкой (если не JSON)"},
                            "query": {"type": "string", "description": "Поисковый запрос (для action=search)"},
                            "extract": {"type": "array", "items": {"type": "string", "enum": ["links", "images", "headings", "meta", "tables", "all"]},
                                        "description": "Что извлекать (action=extract), по умолчанию all"},
                            "css": {"type": "array", "items": {"type": "string"}, "description": "CSS-селекторы для точечного извлечения (action=extract)"},
                            "jq": {"type": "string", "description": ("jq-фильтр (action=json). Применяется к ответу как к входу '.': "
                                       "'.daily', '.items[] | .name', '{temp: .current.temperature_2m}'. "
                                       "Выборка по условию: '.items[] | select(.value | startswith(\"2026\"))' "
                                       "(после 'as $x |' вход НЕ меняется — внутри select пиши '$x | ...', напр. "
                                       "select($x | startswith(\"…\"))). Ведущая точка не обязательна (добавится). "
                                       "Проще всего: сначала '.daily', потом уточняй; при ошибке jq вернётся её текст.")},
                            "output_path": {"type": "string", "description": "Куда сохранить файл (action=download; вне сессии — dangerous mode)"},
                            "resume": {"type": "boolean", "description": "Для download: докачать/перекачать (aria2c). Если файл уже цел — вернётся из глобальной памяти загрузок"},
                            "expected_sha256": {"type": "string", "description": "Для download: ожидаемый sha256 файла; при несовпадении файл удаляется и возвращается ошибка"},
                            "headers": {"type": "array", "items": {"type": "string"}, "description": "HTTP заголовки, формат 'Key: Value'"},
                            "timeout_sec": {"type": "integer", "description": "Таймаут в секундах (по умолчанию 30)"},
                            "max_bytes": {"type": "integer", "description": "Максимальный размер ответа в байтах"},
                            "follow_redirects": {"type": "boolean", "description": "Следовать за редиректами (по умолчанию true)"},
                            "max_items": {"type": "integer", "description": "Максимум элементов на категорию (action=extract/search)"}
                        },
                        "required": []
                    }
                }
            },
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
            "web_extract": {
                "type": "function",
                "function": {
                    "name": "web_extract",
                    "description": "Извлечь структурированные ресурсы со страницы: ссылки, картинки, заголовки, мета-теги, таблицы. Использует httpx + selectolax (быстрый парсер на C).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL страницы (http/https)"},
                            "extract": {"type": "array", "items": {"type": "string", "enum": ["links", "images", "headings", "meta", "tables", "all"]}, "description": "Что извлекать. По умолчанию ['all']"},
                            "max_items": {"type": "integer", "description": "Максимум элементов на категорию (по умолчанию 100)"},
                            "timeout_sec": {"type": "integer", "description": "Таймаут запроса в секундах (по умолчанию 15)"},
                            "headers": {"type": "array", "items": {"type": "string"}, "description": "HTTP заголовки (опционально, формат 'Key: Value')"}
                        },
                        "required": ["url"]
                    }
                }
            },
            "file_system": {
                "type": "function",
                "function": {
                    "name": "file_system",
                    "description": ("Файлы и система. Безопасные read-only действия работают всегда (везде): "
                                    "list/search/grep/read/info/find и inspect (fs.base64, fs.file_type, fs.stat, fs.count, "
                                    "fs.hash, fs.listing, fs.readlink, sys.*, proc.*, svc.*, net.*, git.*, image.meta, "
                                    "text.base64_decode). Подробности и примеры: action=help. "
                                    "Файловые мутации (delete/move/copy/mkdir/chmod/symlink/touch) разрешены внутри папки сессии "
                                    "(вне — dangerous_mode)."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["help", "list", "search", "grep", "read", "info", "inspect", "find", "delete", "move", "copy", "mkdir", "chmod", "symlink", "touch"],
                                "description": "help — каталог безопасных возможностей. Безопасные: list,search,grep,read,info,inspect,find. Мутации: delete,move,copy,mkdir,chmod,symlink,touch (внутри сессии без dangerous_mode)"
                            },
                            "path": {"type": "string", "description": "Исходный путь (для всех команд)"},
                            "dest": {"type": "string", "description": "Целевой путь (для move, copy, symlink)"},
                            "mode": {"type": "string", "description": "Права доступа в octal или символьном виде (для chmod, mkdir)"},
                            "command": {"type": "string", "description": "Подкоманда для action=inspect, напр. fs.base64, fs.file_type, fs.hash, net.ports, git.log, image.meta. Полный список: action=help"},
                            "algo": {"type": "string", "description": "Алгоритм для fs.hash: md5|sha1|sha256|sha512"},
                            "pattern": {"type": "string", "description": "Маска ИМЕНИ файла (glob, напр. *.py) для search/grep; по умолчанию *"},
                            "recursive": {"type": "boolean", "description": "Рекурсивно по подкаталогам (search/grep/inspect)"},
                            "content_query": {"type": "string", "description": "grep — regex по содержимому (регистронезависимо; path может быть файлом или каталогом; спецсимволы экранируй). search — если задан, ищет по содержимому. Также имя для net.dns/dev.which, ref для git.grep, base64 для text.base64_decode"},
                            "max_results": {"type": "integer"},
                            "max_bytes": {"type": "integer", "description": "Лимит вывода (для чтения/base64/ls)"},
                            "offset": {"type": "integer"},
                            "limit": {"type": "integer"}
                        },
                        "required": ["action"]
                    }
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
                    "description": ("Единый редактор файлов. action=read — чтение с пагинацией (offset/limit, line_numbers), "
                                    "возвращает sha256 и мету; action=write — полная запись (content, атомарно, сохраняет кодировку/EOL); "
                                    "action=replace — одна замена (old_text→new_text, replace_all); "
                                    "action=apply — несколько замен за вызов атомарно (edits=[{old_text,new_text}]); "
                                    "action=undo — откат последней правки из чекпоинта; action=help — справка. "
                                    "Инструмент прощает дрейф отступов и переводов строк (fuzzy) и сообщает ближайшее совпадение, "
                                    "если точного нет. Возвращает unified diff; устаревший файл (изменён вне сессии) отклоняется. "
                                    "Запись вне папки сессии требует dangerous mode."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["read", "write", "replace", "apply", "undo", "help"], "description": "Действие"},
                            "path": {"type": "string", "description": "Путь к файлу (в сессии относительный резолвится в session_path/project/)"},
                            "content": {"type": "string", "description": "Содержимое для action=write"},
                            "old_text": {"type": "string", "description": "Текст для замены (action=replace)"},
                            "new_text": {"type": "string", "description": "Новый текст (action=replace); пустая строка = удаление"},
                            "edits": {"type": "array", "items": {"type": "object", "properties": {"old_text": {"type": "string"}, "new_text": {"type": "string"}, "replace_all": {"type": "boolean"}}}, "description": "Список замен для action=apply (атомарно)"},
                            "replace_all": {"type": "boolean", "description": "Заменить все вхождения old_text (по умолчанию false)"},
                            "create": {"type": "boolean", "description": "Создавать файл если не существует (по умолчанию false)"},
                            "expected_sha256": {"type": "string", "description": "Ожидаемый SHA256 файла для проверки перед записью"},
                            "offset": {"type": "integer", "description": "Строка начала чтения (action=read, с 0)"},
                            "limit": {"type": "integer", "description": "Сколько строк читать (action=read; 0 = все)"},
                            "line_numbers": {"type": "boolean", "description": "Показывать номера строк при чтении"},
                            "checkpoint": {"type": "string", "description": "Путь чекпоинта для action=undo (иначе последний)"},
                            "force": {"type": "boolean", "description": "Для action=undo: откатить даже если файл изменился после правки"}
                        },
                        "required": ["action", "path"]
                    }
                }
            },
            "shell_exec": {
                "type": "function",
                "function": {
                    "name": "shell_exec",
                    "description": "Выполнение shell команд в отдельной PTY-сессии (dangerous mode). Сессия не держит агента: читай вывод через action=read/search, шлите ввод через action=send/send_key",
                    "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "Команда (для action=run)"}, "cwd": {"type": "string"}, "timeout_sec": {"type": "integer"}, "action": {"type": "string", "enum": ["run", "status", "read", "search", "send", "send_key", "wait", "kill", "list"], "description": "Действие над сессией (по умолчанию run)"}, "session_id": {"type": "string", "description": "ID сессии (из ответа action=run)"}, "input": {"type": "string", "description": "Текст ввода для action=send"}, "key": {"type": "string", "description": "Клавиша для action=send_key: enter, down, up, y, n, ctrl-c, ..."}, "pattern": {"type": "string", "description": "Строка/regex для action=search"}, "regex": {"type": "boolean"}, "context": {"type": "integer", "description": "Строк контекста вокруг match для action=search"}, "tail_lines": {"type": "integer", "description": "Сколько строк хвоста вывода вернуть"}, "wait_timeout": {"type": "number", "description": "Таймаут ожидания для action=wait"}, "interactive": {"type": "boolean", "description": "true — открыть встроенный экран терминала"}}, "required": []}
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
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "list",
                                    "get",
                                    "add",
                                    "remove",
                                    "run",
                                    "search",
                                    "clawhub",
                                    "install-clawhub"
                                ]
                            },
                            "name": {"type": "string"},
                            "query": {"type": "string"},
                            "url": {"type": "string"},
                            "content": {"type": "string"},
                            "task": {"type": "string"},
                            "limit": {"type": "integer"},
                            "sort": {"type": "string"}
                        },
                        "required": ["action"]
                    }
                }
            },
            "curl": {
                "type": "function",
                "function": {
                    "name": "curl",
                    "description": "Legacy-алиас web (HTTP-запросы, JSON, файлы). Поддерживает jq_filter, методы и тело запроса. Для новых задач используй web.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL (http/https)"},
                            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "description": "HTTP-метод (по умолчанию GET)"},
                            "body": {"type": "string", "description": "Тело запроса (строка); для JSON лучше json_body"},
                            "json_body": {"type": "object", "description": "Тело запроса как JSON-объект (для API: POST/PUT)"},
                            "headers": {"type": "array", "items": {"type": "string"}, "description": "HTTP заголовки, формат 'Key: Value'"},
                            "timeout_sec": {"type": "integer", "description": "Таймаут в секундах (по умолчанию 30)"},
                            "max_bytes": {"type": "integer", "description": "Максимальный размер ответа"},
                            "follow_redirects": {"type": "boolean", "description": "Следовать за редиректами (по умолчанию true)"},
                            "jq_filter": {"type": "string", "description": "Фильтр jq для обработки JSON. Примеры: .userId | .items[] | {name:.name}. ВАЖНО: без кавычек вокруг фильтра"},
                            "output_path": {"type": "string", "description": "Путь для сохранения ответа в файл (опционально, только внутри папки сессии без dangerous_mode)"},
                            "resume": {"type": "boolean", "description": "Докачать/перекачать файл (aria2c)"},
                            "expected_sha256": {"type": "string", "description": "Ожидаемый sha256 скачанного файла"}
                        },
                        "required": ["url"]
                    }
                }
            },
            "vision": {
                "type": "function",
                "function": {
                    "name": "vision",
                    "description": "Анализ изображений мультимодальной моделью. Конвертирует картинку в base64 для передачи в LLM (llava, bakllava и др.)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "image_path": {"type": "string", "description": "Путь к локальному файлу изображения (jpg, png, gif, webp)"},
                            "url": {"type": "string", "description": "URL изображения (альтернатива image_path)"},
                            "prompt": {"type": "string", "description": "Вопрос к модели про изображение (по умолчанию: 'Опиши что ты видишь')"},
                            "timeout_sec": {"type": "integer", "description": "Таймаут скачивания URL в секундах (по умолчанию 30)"}
                        },
                        "required": []
                    }
                }
            },
            "audio": {
                "type": "function",
                "function": {
                    "name": "audio",
                    "description": "Анализ аудио мультимодальной (omni) моделью. Конвертирует аудиофайл в base64 для передачи в LLM (Qwen3-Omni, Qwen3.5-Omni/27B и др.). Для работы нужна модель с поддержкой аудио.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "audio_path": {"type": "string", "description": "Путь к локальному аудиофайлу (wav, mp3, ogg, flac, m4a, webm)"},
                            "url": {"type": "string", "description": "URL аудио (альтернатива audio_path)"},
                            "prompt": {"type": "string", "description": "Вопрос к модели про аудио (по умолчанию: 'Опиши, что ты слышишь')"},
                            "timeout_sec": {"type": "integer", "description": "Таймаут скачивания URL в секундах (по умолчанию 30)"}
                        },
                        "required": []
                    }
                }
            },
            "session_memory": {
                "type": "function",
                "function": {
                    "name": "session_memory",
                    "description": "Протокольный доступ к истории сессии: точные timestamps, строгий порядок ходов (turn_id 1..N), полный текст сообщений и указатели на артефакты/инструменты. Основной инструмент для продолжения сессии и поиска в ней — НЕ читай context.json/response.md через file_system, здесь то же самое быстрее и с подсказками следующих шагов. Вызов: action=restore — ТОЧНОЕ восстановление контекста из снапшота (EXACT, можно доверять как есть); action=resume_brief — обзор для продолжения; get_turn(turn_id, include_content=true) — полный ход (DERIVED); search(query) — гибкий поиск (HINT, требует перепроверки); turns/timeline — последовательность; help — справка. В каждом ответе поле _confidence: EXACT | DERIVED | HINT — отличай точный результат от наметки. Синтаксис прощающий по формату: синонимы (brief/turn/list/find/exact), строковые числа, алиасы (q/id/full), пустой action → resume_brief; неизвестное действие → ambiguous=true со списком вариантов (смысл не подменяется). Поиск: регистр/пробелы не важны, части слов, кириллические окончания, выдаёт файл:строка и время. Каждый ответ содержит совет и блок «Следующие шаги».",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["resume_brief", "summary", "turns", "get_turn", "search", "filter", "timeline", "stats", "chain"],
                                "description": "resume_brief - быстрый сбор сессии для продолжения (задача, состояние, последние ходы), summary - сводка сессии, turns - список обменов, get_turn - конкретный turn, search - поиск по тексту, filter - фильтрация, timeline - хронология, stats - статистика, chain - цепочка turns"
                            },
                            "session_path": {"type": "string", "description": "Путь к сессии (опционально, по умолчанию текущая)"},
                            "turn_id": {"type": "integer", "description": "ID turn для get_turn"},
                            "query": {"type": "string", "description": "Строка поиска для search"},
                            "since": {"type": "string", "description": "Фильтр: начальное время (ISO format)"},
                            "until": {"type": "string", "description": "Фильтр: конечное время (ISO format)"},
                            "role": {"type": "string", "enum": ["user", "assistant", "system"], "description": "Фильтр по роли сообщения"},
                            "has_tool_calls": {"type": "boolean", "description": "Фильтр: только turns с tool_calls"},
                            "limit": {"type": "integer", "description": "Лимит результатов (по умолчанию 20)"},
                            "offset": {"type": "integer", "description": "Смещение для пагинации"},
                            "include_content": {"type": "boolean", "description": "Включать полный content (иначе только preview)"},
                            "include_thinking": {"type": "boolean", "description": "Включать полный thinking (иначе только preview)"}
                        },
                        "required": ["action"]
                    }
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
        progress_callback используется для curl чтобы обновлять прогресс скачивания.
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

        # Опасные действия в простом режиме: разрешены только внутри папки сессии.
        if not self.dangerous_mode:
            action = args.get("action") if isinstance(args, dict) else None
            gate_action = editor_action_of(args) if name == "code_editor" else action
            if name == "shell_exec" and (action or "run") in DANGEROUS_SHELL_ACTIONS:
                msg = (f"Error: shell_exec action '{action or 'run'}' requires dangerous mode "
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
            if (name in ("code_editor", "file_system")
                    and gate_action in (DANGEROUS_EDITOR_ACTIONS + DANGEROUS_FILESYSTEM_ACTIONS)
                    and not allowed_in_session(name, args, session_path)):
                return (f"Error: {name} action '{gate_action}' outside session requires dangerous mode "
                        "(пользователь может разрешить переключение)")
            if name in ("curl", "web") and isinstance(args, dict) and args.get("output_path") \
                    and not allowed_in_session(name, args, session_path):
                return (f"Error: {name} output_path outside session requires dangerous mode "
                        "(пользователь может разрешить переключение)")

        tool = self.get_tool(name)
        if not tool or "function" not in tool:
            if name in self.broken_tools:
                return f"Error: tool '{name}' is broken ({self.broken_tools[name].get('error_type')}): {self.broken_tools[name].get('error')}"
            return f"Error: tool '{name}' is not available"

        func = tool["function"]
        try:
            if session_path is not None:
                try:
                    # Для curl передаем progress_callback
                    if name == "curl" and progress_callback is not None:
                        return func(session_path=session_path, progress_callback=progress_callback, **args)
                    # Для file_system/code_editor передаем dangerous_mode
                    if name in ("file_system", "code_editor"):
                        return func(session_path=session_path, dangerous_mode=self.dangerous_mode, **args)
                    return func(session_path=session_path, **args)
                except TypeError:
                    return func(**args)
            # Для curl без session_path тоже передаем progress_callback
            if name == "curl" and progress_callback is not None:
                return func(progress_callback=progress_callback, **args)
            # Для file_system без session_path тоже передаем dangerous_mode
            if name == "file_system":
                return func(dangerous_mode=self.dangerous_mode, **args)
            return func(**args)
        except Exception as e:
            tb = traceback.format_exc()
            log_tool_error(name, type(e).__name__, str(e), tb)
            return f"Error calling tool '{name}': {type(e).__name__}: {str(e)}"
