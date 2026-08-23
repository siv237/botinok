import requests
import os
import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from core.session_manager import SessionManager

console = Console()

BACKEND_OLLAMA = "ollama"
BACKEND_OPENAI = "openai"


class ConfigWizard:
    def __init__(self):
        self.sm = SessionManager()
        self.config = self.sm.config

    @staticmethod
    def current_backend(config):
        try:
            value = config.get('Ollama', 'Backend', fallback='ollama').strip().lower()
        except Exception:
            value = 'ollama'
        return BACKEND_OPENAI if value in ('openai', 'openai-compatible') else BACKEND_OLLAMA

    def check_ollama(self, url):
        """Проверка доступности Ollama по указанному URL."""
        try:
            response = requests.get(f"{url}/api/tags", timeout=5, verify=False)
            if response.status_code == 200:
                return True, response.json().get("models", [])
        except Exception:
            pass
        return False, []

    @staticmethod
    def _candidate_model_urls(url):
        """Строит кандидатов на эндпоинт /v1/models, допуская как голый домен,
        так и прямой путь с уже указанным /v1."""
        base = url.rstrip('/')
        candidates = []
        if base.endswith('/v1'):
            candidates.append(f"{base}/models")
        candidates.append(f"{base}/v1/models")
        candidates.append(f"{base}/models")
        seen = set()
        uniq = []
        for c in candidates:
            if c not in seen:
                uniq.append(c)
                seen.add(c)
        return uniq

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
                    'max_model_len', 'context_len', 'n_ctx')
        meta = m.get('meta') or {}
        meta_keys = ('context_length', 'context_window', 'max_model_len', 'n_ctx')
        llama = meta.get('llama') if isinstance(meta, dict) else None
        for target in (m, meta if isinstance(meta, dict) else None,
                       llama if isinstance(llama, dict) else None):
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

    def _server_context(self, url, headers):
        """Для llama.cpp-подобных серверов пробует вытащить контекст из `/props`
        (значение сервера по умолчанию). Иначе None."""
        base = url.rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        for path in (f"{base}/props",):
            try:
                r = requests.get(path, timeout=5, verify=False, headers=headers)
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

    def check_openai(self, url, api_key=""):
        """Проверка доступности OpenAI-совместимого API по указанному URL.

        Пробует GET списка моделей (стандартный эндпоинт) по нескольким
        возможным путям: {@base}/v1/models, {@base}/models, и с учётом
        уже указанного пути /v1. Опционально передаёт Bearer-токен.

        Возвращает (True, list[dict]) — список моделей вида
        {'id': str, 'context': int|None}, где context — максимальный
        контекст, сообщаемый провайдером (или None, если провайдер его
        не отдаёт). Если ни у одной модели контекста нет, но сервер
        отдаёт его через /props — подставляем серверное значение.
        """
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        for path in self._candidate_model_urls(url):
            try:
                response = requests.get(path, timeout=5, verify=False, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    for m in data.get('data', []):
                        mid = m.get('id')
                        if not mid:
                            continue
                        models.append({'id': mid, 'context': self._model_context(m)})
                    if models:
                        server_ctx = self._server_context(url, headers)
                        if server_ctx:
                            for entry in models:
                                if not entry.get('context'):
                                    entry['context'] = server_ctx
                    return True, models
            except Exception:
                pass
        return False, []

    def _configure_ollama(self):
        """Настройка подключения к Ollama. Возвращает список имён моделей или None."""
        current_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        console.print(f"\n[bold]1. Проверка Ollama API[/bold]")

        url = current_url
        models = []
        while True:
            success, models = self.check_ollama(url)
            if success:
                console.print(f"[green]✓ Подключение к Ollama установлено: {url}[/green]")
                console.print("[yellow]⚠ SSL верификация отключена (небезопасно для продакшена)[/yellow]")
                if Confirm.ask("Использовать этот адрес сервера?", default=True):
                    break
            else:
                console.print(f"[red]✗ Не удалось подключиться к Ollama по адресу: {url}[/red]")

            url = Prompt.ask("Введите URL Ollama (например, http://localhost:11434)", default=url)

        self.config.set('Ollama', 'BaseUrl', url)
        return [m['name'] for m in models]

    def _configure_openai(self):
        """Настройка подключения к OpenAI-совместимому API.

        Позволяет указать BaseUrl и (опционально) API-ключ. Обязательно
        проверяет доступность списка моделей (/models): подключение
        принимается только если список удалось получить. Возвращает список
        моделей вида list[dict]: {'id', 'context'}.
        """
        console.print(f"\n[bold]1. Настройка OpenAI-совместимого API[/bold]")

        current_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        current_key = self.config.get('Ollama', 'ApiKey', fallback='')

        # 1. Сначала адрес.
        url = Prompt.ask("Введите BaseUrl (например, http://localhost:8080)", default=current_url).strip().rstrip('/')
        if not url:
            url = current_url

        # 2. Потом API-ключ (пустая строка = пропустить).
        if current_key and not Confirm.ask("Изменить API-ключ (Bearer токен)?", default=False):
            api_key = current_key
        else:
            api_key = Prompt.ask("API-ключ (рекомендуется; пусто — пропустить)", default="").strip()
        if api_key:
            self.config.set('Ollama', 'ApiKey', api_key)
        elif self.config.has_option('Ollama', 'ApiKey'):
            self.config.remove_option('Ollama', 'ApiKey')

        # 3. И только потом обязательная проверка списка моделей.
        hint = " (без ключа)" if not api_key else ""
        while True:
            success, models = self.check_openai(url, api_key)
            if success:
                console.print(f"[green]✓ Подключение установлено{hint}: {url}[/green]")
                console.print(f"[green]  Найдено моделей: {len(models)}[/green]")
                if Confirm.ask("Использовать этот адрес сервера?", default=True):
                    break
            else:
                console.print(f"[red]✗ Не удалось получить список моделей{hint}: {url}[/red]")

            url = Prompt.ask("Введите BaseUrl (например, http://localhost:8080)", default=url).strip().rstrip('/')
            if not url:
                url = current_url

        self.config.set('Ollama', 'BaseUrl', url)
        return models

    def run(self):
        console.print(Panel("[bold cyan]Мастер настройки BOTINOK AGENT[/bold cyan]", border_style="cyan"))

        if not Confirm.ask("Хотите запустить мастер настройки сейчас?", default=True):
            console.print("[yellow]Настройка пропущена.[/yellow]")
            return

        if not self.config.has_section('Ollama'):
            self.config.add_section('Ollama')

        # 0. Выбор бэкенда
        console.print(f"\n[bold]0. Выбор бэкенда[/bold]")
        backend_options = [
            (f"Ollama — локальный сервер ({self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')})", BACKEND_OLLAMA),
            ("OpenAI-совместимый API (llama-server, vLLM, OpenAI и др.)", BACKEND_OPENAI),
        ]
        backend_default = self.current_backend(self.config)
        backend_answers = inquirer.prompt([
            inquirer.List('backend',
                         message="Выберите бэкенд (тип сервера)",
                         choices=backend_options,
                         default=backend_default),
        ])
        if not backend_answers:
            console.print("[yellow]Настройка прервана.[/yellow]")
            return

        backend = backend_answers['backend']
        self.config.set('Ollama', 'Backend', backend)

        if backend == BACKEND_OPENAI:
            models = self._configure_openai()
        else:
            models = self._configure_ollama()

        if models is None:
            return

        # 2. Выбор модели по умолчанию
        console.print(f"\n[bold]2. Выбор модели по умолчанию[/bold]")
        if not models:
            if backend == BACKEND_OPENAI:
                console.print("[red]Не удалось получить список моделей с OpenAI-совместимого API.[/red]")
                console.print("Вы можете указать имя модели вручную.")
                chosen_model = Prompt.ask(
                    "Введите имя модели",
                    default=self.config.get('Ollama', 'DefaultModel', fallback='')
                ) or self.config.get('Ollama', 'DefaultModel', fallback='qwen3.5:4b')
            else:
                console.print("[red]На сервере Ollama не найдено ни одной модели![/red]")
                console.print("Пожалуйста, скачайте модель командой 'ollama pull qwen3.5:4b' и запустите мастер снова.")
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
            model_answers = inquirer.prompt([
                inquirer.List('model',
                             message="Выберите модель по умолчанию",
                             choices=model_choices,
                             default=default_model),
            ])
            if not model_answers:
                console.print("[yellow]Настройка прервана.[/yellow]")
                return
            chosen_model = model_answers['model']

        self.config.set('Ollama', 'DefaultModel', chosen_model)

        # Контекст выбранной модели (если провайдер его сообщил)
        model_ctx = None
        if backend == BACKEND_OPENAI and models:
            for m in models:
                if m.get('id') == chosen_model and m.get('context'):
                    model_ctx = int(m['context'])
                    break

        # 3. Контекст по умолчанию
        console.print(f"\n[bold]3. Размер контекста по умолчанию[/bold]")
        current_ctx = self.config.getint('Ollama', 'DefaultContext', fallback=8192)

        if model_ctx:
            # Провайдер сообщил максимальный контекст — предлагаем
            # рекомендуемый (максимальный) или меньше.
            console.print(f"[cyan]Провайдер сообщает максимальный контекст «{chosen_model}»: {model_ctx} токенов.[/cyan]")
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

        ctx_questions = [
            inquirer.List('ctx',
                         message="Выберите размер контекста (влияет на потребление памяти и длину диалога)",
                         choices=ctx_options,
                         default=default_ctx_val,
                         ),
        ]

        ctx_answers = inquirer.prompt(ctx_questions)
        if not ctx_answers:
            console.print("[yellow]Настройка прервана.[/yellow]")
            return

        chosen_ctx = ctx_answers['ctx']
        if chosen_ctx == "custom":
            chosen_ctx = Prompt.ask("Введите размер контекста (в токенах, кратно 1024)", default=str(current_ctx))
            try:
                chosen_ctx = int(chosen_ctx)
            except ValueError:
                console.print(f"[red]Некорректное значение, используется {current_ctx}[/red]")
                chosen_ctx = current_ctx

        self.config.set('Ollama', 'DefaultContext', str(chosen_ctx))

        # 4. Сохранение
        success = self.sm.save_config()
        if not success:
            # Пробуем сохранить локально
            local_config_dir = os.path.expanduser("~/.config/botinok")
            local_config_path = os.path.join(local_config_dir, "config.cfg")
            
            console.print(f"\n[red]✗ Нет прав для сохранения в: {self.sm.config_path}[/red]")
            if Confirm.ask(f"Сохранить конфигурацию локально в {local_config_path}?", default=True):
                try:
                    os.makedirs(local_config_dir, exist_ok=True)
                    self.sm.config_path = local_config_path
                    success = self.sm.save_config()
                except Exception as e:
                    console.print(f"[red]✗ Не удалось создать локальную директорию: {e}[/red]")
                    # Последняя попытка - текущая директория
                    self.sm.config_path = "config.cfg"
                    console.print(f"[yellow]Пробуем сохранить в текущей директории: {self.sm.config_path}[/yellow]")
                    success = self.sm.save_config()
        
        if success:
            console.print(Panel(f"[bold green]Настройка успешно завершена![/bold green]\nКонфигурация сохранена в: {self.sm.config_path}", border_style="green"))
        else:
            console.print(Panel(f"[bold red]Ошибка сохранения конфигурации[/bold red]\nПопробуйте запустить с правами администратора или проверьте права доступа.", border_style="red"))

def main():
    wizard = ConfigWizard()
    wizard.run()

if __name__ == "__main__":
    main()
