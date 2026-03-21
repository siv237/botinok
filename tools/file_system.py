import os
import glob
import fnmatch
from typing import List, Optional, Dict, Union

def file_system_tool(
    action: str,
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
    content_query: Optional[str] = None,
    max_results: int = 50,
    offset: int = 0,
    limit: int = 1000
) -> str:
    """
    Универсальный инструмент для работы с файловой системой.
    
    Actions:
    - list: Список файлов и директорий
    - search: Поиск файлов по имени/паттерну
    - grep: Поиск текста внутри файлов
    - read: Чтение содержимого файла с поддержкой пагинации
    - info: Получение метаданных о файле
    """
    try:
        if action == "list":
            return _list_dir(path)
        elif action == "search":
            return _search_files(path, pattern, recursive, max_results)
        elif action == "grep":
            return _grep_files(path, pattern, content_query, recursive, max_results)
        elif action == "read":
            return _read_file(path, offset, limit)
        elif action == "info":
            return _file_info(path)
        else:
            return f"Ошибка: Неизвестное действие '{action}'"
    except Exception as e:
        return f"Ошибка при выполнении {action}: {str(e)}"

def _list_dir(path: str) -> str:
    if not os.path.exists(path):
        return f"Путь не существует: {path}"
    
    items = []
    for item in os.listdir(path):
        full_path = os.path.join(path, item)
        is_dir = os.path.isdir(full_path)
        size = os.path.getsize(full_path) if not is_dir else "-"
        items.append(f"{'[DIR]' if is_dir else '[FILE]'} {item} ({size})")
    
    return "\n".join(items) if items else "Директория пуста"

def _search_files(path: str, pattern: str, recursive: bool, max_results: int) -> str:
    search_path = os.path.join(path, "**", pattern) if recursive else os.path.join(path, pattern)
    files = glob.glob(search_path, recursive=recursive)
    
    results = files[:max_results]
    output = [f"Найдено {len(files)} файлов (показано {len(results)}):"]
    output.extend(results)
    
    if len(files) > max_results:
        output.append(f"... и еще {len(files) - max_results} файлов")
    
    return "\n".join(output)

def _grep_files(path: str, pattern: str, query: str, recursive: bool, max_results: int) -> str:
    if not query:
        return "Ошибка: Параметр content_query обязателен для grep"
    
    search_path = os.path.join(path, "**", pattern) if recursive else os.path.join(path, pattern)
    files = [f for f in glob.glob(search_path, recursive=recursive) if os.path.isfile(f)]
    
    matches = []
    for file_path in files:
        if len(matches) >= max_results:
            break
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    if query.lower() in line.lower():
                        matches.append(f"{file_path}:{line_num}: {line.strip()}")
                        if len(matches) >= max_results:
                            break
        except Exception:
            continue
            
    return "\n".join(matches) if matches else "Совпадений не найдено"

def _read_file(path: str, offset: int, limit: int) -> str:
    if not os.path.isfile(path):
        return f"Файл не найден: {path}"
    
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            
        total_lines = len(lines)
        end = min(offset + limit, total_lines)
        content = "".join(lines[offset:end])
        
        header = f"--- Файл: {path} (строки {offset+1}-{end} из {total_lines}) ---\n"
        return header + content
    except Exception as e:
        return f"Ошибка чтения файла: {str(e)}"

def _file_info(path: str) -> str:
    if not os.path.exists(path):
        return f"Путь не существует: {path}"
    
    stat = os.stat(path)
    import datetime
    
    info = {
        "Path": os.path.abspath(path),
        "Size": f"{stat.st_size} bytes",
        "Created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "Modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "Is Directory": os.path.isdir(path)
    }
    
    return "\n".join([f"{k}: {v}" for k, v in info.items()])
