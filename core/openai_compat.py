# -*- coding: utf-8 -*-
"""Адаптер OpenAI-совместимых API (llama-server, vLLM, OpenAI и т.д.) для botinok.

Включается в config.cfg:

    [Ollama]
    backend = openai
    baseurl = http://192.168.237.131:8080

При backend = openai все запросы идут на {baseurl}/v1/chat/completions,
стрим конвертируется из SSE в формат Ollama /api/chat на лету.
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests


def is_openai_backend(sm):
    try:
        return sm.config.get('Ollama', 'Backend', fallback='ollama').strip().lower() in ('openai', 'openai-compatible')
    except Exception:
        return False


# Единственный захардкоженный режим — клиентский auto: не отправлять параметр.
REASONING_AUTO = 'auto'


def _chat_probe_status(path, api_key, model, verify=True, timeout=15):
    """Статус реального chat-запроса к модели (max_tokens=1) или None при
    сетевой ошибке."""
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    try:
        r = requests.post(path, headers=headers, verify=verify, timeout=timeout,
                          json={'model': model,
                                'messages': [{'role': 'user', 'content': '.'}],
                                'max_tokens': 1})
        return r.status_code
    except Exception:
        return None


def classify_chat_models(backend, url, api_key, entries, verify=True):
    """Определяет совместимость моделей с ботинком (чат-LLM) по ФАКТИЧЕСКОМУ
    типу, а не по именам:

    - Ollama: собственные capabilities сервера (embedding-модели не имеют
      'completion') — авторитетно, без запросов;
    - OpenAI-совместимые: объявленные mode/type врут (litellm пишет 'chat'
      и эмбеддингам), поэтому каждая модель проверяется настоящим чат-запросом
      (max_tokens=1): 200 — чат, 4xx «does not support chat/generate» — не чат.
      Сетевые сбои модель не исключают (chat=True).

    Каждой записи добавляется флаг 'chat'."""
    out = []
    for e in (entries or []):
        ent = dict(e) if isinstance(e, dict) else {'id': str(e)}
        caps = ent.get('capabilities')
        if isinstance(caps, list) and caps:
            ent['chat'] = any(c in caps for c in ('completion', 'tools', 'thinking'))
        out.append(ent)
    if backend not in ('openai', 'openai-compatible'):
        return out
    need = [e for e in out if 'chat' not in e and e.get('id')]
    if not need:
        return out
    base = (url or '').rstrip('/')
    paths = []
    if base.endswith('/v1'):
        paths.append(f"{base}/chat/completions")
    paths.append(f"{base}/v1/chat/completions")
    paths.append(f"{base}/chat/completions")
    # Найти рабочий путь на первой модели (404 = путь неверный).
    path = None
    first_st = None
    for p in dict.fromkeys(paths):
        st = _chat_probe_status(p, api_key, need[0]['id'], verify)
        if st in (200, 400, 422):
            path, first_st = p, st
            break
    if path is None:
        for e in need:
            e['chat'] = True  # сервер недоступен — не исключаем вслепую
        return out
    # Параллельно: при десятках моделей последовательный перебор с
    # таймаутами выглядит как зависание мастера.
    def _probe(item):
        i, e = item
        return i, (first_st if i == 0
                   else _chat_probe_status(path, api_key, e['id'], verify, timeout=10))

    with ThreadPoolExecutor(max_workers=min(8, len(need))) as pool:
        for i, st in pool.map(_probe, list(enumerate(need))):
            e = need[i]
            e['chat'] = (st == 200) if st in (200, 400, 422) else True
    return out


def filter_chat_models(entries):
    """Оставить только chat-совместимые (по флагу classify_chat_models /
    capabilities). Если фильтр не оставил ничего — отдаём исходный список."""
    entries = list(entries or [])
    kept = [e for e in entries if (e.get('chat', True) if isinstance(e, dict) else True)]
    return kept or entries
# Служебные слова перечислений API, не являющиеся уровнями.
_REASONING_STOP = {'and', 'or', 'the', 'of', 'following', 'value', 'values',
                   'type', 'types', 'expected', 'input', 'default', 'one',
                   'ctx', 'msg', 'loc', 'error', 'code', 'param', 'null'}


def parse_reasoning_error(text):
    """Разбирает сообщение API об ошибочном значении рассуждения: возвращает
    (уровни, дефолт_или_None). Список НЕ захардкожен — берутся значения,
    которые API сам перечислил, чтобы поддержать уровни, которых ещё не
    существует. Значения в кавычках — исчерпывающий перечень; голые слова
    разбираются только как элементы списка (запятые/and/or) и на первом
    же мусоре перечисление обрывается — хвост JSON-ошибки в список не
    попадает. true/false (Ollama) отображаются в on/none. Единственный
    хардкод — auto (клиентский режим «не отправлять»)."""
    import re as _re
    # Экранированные кавычки JSON-обёртки (\"high\") иначе рвут пары кавычек.
    tl = (text or '').lower().replace('\\"', '"')
    seg = None
    # Разбираем только перечисление после маркера — иначе в список попадает
    # само зондируемое значение, которое API эхом возвращает в начале сообщения.
    for marker in ('one of:', 'supported types are', 'must be', 'should be',
                   'valid values'):
        i = tl.find(marker)
        if i != -1:
            seg = tl[i + len(marker):]
            break
    if seg is None:
        return [], None
    levels = []
    default = None
    tok_re = _re.compile(r'^[a-z][a-z0-9_-]{1,15}$')
    quoted = [m.group(1) or m.group(2)
              for m in _re.finditer(r"'([^']+)'|\"([^\"]+)\"", seg)]
    # Кавычки допустимы только как настоящий перечень: если ни один
    # кавычный токен не похож на имя уровня (JSON-обёртка ошибки тоже
    # полна кавычек), кавычному перечню не верим — разбираем без кавычек.
    quoted_ok = []
    for tok in quoted + _re.findall(r'\b(?:true|false)\b', seg):
        tok = {'false': 'none', 'true': 'on'}.get(tok, tok)
        if tok_re.match(tok) and tok not in _REASONING_STOP and tok not in quoted_ok:
            quoted_ok.append(tok)
    if quoted_ok:
        levels = quoted_ok
        m = _re.search(r"['\"]?([a-z][a-z0-9_-]{1,15})['\"]?\s*\(default\)", seg)
        if m and m.group(1) in levels:
            default = m.group(1)
    else:
        # Перечисление без кавычек: «xhigh (default), medium, and low..».
        for part in _re.split(r',|\band\b|\bor\b', seg):
            part = part.strip().strip('.').strip()
            if not part:
                continue  # пустые куски от «, and» — не конец списка
            m = _re.match(r'^([a-z][a-z0-9_-]{1,15})(\s*\(default\))?$', part)
            if not m:
                # Последний элемент списка часто склеен с хвостом ошибки
                # точками: «low.. received model group=…» — берём токен и
                # останавливаемся: после точек перечисления нет.
                m = _re.match(r'^([a-z][a-z0-9_-]{1,15})(\s*\(default\))?\.', part)
                if not m:
                    break
                tok = m.group(1)
                if tok not in levels and tok not in _REASONING_STOP:
                    levels.append(tok)
                if '(default)' in part:
                    default = tok
                break
            tok = m.group(1)
            if tok in _REASONING_STOP:
                continue
            if tok not in levels:
                levels.append(tok)
            if '(default)' in part:
                default = tok
    return levels, default


def probe_reasoning(backend, url, api_key, model, verify=True):
    """Определяет реально поддерживаемые данной моделью уровни рассуждения.

    Двухступенчатый зонд, потому что «поддержка» бывает на двух слоях:
    валидатор прокси может принимать значение синтаксически (например
    'minimal'), а группа моделей отклонять его на исполнении. Шаг 1 —
    заведомо неверное значение: ответ 400 даёт синтаксический перечень
    кандидатов. Шаг 2 — каждое кандидатное значение отправляется НА САМОМ
    СЕБЕ (max_tokens=1, генерация ничтожна): 200 — уровень действительно
    работает, 400 — нет, а текст 400 даёт авторитетный список уровня
    моделей и пометку (default). Итог — объединение подтверждённых 200 и
    названных 400; порядок — как в перечне API.

    Возвращает {'levels': [...], 'default': str|None}; levels пуст, если
    API принимает любое значение молча; None, если данных получить не
    удалось. Отсутствие настройки — не ошибка, а дефолт auto."""
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    def _ask(path, value, stream_off=False):
        pl = {'model': model,
              'messages': [{'role': 'user', 'content': '.'}],
              'max_tokens': 1}
        if stream_off:
            pl['stream'] = False
        pl['reasoning_effort'] = value
        return requests.post(path, headers=headers, verify=verify, timeout=15, json=pl)

    if backend in ('openai', 'openai-compatible'):
        base = (url or '').rstrip('/')
        paths = []
        if base.endswith('/v1'):
            paths.append(f"{base}/chat/completions")
        paths.append(f"{base}/v1/chat/completions")
        paths.append(f"{base}/chat/completions")
        for path in dict.fromkeys(paths):
            try:
                r = _ask(path, '__probe__')
            except Exception:
                continue
            if r.status_code == 200:
                # Прокси молча принимает всё — реальный перечень неизвестен.
                return {'levels': [], 'default': None}
            if r.status_code != 400:
                continue
            candidates, default = parse_reasoning_error(r.text)
            if not candidates:
                continue
            # Шаг 2: проверяем каждый кандидат на самой модели. В список
            # поддержки попадают ТОЛЬКО значения, подтверждённые ответом
            # 200; текст 400 используется лишь для пометки дефолта.
            supported, model_default = [], default
            for cand in candidates:
                try:
                    r2 = _ask(path, cand)
                except Exception:
                    continue
                if r2.status_code == 200:
                    supported.append(cand)
                elif r2.status_code == 400:
                    _, dflt = parse_reasoning_error(r2.text)
                    if dflt:
                        model_default = dflt
            if model_default not in supported:
                model_default = None
            return {'levels': supported, 'default': model_default}
        return None
    try:
        r = requests.post(f"{(url or '').rstrip('/')}/api/chat", headers=headers,
                          verify=verify, timeout=15, json={
                              'model': model,
                              'messages': [{'role': 'user', 'content': '.'}],
                              'stream': False,
                              'options': {'num_predict': 1},
                              'think': '__probe__',
                          })
        if r.status_code == 400:
            levels, default = parse_reasoning_error(r.text)
            return {'levels': levels, 'default': default}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Кэш определённых уровней рассуждения: медленный зонд (проверка каждого
# значения на модели) выполняется один раз, результат хранится на диске
# рядом с config.cfg и мгновенно питает визард и горячее меню в TUI.
# ---------------------------------------------------------------------------

_REASONING_CACHE_TTL = 30 * 24 * 3600  # месяц; устаревание лечится рантайм-фолбэком


def _reasoning_cache_path(sm):
    cfg = getattr(sm, 'config_path', None) or os.path.expanduser('~/.config/botinok/config.cfg')
    return os.path.join(os.path.dirname(cfg) or '.', 'reasoning_cache.json')


def reasoning_cache_key(backend, url, model):
    return f"{backend}|{(url or '').rstrip('/')}|{model}"


def load_cache_entry(sm, key, ttl=_REASONING_CACHE_TTL):
    """Общая запись кэша (reasoning_cache.json) по ключу или None."""
    try:
        with open(_reasoning_cache_path(sm), encoding='utf-8') as f:
            data = json.load(f)
        ent = data.get(key)
        if not isinstance(ent, dict):
            return None
        if time.time() - float(ent.get('ts', 0)) > ttl:
            return None
        return ent
    except Exception:
        return None


def save_cache_entry(sm, key, payload):
    try:
        path = _reasoning_cache_path(sm)
        data = {}
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data[key] = dict(payload)
        data[key]['ts'] = time.time()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def load_reasoning_cache(sm, key):
    """Закэшированный {'levels', 'default'} по ключу или None."""
    ent = load_cache_entry(sm, key)
    if not isinstance(ent, dict) or 'levels' not in ent:
        return None
    return {'levels': list(ent.get('levels') or []), 'default': ent.get('default')}


def save_reasoning_cache(sm, key, info):
    save_cache_entry(sm, key, {
        'levels': list((info or {}).get('levels') or []),
        'default': (info or {}).get('default'),
    })


def probe_reasoning_cached(sm, backend, url, api_key, model, verify=True, force=False):
    """probe_reasoning с дисковым кэшем: быстрый путь для визарда и меню."""
    key = reasoning_cache_key(backend, url, model)
    if not force:
        cached = load_reasoning_cache(sm, key)
        if cached is not None:
            return cached
    info = probe_reasoning(backend, url, api_key, model, verify=verify)
    if info is not None:
        save_reasoning_cache(sm, key, info)
    return info


def get_reasoning_effort(sm):
    """Настроенный уровень рассуждения или None (= auto, параметр не шлём)."""
    try:
        eff = (sm.config.get('Ollama', 'ReasoningEffort', fallback='auto') or '').strip().lower()
    except Exception:
        return None
    return eff if eff and eff != 'auto' else None


def apply_native_think(sm, payload):
    """Для нативного Ollama /api/chat: добавляет 'think' по настройке.

    none -> false, on/true -> true, low/medium/high/max -> строка-уровень.
    При auto (не задано) payload не меняется — текущее поведение.
    """
    eff = get_reasoning_effort(sm)
    if eff is None:
        return payload
    if eff == 'none':
        payload['think'] = False
    elif eff in ('on', 'true'):
        payload['think'] = True
    else:
        payload['think'] = eff
    return payload


def _api_url(sm, path='/v1/chat/completions'):
    base = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434').rstrip('/')
    return f"{base}{path}"


def _api_headers(sm, extra=None):
    headers = {'Content-Type': 'application/json'}
    api_key = sm.config.get('Ollama', 'ApiKey', fallback='').strip()
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    if extra:
        headers.update(extra)
    return headers


def _parse_tool_args(raw):
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {'_raw': raw}


def to_openai_messages(messages):
    out = []
    counter = 0
    for m in messages:
        role = m.get('role')
        if role not in ('system', 'user', 'assistant', 'tool'):
            continue
        msg = {'role': role}
        content = m.get('content')
        if isinstance(content, list):
            content = ' '.join(
                p.get('text', '') for p in content if isinstance(p, dict)
            )
        # Мультимодальный контент: аудио (input_audio) или изображения (image_url).
        # Нативный Ollama-транспорт для аудио — поле `audios` (base64 WAV, см. PR #15243);
        # здесь по маркеру media_kind распознаём его и переводим в OpenAI-формат.
        images = m.get('images') or []
        audios = m.get('audios') or []
        if m.get('media_kind') == 'audio' and audios:
            msg['content'] = [
                {'type': 'text', 'text': content or ''},
                {
                    'type': 'input_audio',
                    'input_audio': {
                        'data': audios[0],
                        'format': 'wav',
                    },
                },
            ]
        elif images:
            parts = [{'type': 'text', 'text': content or ''}]
            for img in images:
                parts.append({
                    'type': 'image_url',
                    'image_url': {
                        'url': f"data:{m.get('mime_type', 'image/jpeg')};base64,{img}"
                    },
                })
            msg['content'] = parts
        else:
            msg['content'] = content or ''
        if role == 'assistant' and m.get('tool_calls'):
            tcs = []
            for tc in m['tool_calls']:
                fn = tc.get('function', {}) or {}
                args = fn.get('arguments', {})
                if not isinstance(args, str):
                    args = json.dumps(args or {}, ensure_ascii=False)
                counter += 1
                tcs.append({
                    'id': tc.get('id') or f'call_{counter}',
                    'type': 'function',
                    'function': {'name': fn.get('name'), 'arguments': args},
                })
            msg['tool_calls'] = tcs
        if role == 'tool':
            if m.get('tool_call_id'):
                msg['tool_call_id'] = m['tool_call_id']
            if m.get('name'):
                msg['name'] = m['name']
        # Поле thinking в историю OpenAI API не передается
        out.append(msg)
    return out


def _to_openai_payload(ollama_payload, sm=None):
    msgs = to_openai_messages(ollama_payload.get('messages', []))
    # Многие шаблоны чата (Qwen и др.) допускают только один system-блок
    # в начале. Склеиваем все системные сообщения в одно.
    system_parts = [m['content'] for m in msgs
                    if m.get('role') == 'system' and m.get('content')]
    if len(system_parts) > 1:
        merged = "\n\n".join(system_parts)
        msgs = ([{'role': 'system', 'content': merged}] +
                [m for m in msgs if m.get('role') != 'system'])
    pl = {
        'model': ollama_payload.get('model'),
        'messages': msgs,
        'stream': bool(ollama_payload.get('stream')),
    }
    tools = ollama_payload.get('tools')
    if tools:
        pl['tools'] = tools  # определения инструментов уже в OpenAI-формате
    opts = ollama_payload.get('options') or {}
    if opts.get('num_predict'):
        pl['max_tokens'] = opts['num_predict']
    if pl['stream']:
        pl['stream_options'] = {'include_usage': True}
    if sm is not None:
        eff = get_reasoning_effort(sm)
        if eff:
            pl['reasoning_effort'] = eff
    return pl


class OpenAIStreamResponse:
    """Обертка над SSE-стримом /v1/chat/completions.

    Имитирует requests.Response с iter_lines(), отдающим NDJSON-чанки в
    формате Ollama /api/chat, чтобы код botinok работал без изменений.
    """

    def __init__(self, resp):
        self._resp = resp
        self.status_code = resp.status_code

    def close(self):
        try:
            self._resp.close()
        except Exception:
            pass

    def json(self):
        return self._resp.json()

    @property
    def text(self):
        return getattr(self._resp, 'text', '')

    def iter_lines(self):
        tool_calls_acc = {}
        usage = {}
        finish_reason = None

        for raw in self._resp.iter_lines():
            if not raw:
                continue
            line = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
            if line.startswith('event:'):
                continue
            data = line[5:].strip() if line.startswith('data:') else line.strip()
            if not data:
                continue
            if data == '[DONE]':
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            u = chunk.get('usage')
            if isinstance(u, dict) and u:
                usage = u

            choices = chunk.get('choices') or []
            delta = {}
            if choices:
                c = choices[0] or {}
                delta = c.get('delta') or {}
                fr = c.get('finish_reason')
                if fr:
                    finish_reason = fr
                # НЕ выходим по finish_reason: чанк с usage приходит следующим

            for tc in delta.get('tool_calls') or []:
                idx = tc.get('index', 0)
                acc = tool_calls_acc.setdefault(idx, {
                    'id': '',
                    'function': {'name': '', 'arguments': ''},
                })
                if tc.get('id'):
                    acc['id'] = tc['id']
                fn = tc.get('function') or {}
                if fn.get('name'):
                    acc['function']['name'] += fn['name']
                if fn.get('arguments'):
                    acc['function']['arguments'] += fn['arguments']

            thought = (delta.get('reasoning_content') or delta.get('reasoning')
                       or delta.get('thinking') or '')
            token = delta.get('content') or ''
            if thought or token:
                yield json.dumps({
                    'message': {
                        'role': 'assistant',
                        'content': token,
                        'thinking': thought,
                    },
                }, ensure_ascii=False).encode('utf-8')
            elif delta.get('tool_calls'):
                # Пульс активности: модель стримит аргументы инструмента
                # (может идти минуты без единого «видимого» токена). Строка
                # нужна, чтобы харнес видел жизнь в потоке и не кричал «зависло».
                yield json.dumps({
                    'message': {'role': 'assistant'},
                    'tool_delta': True,
                }, ensure_ascii=False).encode('utf-8')

        final_msg = {'role': 'assistant'}
        if tool_calls_acc:
            tcs = []
            for idx in sorted(tool_calls_acc):
                tc = tool_calls_acc[idx]
                tcs.append({
                    'id': tc['id'] or f'call_{idx}',
                    'type': 'function',
                    'function': {
                        'name': tc['function']['name'],
                        'arguments': _parse_tool_args(tc['function']['arguments'] or '{}'),
                    },
                })
            final_msg['tool_calls'] = tcs
        yield json.dumps({
            'message': final_msg,
            'done': True,
            'done_reason': finish_reason or 'stop',
            'prompt_eval_count': usage.get('prompt_tokens', 0),
            'eval_count': usage.get('completion_tokens', 0),
            'reasoning_tokens': (usage.get('completion_tokens_details') or {}).get(
                'reasoning_tokens', 0),
            'eval_duration': 0,
            'total_duration': 0,
        }, ensure_ascii=False).encode('utf-8')


def _is_reasoning_rejection(status, text):
    """400, вызванная неприменимым значением рассуждения (модель отклонила
    уровень, который синтаксически прошёл валидатор прокси)."""
    tl = (text or '').lower()
    return (status == 400 and 'reasoning' in tl
            and ('unexpected' in tl or 'not supported' in tl
                 or 'unsupported' in tl or 'invalid' in tl
                 or 'effort' in tl))


def _drop_bad_reasoning(sm):
    """Настройка ReasoningEffort отклонена сервером — убираем её (auto),
    чтобы не ловить 400 на каждом запросе, и сохраняем."""
    try:
        if sm is not None and sm.config.has_option('Ollama', 'ReasoningEffort'):
            sm.config.remove_option('Ollama', 'ReasoningEffort')
            sm.save_config()
    except Exception:
        pass


def chat_stream_request(sm, ollama_payload, timeout=300, verify_ssl=True):
    """POST на /v1/chat/completions со стримингом. Возвращает OpenAIStreamResponse."""
    pl = _to_openai_payload(ollama_payload, sm)
    resp = requests.post(
        _api_url(sm),
        json=pl,
        headers=_api_headers(sm),
        stream=True,
        timeout=timeout,
        verify=verify_ssl,
    )
    if resp.status_code == 400 and pl.get('reasoning_effort'):
        body = resp.text
        resp.close()
        if _is_reasoning_rejection(400, body):
            # Модель не знает такой уровень — один раз повторяем без него
            # и сбрасываем настройку, чтобы не повторять ошибку каждый ход.
            pl.pop('reasoning_effort', None)
            _drop_bad_reasoning(sm)
            resp = requests.post(
                _api_url(sm), json=pl, headers=_api_headers(sm), stream=True,
                timeout=timeout, verify=verify_ssl)
    return OpenAIStreamResponse(resp)


def chat_once(sm, ollama_payload, timeout=300, verify_ssl=True):
    """Нестриминговый запрос. Ответ в формате Ollama: {"message": {...}, ...}."""
    pl = _to_openai_payload(ollama_payload, sm)
    pl['stream'] = False
    pl.pop('stream_options', None)
    res = requests.post(_api_url(sm), json=pl, headers=_api_headers(sm), timeout=timeout, verify=verify_ssl)
    if res.status_code == 400 and pl.get('reasoning_effort') and \
            _is_reasoning_rejection(400, res.text):
        pl.pop('reasoning_effort', None)
        _drop_bad_reasoning(sm)
        res = requests.post(_api_url(sm), json=pl, headers=_api_headers(sm),
                            timeout=timeout, verify=verify_ssl)
    res.raise_for_status()
    data = res.json()
    choice = (data.get('choices') or [{}])[0]
    msg = choice.get('message') or {}
    ollama_tcs = []
    for tc in msg.get('tool_calls') or []:
        fn = tc.get('function') or {}
        args = fn.get('arguments')
        if not isinstance(args, dict):
            args = _parse_tool_args(args or '{}')
        ollama_tcs.append({
            'id': tc.get('id'),
            'type': 'function',
            'function': {'name': fn.get('name'), 'arguments': args},
        })
    out_msg = {'role': 'assistant', 'content': msg.get('content') or ''}
    thought = msg.get('reasoning_content') or msg.get('reasoning')
    if thought:
        out_msg['thinking'] = thought
    if ollama_tcs:
        out_msg['tool_calls'] = ollama_tcs
    usage = data.get('usage') or {}
    return {
        'message': out_msg,
        'done': True,
        'prompt_eval_count': usage.get('prompt_tokens', 0),
        'eval_count': usage.get('completion_tokens', 0),
        'reasoning_tokens': (usage.get('completion_tokens_details') or {}).get(
            'reasoning_tokens', 0),
    }
