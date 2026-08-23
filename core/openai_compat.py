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

import requests


def is_openai_backend(sm):
    try:
        return sm.config.get('Ollama', 'Backend', fallback='ollama').strip().lower() in ('openai', 'openai-compatible')
    except Exception:
        return False


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


def _to_openai_payload(ollama_payload):
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

            thought = delta.get('reasoning_content') or delta.get('thinking') or ''
            token = delta.get('content') or ''
            if thought or token:
                yield json.dumps({
                    'message': {
                        'role': 'assistant',
                        'content': token,
                        'thinking': thought,
                    },
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
            'prompt_eval_count': usage.get('prompt_tokens', 0),
            'eval_count': usage.get('completion_tokens', 0),
            'eval_duration': 0,
            'total_duration': 0,
        }, ensure_ascii=False).encode('utf-8')


def chat_stream_request(sm, ollama_payload, timeout=300, verify_ssl=True):
    """POST на /v1/chat/completions со стримингом. Возвращает OpenAIStreamResponse."""
    resp = requests.post(
        _api_url(sm),
        json=_to_openai_payload(ollama_payload),
        headers=_api_headers(sm),
        stream=True,
        timeout=timeout,
        verify=verify_ssl,
    )
    return OpenAIStreamResponse(resp)


def chat_once(sm, ollama_payload, timeout=300, verify_ssl=True):
    """Нестриминговый запрос. Ответ в формате Ollama: {"message": {...}, ...}."""
    pl = _to_openai_payload(ollama_payload)
    pl['stream'] = False
    pl.pop('stream_options', None)
    res = requests.post(_api_url(sm), json=pl, headers=_api_headers(sm), timeout=timeout, verify=verify_ssl)
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
    if msg.get('reasoning_content'):
        out_msg['thinking'] = msg['reasoning_content']
    if ollama_tcs:
        out_msg['tool_calls'] = ollama_tcs
    usage = data.get('usage') or {}
    return {
        'message': out_msg,
        'done': True,
        'prompt_eval_count': usage.get('prompt_tokens', 0),
        'eval_count': usage.get('completion_tokens', 0),
    }
