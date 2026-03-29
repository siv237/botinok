import requests
import json
import sys
import os
import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from core.session_manager import SessionManager

console = Console()

class ConfigWizard:
    def __init__(self):
        self.sm = SessionManager()
        self.config = self.sm.config
        
    def check_ollama(self, url):
        """Проверка доступности Ollama по указанному URL."""
        try:
            response = requests.get(f"{url}/api/tags", timeout=5, verify=False)
            if response.status_code == 200:
                return True, response.json().get("models", [])
        except Exception:
            pass
        return False, []

    def get_available_models(self, url):
        """Получение списка моделей с сервера Ollama."""
        success, models = self.check_ollama(url)
        if success:
            return [m['name'] for m in models]
        return []

    def run(self):
        console.print(Panel("[bold cyan]Мастер настройки BOTINOK AGENT[/bold cyan]", border_style="cyan"))
        
        if not Confirm.ask("Хотите запустить мастер настройки сейчас?", default=True):
            console.print("[yellow]Настройка пропущена.[/yellow]")
            return

        # 1. Настройка Ollama URL
        current_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        console.print(f"\n[bold]1. Проверка Ollama API[/bold]")
        
        url = current_url
        while True:
            success, models = self.check_ollama(url)
            if success:
                console.print(f"[green]✓ Подключение к Ollama установлено: {url}[/green]")
                console.print("[yellow]⚠ SSL верификация отключена (небезопасно для продакшена)[/yellow]")
                if Confirm.ask(f"Использовать этот адрес сервера?", default=True):
                    break
            else:
                console.print(f"[red]✗ Не удалось подключиться к Ollama по адресу: {url}[/red]")
            
            url = Prompt.ask("Введите URL Ollama (например, http://localhost:11434)", default=url)

        # Сохраняем URL в конфиг
        if not self.config.has_section('Ollama'):
            self.config.add_section('Ollama')
        self.config.set('Ollama', 'BaseUrl', url)

        # 2. Выбор модели
        console.print(f"\n[bold]2. Выбор модели по умолчанию[/bold]")
        
        if not models:
            console.print("[red]На сервере Ollama не найдено ни одной модели![/red]")
            console.print("Пожалуйста, скачайте модель командой 'ollama pull qwen3.5:4b' и запустите мастер снова.")
            return

        # Формируем список опций для inquirer с дополнительной информацией
        model_options = []
        for m in models:
            name = m['name']
            size_gb = m.get('size', 0) / (1024**3)
            fmt = m.get('details', {}).get('format', 'gguf')
            # Создаем красивую строку для отображения, но значением будет только имя
            display_name = f"{name:<40} | {size_gb:>6.2f} GB | {fmt}"
            model_options.append((display_name, name))

        default_model = self.config.get('Ollama', 'DefaultModel', fallback='qwen3.5:4b')
        
        # Интерактивный выбор модели с помощью inquirer (стрелками)
        questions = [
            inquirer.List('model',
                         message="Выберите модель из списка (Название | Размер | Формат)",
                         choices=model_options,
                         default=default_model,
                         ),
        ]
        
        answers = inquirer.prompt(questions)
        if not answers:
            console.print("[yellow]Настройка прервана.[/yellow]")
            return
            
        chosen_model = answers['model']
        self.config.set('Ollama', 'DefaultModel', chosen_model)
        
        # 3. Сохранение
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
