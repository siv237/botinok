#!/usr/bin/env python3
"""Curl - HTTP GET запросы только для чтения (readonly-safe)

В режиме readonly:
- Только GET запросы (без POST/PUT/DELETE/PATCH)
- Без записи на диск (без -O, --output, перенаправления >)
- Без загрузки файлов
- Возвращает только текстовое содержимое ответа
"""

import subprocess
import shlex
import re
from typing import Optional


def curl(
    url: str,
    headers: Optional[list] = None,
    timeout_sec: int = 30,
    max_bytes: int = 256_000,
    follow_redirects: bool = True,
    jq_filter: Optional[str] = None,
) -> str:
    """
    Выполняет HTTP GET запрос (только чтение, readonly-safe).
    
    Args:
        url: URL для запроса (http/https)
        headers: Список заголовков (опционально)
        timeout_sec: Таймаут запроса в секундах
        max_bytes: Максимальный размер ответа
        follow_redirects: Следовать ли за редиректами (-L)
        jq_filter: Фильтр jq для обработки JSON (опционально, пример: '.items[] | .name')
    
    Returns:
        Текстовое содержимое ответа или результат jq фильтрации
    """
    if not url or not str(url).strip():
        return "Ошибка: URL пустой"
    
    # Проверка URL
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return f"Ошибка: URL должен начинаться с http:// или https:// (получено: {url[:50]}...)"
    
    # Блокировка опасных флагов если URL содержит их
    dangerous_patterns = [
        r"\s+-[oO]\s+",           # -o, -O (output to file)
        r"\s+--output\s+",        # --output
        r"\s*>\s+",                # перенаправление в файл
        r"\s*>>\s+",               # append перенаправление
        r"\s+-[T]\s+",            # -T (upload)
        r"\s+--upload-file\s+",    # --upload-file
        r"\s+-d\s+",              # -d (POST data)
        r"\s+--data\s+",           # --data
        r"\s+-X\s+(POST|PUT|DELETE|PATCH)",  # методы кроме GET
    ]
    url_lower = url.lower()
    for pattern in dangerous_patterns:
        if re.search(pattern, url_lower):
            return f"Ошибка: Обнаружена попытка записи или небезопасной операции. В режиме readonly curl только для чтения."
    
    # Базовая команда curl - только безопасные флаги
    cmd = ["curl", "-s"]
    
    if follow_redirects:
        cmd.append("-L")
    
    # Таймаут
    cmd.extend(["--connect-timeout", str(min(timeout_sec, 60)), "--max-time", str(min(timeout_sec, 120))])
    
    # Заголовки
    if headers:
        for header in headers:
            cmd.extend(["-H", str(header)])
    
    # URL
    cmd.append(url)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_sec
        )
        
        # Декодируем stdout с заменой невалидных байтов (для бинарных данных)
        output = result.stdout.decode('utf-8', errors='replace') if result.stdout else ""
        
        # Ограничение размера
        output_bytes = output.encode('utf-8')
        if len(output_bytes) > max_bytes:
            output = output_bytes[:max_bytes].decode('utf-8', errors='ignore') + "\n...[TRUNCATED_BY_MAX_BYTES]"
        
        if result.returncode != 0:
            stderr = result.stderr[:500] if result.stderr else ""
            return f"Ошибка curl (code {result.returncode}): {stderr}"
        
        # Применяем jq фильтр если указан
        if jq_filter and output.strip():
            try:
                # Нормализуем фильтр: добавляем точку в начало если её нет
                # Это позволяет писать 'userId' вместо '.userId'
                jq_filter = jq_filter.strip()
                if jq_filter and not jq_filter.startswith('.') and not jq_filter.startswith('[') and not jq_filter.startswith('{'):
                    # Проверяем что это не ключевое слово jq (def, import, include и т.п.)
                    jq_keywords = ('def ', 'import ', 'include ', 'module ', 'as ', 'if ', 'reduce ', 'foreach ')
                    if not any(jq_filter.startswith(kw) for kw in jq_keywords):
                        jq_filter = '.' + jq_filter
                
                # Проверка безопасности фильтра jq (блокируем попытки записи)
                dangerous_jq_patterns = [
                    r'@\s*\w+\s*"',  # @base64 "file", @uri "file" и т.п.
                    r'\$\w+\s*>',    # перенаправление в файл
                    r'\|\s*tee',    # tee для записи
                ]
                for pattern in dangerous_jq_patterns:
                    if re.search(pattern, jq_filter):
                        return f"Ошибка: jq фильтр содержит небезасную операцию записи"
                
                jq_cmd = ["jq", "-r", jq_filter]
                jq_result = subprocess.run(
                    jq_cmd,
                    input=output,
                    capture_output=True,
                    text=True,
                    timeout=min(timeout_sec, 30)
                )
                if jq_result.returncode == 0:
                    output = jq_result.stdout
                else:
                    jq_err = jq_result.stderr[:200] if jq_result.stderr else ""
                    return f"Ошибка jq: {jq_err}\n\nИсходный ответ:\n{output[:1000]}"
            except FileNotFoundError:
                return f"Ошибка: jq не установлен (требуется для фильтрации)\n\nИсходный ответ:\n{output[:1000]}"
            except subprocess.TimeoutExpired:
                return f"Ошибка: jq timeout\n\nИсходный ответ:\n{output[:1000]}"
            except Exception as e:
                return f"Ошибка jq ({str(e)})\n\nИсходный ответ:\n{output[:1000]}"
        
        return output
        
    except subprocess.TimeoutExpired:
        return f"Ошибка: timeout ({timeout_sec}s)"
    except FileNotFoundError:
        return "Ошибка: curl не найден в системе"
    except Exception as e:
        return f"Ошибка curl: {str(e)}"
