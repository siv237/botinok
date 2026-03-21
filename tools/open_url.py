import os
import subprocess
import sys
import time
import urllib.parse
import configparser

def open_url(url: str, session_path: str = None) -> str:
    print(f"DEBUG: Opening URL: {url}", file=sys.stderr)

    # Загружаем конфиг
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.cfg")
    if os.path.exists(config_path):
        config.read(config_path, encoding='utf-8')
    
    user_agent = config.get('Tools', 'LynxUserAgent', fallback="Mozilla/5.0 (Compatible; Lynx/2.8.9rel.1; Linux)")
    max_chars = config.getint('Tools', 'LynxMaxChars', fallback=8000)
    connect_timeout = config.getint('Tools', 'LynxConnectTimeout', fallback=6)
    read_timeout = config.getint('Tools', 'LynxReadTimeout', fallback=10)

    try:
        original_url = url.strip()
        parsed = urllib.parse.urlparse(original_url)

        # Нормализация: если схема не указана (например, www.example.com),
        # пробуем https:// как основной вариант.
        if not parsed.scheme:
            url_candidates = [f"https://{original_url}", f"http://{original_url}"]
        else:
            url_candidates = [original_url]

        # Проверяем схемы и корректность хоста
        validated_candidates = []
        for cand in url_candidates:
            p = urllib.parse.urlparse(cand)
            if p.scheme in {"http", "https"} and p.netloc:
                validated_candidates.append(cand)

        if not validated_candidates:
            return "Ошибка: поддерживаются только ссылки http/https и корректный хост"

        env = os.environ.copy()
        user_agent = "Mozilla/5.0 (Compatible; Lynx/2.8.9rel.1; Linux)"

        lynx_base_cmd = [
            "lynx",
            "-dump",
            "-number_links",
            "-display_charset=utf-8",
            "-useragent=" + user_agent,
        ]

        result = None
        timeouts = [connect_timeout, read_timeout]
        for url_index, cand_url in enumerate(validated_candidates, start=1):
            print(f"DEBUG: Trying URL: {cand_url}", file=sys.stderr)
            for attempt, t in enumerate(timeouts, start=1):
                try:
                    full_cmd = lynx_base_cmd + [f"-connect_timeout={t}", f"-read_timeout={t}", cand_url]
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

                print(f"DEBUG: Lynx finished with return code: {result.returncode}", file=sys.stderr)

                if result.returncode == 0:
                    break

                if attempt < len(timeouts) and result.stderr and "Не удается установить соединение" in result.stderr:
                    print("DEBUG: Connection failed, retrying in 0.5s...", file=sys.stderr)
                    time.sleep(0.5)
                    continue

                break

            if result and result.returncode == 0:
                break

            if url_index < len(validated_candidates):
                print("DEBUG: Switching to next URL candidate...", file=sys.stderr)

        # Сохраняем дамп lynx в сессию, если путь передан
        if session_path and result:
            timestamp = int(time.time())
            # Очищаем URL для имени файла
            safe_url = "".join([c if c.isalnum() else "_" for c in cand_url])[:50]
            filename = f"lynx_open_{timestamp}_{safe_url}.log"
            dump_path = os.path.join(session_path, filename)
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(f"URL: {cand_url}\n")
                f.write(f"Exit Code: {result.returncode}\n")
                f.write(f"STDERR:\n{result.stderr}\n")
                f.write(f"STDOUT:\n{result.stdout}\n")
            save_info = f"\n[Lynx dump saved to: {filename}]"
        else:
            save_info = ""

        if not result or result.returncode != 0:
            err_output = (result.stderr if result and result.stderr else "Unknown error")
            return f"Ошибка lynx (code {result.returncode if result else 'unknown'}): {err_output}{save_info}"

        content = result.stdout
        if not content or len(content.strip()) < 50:
            return f"Контент пустой или слишком короткий. Контент: {content[:200] if content else 'None'}{save_info}"

        lines = [line for line in content.split("\n") if line.strip()]
        cleaned_content = "\n".join(lines)
        return cleaned_content[:max_chars] + save_info

    except Exception as e:
        return f"Ошибка открытия ссылки: {str(e)}"
