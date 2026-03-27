import subprocess
import configparser
import os
import sys
import urllib.parse
import time

def _debug(msg: str):
    """Выводит отладочное сообщение если включен BOTINOK_DEBUG."""
    if os.environ.get("BOTINOK_DEBUG"):
        print(f"DEBUG: {msg}", file=sys.stderr)

def ddg_search(query: str, session_path: str = None) -> str:
    """
    Выполняет поиск в DuckDuckGo через lynx (HTML версия).
    """
    # Загружаем конфиг
    config = configparser.ConfigParser()
    # Конфиг лежит в корне проекта, а этот файл в /tools/
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.cfg")
    if os.path.exists(config_path):
        config.read(config_path, encoding='utf-8')
    
    user_agent = config.get('Tools', 'LynxUserAgent', fallback="Mozilla/5.0 (Compatible; Lynx/2.8.9rel.1; Linux)")
    max_chars = config.getint('Tools', 'LynxMaxChars', fallback=5000)
    connect_timeout = config.getint('Tools', 'LynxConnectTimeout', fallback=6)
    read_timeout = config.getint('Tools', 'LynxReadTimeout', fallback=10)

    _debug(f"Starting search for query: '{query}'")
    # Кодируем запрос для URL
    # Используем quote вместо quote_plus для более стандартного кодирования в URL
    encoded_query = urllib.parse.quote(query)
    # Пробуем сначала html.duckduckgo.com (без редиректа), затем duckduckgo.com (если первый недоступен)
    search_urls = [
        f"https://html.duckduckgo.com/html/?q={encoded_query}",
        f"https://duckduckgo.com/html/?q={encoded_query}",
    ]
    
    # Копируем текущее окружение
    env = os.environ.copy()
    
    try:
        lynx_base_cmd = [
            "lynx",
            "-dump",
            "-number_links",
            "-display_charset=utf-8",
            "-useragent=" + user_agent,
        ]

        result = None
        # Используем таймауты из конфига
        timeouts = [connect_timeout, read_timeout]
        
        for url_index, url in enumerate(search_urls, start=1):
            for attempt, t in enumerate(timeouts, start=1):
                try:
                    # Также отключаем куки через -cfg, чтобы избежать проблем с сессиями
                    full_cmd = lynx_base_cmd + [
                        f"-connect_timeout={t}",
                        f"-read_timeout={t}",
                        url
                    ]
                    _debug(f"Running command: {' '.join(full_cmd)}")
                    result = subprocess.run(
                        full_cmd,
                        capture_output=True,
                        text=True,
                        env=env,
                        timeout=t + 6,
                    )
                except subprocess.TimeoutExpired:
                    result = subprocess.CompletedProcess(
                        args=full_cmd,
                        returncode=124,
                        stdout="",
                        stderr=f"Lynx timeout after {t + 6}s",
                    )

                _debug(f"Lynx finished with return code: {result.returncode}")

                if result.returncode == 0:
                    break

                if attempt < len(timeouts) and result.stderr and "Не удается установить соединение" in result.stderr:
                    _debug("Connection failed, retrying in 0.5s...")
                    time.sleep(0.5)
                    continue

                break

            if result and result.returncode == 0:
                break

            if url_index < len(search_urls):
                _debug("Switching to fallback DDG host...")

        # Сохраняем дамп lynx в сессию, если путь передан
        if session_path and result:
            timestamp = int(time.time())
            filename = f"lynx_search_{timestamp}.log"
            dump_path = os.path.join(session_path, filename)
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(f"URL: {url}\n")
                f.write(f"Exit Code: {result.returncode}\n")
                f.write(f"STDERR:\n{result.stderr}\n")
                f.write(f"STDOUT:\n{result.stdout}\n")
            # Возвращаем информацию о сохраненном файле в результате для логов
            save_info = f"\n[Lynx dump saved to: {filename}]"
        else:
            save_info = ""

        if not result or result.returncode != 0:
            err_output = result.stderr if result and result.stderr else "Unknown error"
            _debug(f"Lynx error: {err_output}")
            return f"Ошибка lynx (code {result.returncode if result else 'unknown'}): {err_output}{save_info}"

        content = result.stdout
        if not content or len(content.strip()) < 100:
            _debug(f"Lynx returned suspicious content length: {len(content) if content else 0}")
            # Иногда DDG выдает страницу с капчей или блокировкой
            if "captcha" in content.lower() or "forbidden" in content.lower():
                return f"Ошибка: DuckDuckGo заблокировал запрос (CAPTCHA/Forbidden). Контент: {content[:200]}{save_info}"
            return f"Результаты поиска пусты или слишком коротки. Контент: {content[:200] if content else 'None'}{save_info}"

        # Очистка от пустых строк
        lines = [line for line in content.split('\n') if line.strip()]
        cleaned_content = '\n'.join(lines)
        
        _debug(f"Found {len(lines)} lines of content ({len(cleaned_content)} chars)")
        return cleaned_content[:max_chars] + save_info

    except Exception as e:
        _debug(f"Exception during search: {str(e)}")
        return f"Ошибка выполнения поиска: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(ddg_search(sys.argv[1]))
    else:
        print("Usage: python3 web_search.py 'query'")
