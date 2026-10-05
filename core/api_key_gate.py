# -*- coding: utf-8 -*-
"""API Key Gate: дружелюбная настройка ключа при ошибках авторизации.

Когда LLM-сервер отвечает 401/403 (ключ не задан, отозван, неверный),
ботинок не молча падает, а предлагает ввести ключ: в TUI — модальное
окошко с активной ссылкой на страницу выдачи ключа, в консоли — запрос
в терминале. Ключ сохраняется в персональный конфиг
``~/.config/botinok/config.cfg`` (наивысший приоритет, переживает
обновление пакета).
"""
import configparser
import os
import re
import sys

AUTH_STATUS_CODES = frozenset({401, 403})

# Признаки проблемы именно с ключом/аутентификацией в тексте ошибки
# (LiteLLM, OpenAI, vLLM, llama.cpp).
_KEY_PROBLEM_RE = re.compile(
    r"(no api key|api key|invalid.{0,20}(key|token)|missing.{0,20}(key|token)|"
    r"authentication|unauthorized|expired|revoked|not allowed|permission denied)",
    re.IGNORECASE,
)


def is_auth_error(status_code, error_text: str = "") -> bool:
    """True, если ответ сервера похож на проблему с API-ключом."""
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return False
    if code == 401:
        return True
    if code == 403:
        return bool(_KEY_PROBLEM_RE.search(error_text or ""))
    return False


def key_entry_url(sm) -> str:
    """Ссылка на страницу получения ключа.

    Берётся из ``[Ollama] KeyUrl``; если не задан — корень BaseUrl
    (обычно гейтвей и есть страница регистрации).
    """
    try:
        url = sm.config.get('Ollama', 'KeyUrl', fallback='').strip()
    except Exception:
        url = ''
    if url:
        return url
    try:
        base = sm.config.get('Ollama', 'BaseUrl', fallback='').strip()
    except Exception:
        base = ''
    m = re.match(r'(https?://[^/]+)', base or '')
    return (m.group(1) + '/') if m else ''


def save_api_key(sm, key: str) -> str:
    """Сохраняет ключ в персональный конфиг и в текущий конфиг-объект.

    Персональный (~/.config/botinok/config.cfg) имеет наивысший приоритет
    и не трогается при обновлении системного пакета. ВАЖНО: апстрим читает
    только ОДИН конфиг (персональный полностью заменяет системный), поэтому
    при создании персонального переносим в него весь текущий эффективный
    конфиг — иначе теряются BaseUrl/Backend/DefaultModel из пресета.
    Возвращает путь.
    """
    path = os.path.expanduser(os.path.join('~', '.config', 'botinok', 'config.cfg'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cp = configparser.ConfigParser()
    if os.path.exists(path):
        cp.read(path, encoding='utf-8')
    try:
        for sec in sm.config.sections():
            if not cp.has_section(sec):
                cp.add_section(sec)
            for k, v in sm.config.items(sec):
                if not cp.has_option(sec, k):
                    cp.set(sec, k, v)
    except Exception:
        pass
    if not cp.has_section('Ollama'):
        cp.add_section('Ollama')
    cp.set('Ollama', 'ApiKey', key)
    with open(path, 'w', encoding='utf-8') as f:
        cp.write(f)
    try:
        if not sm.config.has_section('Ollama'):
            sm.config.add_section('Ollama')
        sm.config.set('Ollama', 'ApiKey', key)
    except Exception:
        pass
    return path


def prompt_key_console(key_url: str = "", reason: str = ""):
    """Запрос ключа в обычном терминале (stealth/pipe, если stdin — TTY).

    Возвращает строку-ключ или None (не TTY / пустой ввод / Ctrl-D).
    """
    try:
        if not sys.stdin.isatty():
            return None
    except Exception:
        return None
    print("⚠ LLM-сервер запросил API-ключ." + (f" ({reason})" if reason else ""),
          file=sys.stderr)
    if key_url:
        print(f"  Получить ключ: {key_url}", file=sys.stderr)
    try:
        import getpass
        key = getpass.getpass("  Введите API-ключ (Enter — пропустить): ").strip()
    except Exception:
        return None
    return key or None
