import re
import requests
import os

from core.openai_compat import (probe_reasoning, load_reasoning_cache,
                                save_reasoning_cache, reasoning_cache_key,
                                load_cache_entry, save_cache_entry,
                                classify_chat_models)
from core.session_manager import SessionManager
from core import server_history
from core import provider_registry
from core.cli_io import out
from core.textual_prompts import (textual_confirm, textual_prompt, textual_select,
                                  textual_select_grouped)

BACKEND_OLLAMA = "ollama"
BACKEND_OPENAI = "openai"

# Типовые префиксы API перед /models. Провайдеры прячут инференс за
# собственным путём (например Fireworks — /inference/v1). Порядок — от
# самого частого к редкому.
_MODEL_PREFIXES = ('/v1', '', '/inference/v1', '/inference',
                   '/api/v1', '/openai/v1', '/compatible-mode/v1')
# Хосты, для которых схема по умолчанию — http (локальная сеть).
_LOCAL_HOST_RE = re.compile(r'^(localhost|127\.0\.0\.1|0\.0\.0\.0|::1)$')
_PRIVATE_HOST_RE = re.compile(r'^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.)')
_SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://')


class ConfigWizard:
    def __init__(self, sm=None):
        # sm=None — запуск из CLI (--wizard): свой SessionManager. TUI передаёт
        # живого SessionManager сессии, чтобы проверки и запись ключа шли по
        # текущей конфигурации (та же практика у команды /key).
        self.sm = sm if sm is not None else SessionManager()
        self.config = self.sm.config

    @staticmethod
    def current_backend(config):
        try:
            value = config.get('Ollama', 'Backend', fallback='ollama').strip().lower()
        except Exception:
            value = 'ollama'
        return BACKEND_OPENAI if value in ('openai', 'openai-compatible') else BACKEND_OLLAMA

    @staticmethod
    def _is_https(url):
        return str(url or "").strip().lower().startswith("https://")

    @staticmethod
    def _cert_error(exc):
        """Определяет, что ошибка связана с проверкой TLS-сертификата."""
        if isinstance(exc, requests.exceptions.SSLError):
            return str(exc)
        text = str(exc).lower()
        if "certificate" in text or "ssl" in text or "tls" in text:
            return str(exc)
        return None

    def _consent_ignore_cert(self, url, err):
        """Предупреждение и согласие на игнорирование сертификата.

        Возвращает True (согласен), False (не согласен) или None (отмена).
        """
        out(f"⚠ Не удалось проверить SSL-сертификат: {url}")
        out(f"  Причина: {err}")
        out("  Игнорирование сертификата делает соединение уязвимым к MITM-атакам.")
        return textual_confirm(
            "Игнорировать проверку сертификата и продолжить работу?", default=False)

    def check_ollama(self, url, verify=True):
        """Проверка доступности Ollama по указанному URL.

        Возвращает (success, models, cert_error), где cert_error — текст
        ошибки TLS-сертификата, если соединение не удалось именно из-за
        проверки сертификата (иначе None).
        """
        cert_error = None
        try:
            response = requests.get(f"{url}/api/tags", timeout=5, verify=verify)
            if response.status_code == 200:
                return True, response.json().get("models", []), None
        except Exception as e:
            cert_error = self._cert_error(e)
        return False, [], cert_error

    @staticmethod
    def _normalize_url(raw):
        """Приводит введённый адрес к рабочему виду, не требуя от пользователя
        идеальной записи: дописывает недостающую схему (https для публичных
        хостов, http для локальных) и убирает хвостовые слэши.

        Возвращает (url, была_ли_дописана_схема)."""
        u = (raw or '').strip()
        if not u:
            return u, False
        if _SCHEME_RE.match(u):
            return u.rstrip('/'), False
        host = u.split('/', 1)[0].rsplit('@', 1)[-1]
        host = host.split(':', 1)[0].strip('[]').lower()
        local = bool(_LOCAL_HOST_RE.match(host) or _PRIVATE_HOST_RE.match(host)
                     or host.endswith('.local') or host.endswith('.localhost'))
        scheme = 'http' if local else 'https'
        return f"{scheme}://{u}".rstrip('/'), True

    @staticmethod
    def _split_pasted_url(raw):
        """Разбирает вставленный адрес, который может быть не API-базой, а
        страницей модели (https://host/models/<id>). Возвращает
        (base_url, подсказка_имени_модели|None)."""
        u, _ = ConfigWizard._normalize_url(raw)
        m = re.match(r'^(https?://[^/]+)(/.*)?$', u)
        if not m:
            return u, None
        host, path = m.group(1), (m.group(2) or '').rstrip('/')
        mm = re.match(r'^/models/(.+)$', path)
        if mm:
            return host, mm.group(1)
        return u, None

    @staticmethod
    def _canonical_model_urls(url):
        """Самые вероятные точки входа для адреса КАК ЕГО ВВЁЛ пользователь:
        {@base}/v1/models и {@base}/models, с учётом уже указанного /v1 или
        полного пути до моделей/чата. Сначала — канонический вариант."""
        base = (url or '').strip().rstrip('/')
        for suffix in ('/chat/completions', '/completions'):
            if base.endswith(suffix):
                base = base[:-len(suffix)].rstrip('/')
        out = []
        if base.endswith('/models'):
            out.append(base)
        else:
            if base.endswith('/v1'):
                out.append(f"{base}/models")
            out.append(f"{base}/v1/models")
            out.append(f"{base}/models")
        seen, uniq = set(), []
        for c in out:
            if c not in seen:
                uniq.append(c)
                seen.add(c)
        return uniq

    @staticmethod
    def _candidate_model_urls(url):
        """Строит кандидатов на эндпоинт /models по примерному адресу:
        дописывает недостающие типовые префиксы API и убирает лишнее
        (полный путь до моделей/чата, дублирующийся /v1)."""
        base = (url or '').strip().rstrip('/')
        for suffix in ('/chat/completions', '/completions'):
            if base.endswith(suffix):
                base = base[:-len(suffix)].rstrip('/')
        roots = []
        for r in ([base[:-len('/models')]] if base.endswith('/models') else []) + [base]:
            r = r.rstrip('/')
            if r and r not in roots:
                roots.append(r)
        if base.endswith('/v1'):
            r = base[:-len('/v1')].rstrip('/')
            if r and r not in roots:
                roots.append(r)
        out = []
        for r in roots:
            if r.endswith('/models'):
                out.append(r)
                continue
            for pfx in _MODEL_PREFIXES:
                # Не дублируем уже указанный префикс (…/v1/v1/models).
                if pfx and r.endswith(pfx):
                    continue
                out.append(f"{r}{pfx}/models")
        seen = set()
        uniq = []
        for c in out:
            if c not in seen:
                uniq.append(c)
                seen.add(c)
        return uniq

    @staticmethod
    def _api_base_from_models_url(models_url):
        """Восстанавливает корень API из рабочего адреса списка моделей:
        именно его сохраняем как BaseUrl, т.к. рантайм сам дописывает /v1.
        Лишний /v1 и провайдерский префикс (например /inference) сохраняются."""
        u = (models_url or '').rstrip('/')
        for suffix in ('/v1/models', '/models'):
            if u.endswith(suffix):
                root = u[:-len(suffix)].rstrip('/')
                if suffix == '/models' and root.endswith('/v1'):
                    root = root[:-len('/v1')].rstrip('/')
                return root or None
        return None

    @staticmethod
    def _model_context(m):
        """Извлекает максимальный контекст модели из полей провайдера.

        Разные серверы (llama.cpp, vLLM, прокси) отдают его в разных
        полях: context_length, context_window, max_model_len и т.п.,
        иногда вложено в meta / meta.llama. Если контекст не найден —
        возвращает None.
        """
        if not isinstance(m, dict):
            return None
        top_keys = ('context_length', 'context_window', 'max_context_length',
                    'max_model_len', 'context_len', 'n_ctx',
                    'max_total_tokens', 'max_input_tokens')
        meta = m.get('meta') or {}
        meta_keys = ('context_length', 'context_window', 'max_model_len', 'n_ctx')
        llama = meta.get('llama') if isinstance(meta, dict) else None
        details = m.get('details') if isinstance(m.get('details'), dict) else None
        for target in (m, meta if isinstance(meta, dict) else None,
                       llama if isinstance(llama, dict) else None,
                       details):
            if not isinstance(target, dict):
                continue
            for key in top_keys if target is m else meta_keys:
                v = target.get(key)
                if isinstance(v, (int, float)) and v > 0:
                    return int(v)
                if isinstance(v, str) and v.strip().isdigit():
                    return int(v.strip())
        # Отдельные провайдеры отдают число напрямую (некоторые прокси)
        for key in top_keys:
            if key in m and isinstance(m[key], (int, float)) and m[key] > 0:
                return int(m[key])
        return None

    @staticmethod
    def _context_ladder(max_ctx, current_ctx):
        """Строит лесенку размеров контекста от рекомендуемого (провайдерского)
        вниз, кратно убывая вдвое, но не ниже 8192."""
        ladder = []
        v = max_ctx if max_ctx and max_ctx > 0 else current_ctx
        if v and v > 0:
            v = int(v)
            while v >= 8192 and len(ladder) < 8:
                ladder.append(v)
                v = v // 2
        # Гарантируем, что текущий тоже попадёт в список (если в диапазоне)
        if current_ctx and current_ctx > 0:
            if 8192 <= current_ctx <= (max_ctx or current_ctx):
                if current_ctx not in ladder:
                    ladder.append(int(current_ctx))
        return ladder

    def _server_context(self, url, headers, verify=True):
        """Для llama.cpp-подобных серверов пробует вытащить контекст из `/props`
        (значение сервера по умолчанию). Иначе None."""
        base = url.rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        for path in (f"{base}/props",):
            try:
                r = requests.get(path, timeout=5, verify=verify, headers=headers)
                if r.status_code != 200:
                    continue
                data = r.json()
                dgs = data.get('default_generation_settings') or {}
                if isinstance(dgs, dict):
                    for key in ('n_ctx_per_seq', 'n_ctx_seq', 'n_ctx'):
                        v = dgs.get(key)
                        if isinstance(v, (int, float)) and v > 0:
                            return int(v)
            except Exception:
                continue
        return None

    def _get_models_json(self, path, api_key, verify):
        """GET одного адреса списка моделей. При рабочем эндпоинте
        (200 + список data) возвращает (models, api_base, headers), иначе None.
        Исключения (сеть, TLS) не глотает — их обрабатывает вызывающий."""
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        # 30 c: нестабильные/медленные провайдеры успевают отдать список моделей,
        # а не падают в таймаут на ровном месте.
        response = requests.get(path, timeout=30, verify=verify, headers=headers)
        if response.status_code != 200:
            return None
        data = response.json()
        raw = data.get('data') if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return None
        api_base = self._api_base_from_models_url(path) or path
        models = []
        for m in raw:
            mid = m.get('id') if isinstance(m, dict) else None
            if mid:
                models.append({'id': mid, 'context': self._model_context(m)})
        return models, api_base, headers

    def _classify(self, models, api_base, api_key, verify, headers):
        """Отсеивает не-чат модели настоящим чат-запросом и подставляет
        серверный контекст, если провайдер его не отдал."""
        models = [e for e in
                  classify_chat_models(BACKEND_OPENAI, api_base, api_key,
                                       models, verify=verify)
                  if e.get('chat', True)]
        if models:
            server_ctx = self._server_context(api_base, headers, verify=verify)
            if server_ctx:
                for entry in models:
                    if not entry.get('context'):
                        entry['context'] = server_ctx
        return models

    @staticmethod
    def _net_error(exc):
        """Короткое описание сетевой ошибки (таймаут/нет соединения/…) или
        None, если ошибка не сетевая (например, TLS — у неё свой обработчик)."""
        if isinstance(exc, requests.exceptions.SSLError):
            return None
        name = type(exc).__name__
        if 'Timeout' in name:
            return "таймаут"
        if 'Connection' in name or 'Connect' in name:
            return "нет соединения"
        return "ошибка сети"

    def _probe_paths(self, paths, api_key, verify):
        """Перебирает адреса списка моделей. Возвращает
        (models, api_base, cert_error, net_error)."""
        cert_error = None
        net_error = None
        for path in paths:
            try:
                got = self._get_models_json(path, api_key, verify)
            except Exception as e:
                cert_error = cert_error or self._cert_error(e)
                net_error = net_error or self._net_error(e)
                continue
            if got is None:
                continue
            models, api_base, headers = got
            return (self._classify(models, api_base, api_key, verify, headers),
                    api_base, None, None)
        return None, None, cert_error, net_error

    def check_openai(self, url, api_key="", verify=True):
        """Проверка КАНОНИЧЕСКОГО адреса, введённого пользователем.

        Проверяются наиболее вероятные точки входа для адреса как он введён:
        {@base}/v1/models и {@base}/models (с учётом уже указанного /v1).
        Если ни одна не ответила — визард переходит к авто-корректору по
        типовым паттернам (discover_model_endpoints), а затем — к выбору
        провайдера из базы (provider_registry).

        Возвращает (success, list[dict], cert_error, api_base, net_error) —
        список моделей вида {'id': str, 'context': int|None}. api_base — корень
        API (его и нужно сохранять в BaseUrl: рантайм сам дописывает /v1).
        cert_error — текст ошибки TLS-сертификата (иначе None). net_error —
        «таймаут»/«нет соединения», если сервер вовсе не ответил (это не
        «путь неверный» — стоит предложить повтор).
        """
        url, _ = self._normalize_url(url)
        models, api_base, cert_error, net_error = self._probe_paths(
            self._canonical_model_urls(url), api_key, verify)
        if models is not None:
            return True, models, None, api_base, None
        return False, [], cert_error, None, net_error

    def discover_model_endpoints(self, url, api_key="", verify=True):
        """Автопоиск: перебирает типовые точки входа (в т.ч. провайдерские
        префиксы /inference/v1, /api/v1 …) и возвращает ВСЕ рабочие:
        list[(api_base, models)]. Нужен, когда канонический адрес не ответил —
        визард покажет найденное пользователю."""
        url, _ = self._normalize_url(url)
        found, seen = [], set()
        for path in self._candidate_model_urls(url):
            try:
                got = self._get_models_json(path, api_key, verify)
            except Exception:
                continue
            if got is None:
                continue
            models, api_base, _ = got
            if api_base in seen:
                continue
            seen.add(api_base)
            found.append((api_base, models))
        return found

    def _configure_reasoning(self, backend, chosen_model):
        """Шаг визарда: режим рассуждения. Быстрый путь — «по умолчанию
        (auto)»: никаких сетевых проверок. Только при явном выборе запускается
        зонд (медленный, но с дисковым кэшем — повторные запуски мгновенны).
        Список уровней диктует сам API, захардкожен лишь auto."""
        out("\nРассуждение (reasoning)")
        current = (self.config.get('Ollama', 'ReasoningEffort', fallback='auto') or 'auto').strip().lower()

        quick = [("auto — по умолчанию, как сейчас (без проверки сервера)", 'auto')]
        if current and current != 'auto':
            quick.append((f"{current} — уже выбрано ранее", current))
        quick.append(("Выбрать уровень… (проверить, что поддерживает сервер)", "__pick__"))
        ans = textual_select("Режим рассуждения", quick, 'auto' if current == 'auto' else current)
        if ans is None:
            return None
        if ans != '__pick__':
            if ans == 'auto':
                if self.config.has_option('Ollama', 'ReasoningEffort'):
                    self.config.remove_option('Ollama', 'ReasoningEffort')
            else:
                self.config.set('Ollama', 'ReasoningEffort', ans)
            return ans

        url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        api_key = self.config.get('Ollama', 'ApiKey', fallback='')
        verify = self.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        cached = load_reasoning_cache(self.sm, reasoning_cache_key(backend, url, chosen_model))
        if cached is not None:
            out("  Уровни взяты из кэша предыдущей проверки (без обращения к серверу).")
            info = cached
        else:
            out("  Проверяю поддержку рассуждения у сервера — это займёт несколько секунд…")
            info = probe_reasoning(backend, url, api_key, chosen_model, verify=verify)
            if info is not None:
                save_reasoning_cache(self.sm, reasoning_cache_key(backend, url, chosen_model), info)

        options = [("auto — параметр не отправлять (поведение по умолчанию)", 'auto')]
        if info and info['levels']:
            out(f"  Сервер поддерживает: {', '.join(info['levels'])}")
            for lvl in info['levels']:
                mark = " — дефолт сервера" if info.get('default') == lvl else ""
                options.append((f"{lvl}{mark}", lvl))
        else:
            out("  Сервер не сообщил список поддерживаемых значений.")
            custom = textual_prompt("Значение рассуждения (пусто — auto)", default="")
            if custom is None:
                return None
            custom = custom.strip().lower()
            if custom:
                options.append((f"{custom} (вручную)", custom))

        chosen = textual_select("Режим рассуждения", options,
                                current if any(v == current for _, v in options) else 'auto')
        if chosen is None:
            return None
        if chosen == 'auto':
            if self.config.has_option('Ollama', 'ReasoningEffort'):
                self.config.remove_option('Ollama', 'ReasoningEffort')
        else:
            self.config.set('Ollama', 'ReasoningEffort', chosen)
        return chosen

    def _configure_ollama(self, preset=None):
        """Настройка подключения к Ollama. Возвращает список имён моделей или None.

        preset — пункт истории: адрес берётся из него."""
        current_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        out("\n1. Проверка Ollama API")

        base_verify = self.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        url, _ = self._normalize_url((preset or {}).get('url') or current_url)
        verify = base_verify
        models = []
        while True:
            success, models, cert_error = self.check_ollama(url, verify=verify)
            if success:
                out(f"✓ Подключение к Ollama установлено: {url}")
                if self._is_https(url):
                    if verify:
                        out("🔒 Проверка SSL-сертификата включена")
                    else:
                        out("⚠ SSL верификация отключена (небезопасно для продакшена)")
                use = textual_confirm("Использовать этот адрес сервера?", default=True)
                if use is None:
                    return None
                if use:
                    self.config.set('Ollama', 'VerifySSL', 'true' if verify else 'false')
                    break
            elif cert_error:
                consent = self._consent_ignore_cert(url, cert_error)
                if consent is None:
                    return None
                if consent:
                    verify = False
                    continue
            else:
                out(f"✗ Не удалось подключиться к Ollama по адресу: {url}")

            new_url = textual_prompt(
                "Введите URL Ollama (например, http://localhost:11434)", default=url)
            if new_url is None:
                return None
            new_url, _ = self._normalize_url(new_url)
            if new_url != url:
                verify = base_verify
            url = new_url or url

        self.config.set('Ollama', 'BaseUrl', url)
        server_history.record(self.sm, BACKEND_OLLAMA, url)
        entries = [{'id': m['name'], 'context': self._model_context(m),
                    'capabilities': m.get('capabilities') or []} for m in models]
        # Ollama сам сообщает тип модели (capabilities) — эмбеддинги отсекаются.
        return [e for e in classify_chat_models(BACKEND_OLLAMA, url, '', entries)
                if e.get('chat', True)]

    def _pick_provider(self):
        """Ветка визарда: выбрать провайдера из базы models.dev.

        Даёт обновить список, показывает, когда база обновлена, и быстрый
        поиск по имени/домену. Возвращает строку базового URL провайдера для
        подстановки в ручной ввод (или None)."""
        src = provider_registry.REGISTRY_URL
        refresh_val = "__refresh__"
        # В сеть — только по явному согласию: пока списка нет, показываем
        # кнопку загрузки; иначе — список с полем-фильтром.
        providers = provider_registry.load(self.sm)
        if not providers:
            out("  Локальная база провайдеров пуста.")
            start = textual_select(
                "База провайдеров не загружена",
                [(f"⟳ Загрузить список из {src}", refresh_val)],
                refresh_val)
            if start != refresh_val:
                return None
            out(f"  Скачиваю список из {src}…")
            providers = provider_registry.refresh(self.sm) or []
            if not providers:
                out("  Не удалось скачать — введите адрес вручную.")
                return None
        # Один экран: список провайдеров, а поле сверху — просто фильтр.
        # Первым пунктом — обновление из источника.
        while True:
            age = provider_registry.age_text(self.sm)
            out(f"  Источник: {src} — {len(providers)} провайдеров, "
                f"обновлено {provider_registry.updated_date(self.sm)} ({age})")
            options = [(f"⟳ Обновить список из {src}  (обновлён {age})",
                        refresh_val)]
            options += [(f"{e['name']}  —  {e['api']}", e['api'])
                        for e in providers]
            default = options[1][1] if len(options) > 1 else refresh_val
            picked = textual_select(
                f"Выберите провайдера — база обновлена {age} "
                f"(поле сверху — фильтр по имени или домену)",
                options, default, filterable=True)
            if picked is None:
                return None
            if picked == refresh_val:
                out(f"  Обновляю список из {src}…")
                fresh = provider_registry.refresh(self.sm)
                if fresh:
                    providers = fresh
                    out(f"  Готово: {len(providers)} провайдеров.")
                else:
                    out("  Не удалось обновить (нет сети?) — оставляю текущий список.")
                continue
            return picked

    def _configure_openai(self, preset=None):
        """Настройка подключения к OpenAI-совместимому API.

        Позволяет указать BaseUrl и (опционально) API-ключ. Обязательно
        проверяет доступность списка моделей (/models): подключение
        принимается только если список удалось получить. Возвращает список
        моделей вида list[dict]: {'id', 'context'}. preset — пункт истории:
        адреса и ключ только предзаполняют обычные шаги.
        """
        out("\n1. Настройка OpenAI-совместимого API")

        current_url = (preset or {}).get('url') or \
            self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        current_key = ((preset or {}).get('api_key') or '').strip() or \
            self.config.get('Ollama', 'ApiKey', fallback='')

        # 1. Сначала адрес (предзаполнен, можно изменить). От пользователя
        # достаточно примерного адреса — схему и точку входа уточняем сами.
        # Под полем — кнопка поиска по базе провайдеров (models.dev): на неё
        # спускаются стрелкой «вниз», выбор подставляет адрес обратно в ввод.
        def _prompt_url(message, default):
            val = textual_prompt(
                message, default=default,
                buttons=[("🔎 Поиск по базе провайдеров (models.dev)", "?")])
            if val is None:
                return None
            if val.strip() in ('?', '/find', 'find'):
                picked = self._pick_provider()
                return picked if picked else ''
            return val

        url = _prompt_url(
            "Введите BaseUrl или ссылку на модель "
            "(например, http://localhost:8080, api.fireworks.ai)",
            current_url)
        if url is None:
            return None
        url, added_scheme = self._normalize_url(url)
        if not url:
            url = current_url
        if added_scheme:
            out(f"  Схема не указана — использую {url}")
        url, model_hint = self._split_pasted_url(url)
        if model_hint:
            out(f"  Это похоже на страницу модели «{model_hint}» — "
                f"проверю API хоста {url}")

        # 2. Потом API-ключ (пустая строка = пропустить).
        if current_key:
            change_key = textual_confirm("Изменить API-ключ (Bearer токен)?", default=False)
            if change_key is None:
                return None
        else:
            change_key = True
        if not change_key:
            api_key = current_key
        else:
            api_key = textual_prompt("API-ключ (рекомендуется; пусто — пропустить)",
                                     default=current_key)
            if api_key is None:
                return None
            api_key = api_key.strip()
        if api_key:
            self.config.set('Ollama', 'ApiKey', api_key)
        elif self.config.has_option('Ollama', 'ApiKey'):
            self.config.remove_option('Ollama', 'ApiKey')

        # 3. Проверка: сначала канонический адрес, при неудаче — авто-корректор
        # по типовым паттернам (предлагает правильную строку), затем — выбор
        # провайдера из базы models.dev.
        hint = " (без ключа)" if not api_key else ""
        base_verify = self.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        verify = base_verify

        def _with_hint(models):
            """Добавляет имя модели из вставленной ссылки, если его нет."""
            if not model_hint:
                return models
            ids = [m['id'] for m in models]
            if any(model_hint == i or model_hint in i for i in ids):
                return models
            return [{'id': model_hint, 'context': None}] + list(models)

        def _accept(models):
            """Печатает результат и спрашивает подтверждение адреса.
            Возвращает 'use' | 'retry' | None (отмена)."""
            out(f"✓ Подключение установлено{hint}: {url}")
            out(f"  Найдено моделей: {len(models)}")
            if self._is_https(url):
                out("🔒 Проверка SSL-сертификата включена" if verify
                    else "⚠ SSL верификация отключена (небезопасно для продакшена)")
            ans = textual_confirm("Использовать этот адрес сервера?", default=True)
            if ans is None:
                return None
            return 'use' if ans else 'retry'

        while True:
            success, models, cert_error, api_base, net_error = self.check_openai(
                url, api_key, verify=verify)
            if success:
                if api_base and api_base.rstrip('/') != url.rstrip('/'):
                    out(f"  Точка входа уточнена: {api_base}")
                    url = api_base
                models = _with_hint(models)
                decision = _accept(models)
                if decision is None:
                    return None
                if decision == 'use':
                    self.config.set('Ollama', 'VerifySSL', 'true' if verify else 'false')
                    break
            elif cert_error:
                consent = self._consent_ignore_cert(url, cert_error)
                if consent is None:
                    return None
                if consent:
                    verify = False
                    continue
            else:
                if net_error:
                    # Сервер вовсе не ответил (таймаут/нет соединения) — это
                    # не «путь неверный»: предлагаем повторить, а не гадать.
                    out(f"✗ Сервер не ответил по адресу {url} ({net_error}).")
                    again = textual_confirm("Повторить проверку?", default=True)
                    if again is None:
                        return None
                    if again:
                        continue
                out(f"✗ По адресу {url} список моделей не найден.")
                out("  Авто-корректор: подбираю точку входа по типовым "
                    "паттернам (/v1/models, /models, /inference/v1/models …)")
                found = self.discover_model_endpoints(url, api_key, verify=verify)
                chosen = None
                if len(found) == 1:
                    chosen = found[0]
                    out(f"  Подошёл адрес: {chosen[0]}")
                elif len(found) > 1:
                    options = [(f"{b}  —  {len(m)} моделей", b) for b, m in found]
                    pick = textual_select("Найдено несколько точек входа — выберите",
                                          options, found[0][0])
                    if pick is None:
                        return None
                    chosen = next((f for f in found if f[0] == pick), None)
                if chosen:
                    url = chosen[0]
                    headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
                    models = _with_hint(
                        self._classify(chosen[1], url, api_key, verify, headers))
                    decision = _accept(models)
                    if decision is None:
                        return None
                    if decision == 'use':
                        self.config.set('Ollama', 'VerifySSL',
                                        'true' if verify else 'false')
                        break
                else:
                    # Второй вариант — выбрать провайдера из базы (models.dev).
                    if textual_confirm("Подобрать провайдера из базы (models.dev)?",
                                       default=False):
                        picked = self._pick_provider()
                        if picked:
                            url = picked
                            out(f"  Адрес из базы: {url}")
                            continue
                    # Типичная причина — гейтвей требует ключ, а он не введён.
                    if not api_key:
                        add_key = textual_confirm(
                            "Попробовать ввести API-ключ (гейтвей может требовать его)?",
                            default=True)
                        if add_key is None:
                            return None
                        if add_key:
                            k = textual_prompt("API-ключ (Bearer токен)", default="")
                            if k is None:
                                return None
                            api_key = (k or "").strip()
                            if api_key:
                                self.config.set('Ollama', 'ApiKey', api_key)
                                hint = ""
                            continue

            new_url = _prompt_url(
                "Введите BaseUrl (например, http://localhost:8080)", url)
            if new_url is None:
                return None
            new_url, _ = self._normalize_url(new_url)
            if not new_url:
                new_url = current_url
            if new_url != url:
                verify = base_verify
            url = new_url

        self.config.set('Ollama', 'BaseUrl', url)
        server_history.record(self.sm, BACKEND_OPENAI, url, api_key)
        return models

    def run(self):
        out("Мастер настройки BOTINOK AGENT")

        start = textual_confirm("Хотите запустить мастер настройки сейчас?", default=True)
        if not start:
            out("Настройка пропущена.")
            return

        if not self.config.has_section('Ollama'):
            self.config.add_section('Ollama')

        # 0. Выбор бэкенда
        out("\n0. Выбор бэкенда")
        backend_options = [
            (f"Ollama — локальный сервер ({self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')})", BACKEND_OLLAMA),
            ("OpenAI-совместимый API (llama-server, vLLM, OpenAI и др.)", BACKEND_OPENAI),
        ]
        backend_default = self.current_backend(self.config)
        hist = server_history.recent(self.sm)
        if hist:
            backend = textual_select_grouped(
                "Выберите бэкенд (тип сервера)", backend_options,
                "История использования (выберите сервер)",
                [(server_history.label(e), ('hist', e)) for e in hist],
                backend_default)
        else:
            backend = textual_select("Выберите бэкенд (тип сервера)",
                                     backend_options, backend_default)
        if backend is None:
            out("Настройка прервана.")
            return

        # Пункт истории: бэкенд, адрес и ключ берём из него, дальше мастер
        # идёт обычно — поля предзаполнены, их можно изменить.
        preset = None
        if isinstance(backend, tuple) and backend[0] == 'hist':
            preset = backend[1]
            backend = preset.get('backend') or BACKEND_OLLAMA

        self.config.set('Ollama', 'Backend', backend)

        if backend == BACKEND_OPENAI:
            models = self._configure_openai(preset=preset)
        else:
            models = self._configure_ollama(preset=preset)

        if models is None:
            out("Настройка прервана.")
            return

        # Автоопределённый список моделей (с контекстом) — в общий кэш:
        # горячие меню шапки TUI после мастера открываются мгновенно.
        if models:
            try:
                _url = self.config.get('Ollama', 'BaseUrl', fallback='')
                save_cache_entry(self.sm, f"models|{backend}|{_url.rstrip('/')}",
                                 {'models': [{'id': m['id'], 'context': m.get('context'),
                                              'chat': m.get('chat', True)}
                                             for m in models], 'cls': 1})
            except Exception:
                pass

        # 2. Выбор модели по умолчанию
        out("\n2. Выбор модели по умолчанию")
        if not models:
            if backend == BACKEND_OPENAI:
                out("Не удалось получить список моделей с OpenAI-совместимого API.")
                out("Вы можете указать имя модели вручную.")
                chosen_model = textual_prompt(
                    "Введите имя модели",
                    default=self.config.get('Ollama', 'DefaultModel', fallback=''))
                if chosen_model is None:
                    out("Настройка прервана.")
                    return
                chosen_model = chosen_model or self.config.get('Ollama', 'DefaultModel', fallback='qwen3.5:4b')
            else:
                out("На сервере Ollama не найдено ни одной модели!")
                out("Пожалуйста, скачайте модель командой 'ollama pull qwen3.5:4b' и запустите мастер снова.")
                return
        else:
            # Модели приходят как list[dict]: {'id', 'context'}
            model_ids = [m['id'] for m in models]
            default_model = self.config.get('Ollama', 'DefaultModel', fallback=model_ids[0] if model_ids else 'qwen3.5:4b')
            if default_model not in model_ids and model_ids:
                default_model = model_ids[0]

            def _model_label(entry):
                mid = entry.get('id')
                ctx = entry.get('context')
                if ctx:
                    return f"{mid}  ({int(ctx)} ctx)"
                return mid

            model_choices = [(_model_label(m), m['id']) for m in models]
            chosen_model = textual_select("Выберите модель по умолчанию",
                                          model_choices, default_model,
                                          filterable=True)
            if chosen_model is None:
                out("Настройка прервана.")
                return

        self.config.set('Ollama', 'DefaultModel', chosen_model)

        # 2.5 Режим рассуждения (дефолт auto = текущее поведение)
        if self._configure_reasoning(backend, chosen_model) is None:
            out("Настройка прервана.")
            return

        # Контекст выбранной модели: автоопределение провайдера, при его
        # отсутствии — общий кэш (список моделей уже мог его содержать).
        model_ctx = None
        if models:
            for m in models:
                if m.get('id') == chosen_model and m.get('context'):
                    model_ctx = int(m['context'])
                    break
        if not model_ctx:
            try:
                _url = self.config.get('Ollama', 'BaseUrl', fallback='')
                _ent = load_cache_entry(self.sm, f"models|{backend}|{_url.rstrip('/')}",
                                        ttl=24 * 3600)
                for m in (_ent or {}).get('models') or []:
                    if m.get('id') == chosen_model and m.get('context'):
                        model_ctx = int(m['context'])
                        break
            except Exception:
                pass

        # 3. Контекст по умолчанию
        out("\n3. Размер контекста по умолчанию")
        current_ctx = self.config.getint('Ollama', 'DefaultContext', fallback=8192)

        if model_ctx:
            # Провайдер сообщил максимальный контекст — предлагаем
            # рекомендуемый (максимальный) или меньше.
            out(f"Провайдер сообщает максимальный контекст «{chosen_model}»: {model_ctx} токенов.")
            ladder = self._context_ladder(model_ctx, current_ctx)
            ctx_options = []
            for i, size in enumerate(ladder):
                if i == 0 and size == model_ctx:
                    desc = "максимальный (рекомендуемый провайдером)"
                elif size == current_ctx:
                    desc = "текущий"
                elif size < model_ctx:
                    desc = "уменьшенный"
                else:
                    desc = "провайдерский"
                ctx_options.append((f"{size:>6} — {desc}", size))
            ctx_options.append(("Свой вариант", "custom"))
        else:
            ctx_options = [
                ("8192    — минимальный", 8192),
                ("16384   — компактный", 16384),
                ("32768   — стандартный", 32768),
                ("65536   — расширенный", 65536),
                ("131072  — большой", 131072),
                ("262144  — максимальный", 262144),
                ("Свой вариант", "custom"),
            ]

        default_ctx_val = current_ctx
        if not any(v == current_ctx for _, v in ctx_options):
            default_ctx_val = "custom"

        chosen_ctx = textual_select(
            "Выберите размер контекста (влияет на потребление памяти и длину диалога)",
            ctx_options, default_ctx_val)
        if chosen_ctx is None:
            out("Настройка прервана.")
            return

        if chosen_ctx == "custom":
            custom_ctx = textual_prompt(
                "Введите размер контекста (в токенах, кратно 1024)", default=str(current_ctx))
            if custom_ctx is None:
                out("Настройка прервана.")
                return
            try:
                chosen_ctx = int(custom_ctx)
            except ValueError:
                out(f"Некорректное значение, используется {current_ctx}")
                chosen_ctx = current_ctx

        self.config.set('Ollama', 'DefaultContext', str(chosen_ctx))

        # 4. Сохранение
        success = self.sm.save_config()
        if not success:
            # Пробуем сохранить локально
            local_config_dir = os.path.expanduser("~/.config/botinok")
            local_config_path = os.path.join(local_config_dir, "config.cfg")

            out(f"\n✗ Нет прав для сохранения в: {self.sm.config_path}")
            save_local = textual_confirm(
                f"Сохранить конфигурацию локально в {local_config_path}?", default=True)
            if not save_local:
                out("Сохранение отменено.")
            else:
                try:
                    os.makedirs(local_config_dir, exist_ok=True)
                    self.sm.config_path = local_config_path
                    success = self.sm.save_config()
                except Exception as e:
                    out(f"✗ Не удалось создать локальную директорию: {e}")
                    # Последняя попытка - текущая директория
                    self.sm.config_path = "config.cfg"
                    out(f"Пробуем сохранить в текущей директории: {self.sm.config_path}")
                    success = self.sm.save_config()

        if success:
            out(f"Настройка успешно завершена!\nКонфигурация сохранена в: {self.sm.config_path}")
        else:
            out("Ошибка сохранения конфигурации\nПопробуйте запустить с правами администратора или проверьте права доступа.")


def main():
    wizard = ConfigWizard()
    wizard.run()


if __name__ == "__main__":
    main()
