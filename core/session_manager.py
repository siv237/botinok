import os
import json
import time
import configparser
from datetime import datetime
import requests
import re

class SessionManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        # Ищем конфиг: сначала локальный, потом системный
        if os.path.exists("config.cfg"):
            self.config_path = "config.cfg"
        else:
            self.config_path = os.getenv("BOTINOK_CONFIG", "/opt/botinok/config.cfg")
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding='utf-8')
        else:
            # Дефолтные значения, если конфиг не найден
            self.config['Ollama'] = {'BaseUrl': 'http://localhost:11434', 'DefaultModel': 'qwen3.5:9b', 'DefaultContext': '8192'}
            self.config['Storage'] = {'SessionsDir': '~/.botinok/sessions', 'StepsSubDir': 'steps'}
            
        self.base_path = self.config.get('Storage', 'SessionsDir', fallback='sessions')
        # Разворачиваем ~ и $HOME для текущего пользователя
        self.base_path = os.path.expanduser(self.base_path)
        self.base_path = os.path.expandvars(self.base_path)
        self.last_chunk_time = None
        if not os.path.exists(self.base_path):
            try:
                os.makedirs(self.base_path)
            except PermissionError as e:
                parent = os.path.dirname(self.base_path)
                raise PermissionError(
                    f"Cannot create sessions directory: {self.base_path}\n"
                    f"Parent directory exists: {os.path.exists(parent)}\n"
                    f"If {parent} was created by root earlier, run:\n"
                    f"  sudo chown $(id -u):$(id -g) {parent}\n"
                    f"Or remove it: sudo rm -rf {parent}"
                ) from e

    def list_sessions(self):
        """Возвращает список существующих сессий в base_path (новые сверху)."""
        try:
            if not os.path.exists(self.base_path):
                return []
            items = []
            for name in os.listdir(self.base_path):
                p = os.path.join(self.base_path, name)
                if os.path.isdir(p):
                    try:
                        mtime = os.path.getmtime(p)
                    except Exception:
                        mtime = 0
                    items.append({"name": name, "path": p, "mtime": mtime})
            items.sort(key=lambda x: x.get("mtime", 0), reverse=True)
            return items
        except Exception:
            return []

    def get_latest_session(self):
        sessions = self.list_sessions()
        return sessions[0] if sessions else None

    def ensure_session_structure(self, session_path: str):
        """Гарантирует наличие стандартных подпапок в уже существующей сессии."""
        try:
            steps_subdir = self.config.get('Storage', 'StepsSubDir', fallback='steps')
            os.makedirs(os.path.join(session_path, steps_subdir), exist_ok=True)
            os.makedirs(os.path.join(session_path, "artifacts"), exist_ok=True)
            os.makedirs(os.path.join(session_path, "project"), exist_ok=True)
            os.makedirs(os.path.join(session_path, "proofreader"), exist_ok=True)
        except Exception:
            pass

    def load_last_assistant_answer(self, session_path: str, max_chars: int = 6000) -> str:
        """Пытается достать последний ответ ассистента для продолжения сессии.

        Приоритет:
        1) конец response.md
        2) последний assistant в context.json
        """
        response_path = os.path.join(session_path, "response.md")
        try:
            if os.path.exists(response_path):
                with open(response_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = f.read()
                if data:
                    data = data.strip()
                    if len(data) > max_chars:
                        data = data[-max_chars:]
                    return data
        except Exception:
            pass

        context_path = os.path.join(session_path, "context.json")
        try:
            if os.path.exists(context_path):
                with open(context_path, "r", encoding="utf-8", errors="ignore") as f:
                    ctx = json.load(f)
                hist = ctx.get("history", []) if isinstance(ctx, dict) else []
                for entry in reversed(hist):
                    if isinstance(entry, dict) and entry.get("role") == "assistant":
                        content = entry.get("content") or ""
                        content = str(content).strip()
                        if content:
                            if len(content) > max_chars:
                                content = content[-max_chars:]
                            return content
        except Exception:
            pass

        return ""

    def load_first_user_prompt(self, session_path: str, max_chars: int = 120) -> str:
        context_path = os.path.join(session_path, "context.json")
        try:
            if os.path.exists(context_path):
                with open(context_path, "r", encoding="utf-8", errors="ignore") as f:
                    ctx = json.load(f)
                hist = ctx.get("history", []) if isinstance(ctx, dict) else []
                for entry in hist:
                    if isinstance(entry, dict) and entry.get("role") == "user":
                        content = str(entry.get("content") or "").strip()
                        if content:
                            content = re.sub(r"\s+", " ", content)
                            if len(content) > max_chars:
                                content = content[:max_chars] + "..."
                            return content
        except Exception:
            pass

        response_path = os.path.join(session_path, "response.md")
        try:
            if os.path.exists(response_path):
                with open(response_path, "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(60_000)
                m = re.search(r"^\s*prompt:\s*\|\s*\n(?P<body>(?:\s{2}.*\n)+)", head, re.MULTILINE)
                if m:
                    body = m.group("body")
                    lines = []
                    for ln in body.splitlines():
                        lines.append(ln[2:] if ln.startswith("  ") else ln)
                    content = "\n".join(lines).strip()
                    content = re.sub(r"\s+", " ", content)
                    if content:
                        if len(content) > max_chars:
                            content = content[:max_chars] + "..."
                        return content
        except Exception:
            pass

        return ""

    def ensure_session_subdir(self, session_path: str, subdir_name: str) -> str:
        subdir_path = os.path.join(session_path, subdir_name)
        if not os.path.exists(subdir_path):
            os.makedirs(subdir_path, exist_ok=True)
        return subdir_path

    def save_artifact(self, session_path: str, file_name: str, content: str) -> str:
        artifacts_dir = self.ensure_session_subdir(session_path, "artifacts")
        artifact_path = os.path.join(artifacts_dir, file_name)
        with open(artifact_path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(str(content))
        return artifact_path
            
    def save_config(self):
        """Сохраняет текущую конфигурацию в файл."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def create_session(self, name=""):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{timestamp}_{name}" if name else timestamp
        session_path = os.path.join(self.base_path, session_name)
        
        steps_subdir = self.config.get('Storage', 'StepsSubDir', fallback='steps')
        os.makedirs(session_path)
        os.makedirs(os.path.join(session_path, steps_subdir))
        os.makedirs(os.path.join(session_path, "artifacts"))
        os.makedirs(os.path.join(session_path, "project"))
        os.makedirs(os.path.join(session_path, "proofreader"))
        
        # Копируем системные промпты в сессию
        self._copy_prompts_to_session(session_path)
        
        # Начальный контекст
        context = {
            "session_id": session_name,
            "created_at": timestamp,
            "history": []
        }
        
        with open(os.path.join(session_path, "context.json"), "w") as f:
            json.dump(context, f, indent=4)
            
        return session_path

    def _copy_prompts_to_session(self, session_path: str):
        """Копирует системные промпты из глобальной папки в сессию."""
        import shutil
        # Определяем путь к глобальным промптам
        if os.path.exists("prompts"):
            global_prompts = "prompts"
        else:
            # Ищем рядом с конфигом
            global_prompts = os.path.join(os.path.dirname(self.config_path), "prompts")
        
        session_prompts = os.path.join(session_path, "prompts")
        os.makedirs(session_prompts, exist_ok=True)
        
        if os.path.exists(global_prompts):
            for filename in os.listdir(global_prompts):
                if filename.endswith('.txt'):
                    src = os.path.join(global_prompts, filename)
                    dst = os.path.join(session_prompts, filename)
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass

    def load_prompt(self, session_path: str, prompt_name: str, **variables) -> str:
        """Загружает промпт из папки сессии и подставляет переменные."""
        prompt_file = os.path.join(session_path, "prompts", f"{prompt_name}.txt")
        
        # Fallback на глобальные промпты
        if not os.path.exists(prompt_file):
            if os.path.exists(f"prompts/{prompt_name}.txt"):
                prompt_file = f"prompts/{prompt_name}.txt"
            else:
                global_file = os.path.join(os.path.dirname(self.config_path), "prompts", f"{prompt_name}.txt")
                if os.path.exists(global_file):
                    prompt_file = global_file
                else:
                    return ""
        
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Подставляем переменные {{VAR_NAME}}
            for var_name, var_value in variables.items():
                content = content.replace(f"{{{{{var_name}}}}}", str(var_value))
            
            return content
        except Exception:
            return ""

    def get_ollama_status(self, base_url=None):
        if base_url is None:
            base_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        verify_ssl = self.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        try:
            response = requests.get(f"{base_url}/api/ps", timeout=5, verify=verify_ssl)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            pass
        return None

    def unload_models(self, base_url=None):
        """Выгружает все модели из памяти Ollama"""
        if base_url is None:
            base_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        verify_ssl = self.config.getboolean('Ollama', 'VerifySSL', fallback=True)
        status = self.get_ollama_status(base_url)
        if status and "models" in status:
            for m in status["models"]:
                try:
                    requests.post(f"{base_url}/api/generate", json={
                        "model": m["name"],
                        "keep_alive": 0
                    }, timeout=5, verify=verify_ssl)
                except Exception:
                    pass

    def log_chunk(self, session_path, chunk_type, content, metrics=None):
        """Логирует каждый отдельный чанк ответа в реальном времени с замером дельты."""
        log_file = os.path.join(session_path, "session_raw.log")
        now = datetime.now()
        
        delta = 0
        if self.last_chunk_time:
            delta = (now - self.last_chunk_time).total_seconds()
        self.last_chunk_time = now

        entry = {
            "timestamp": now.isoformat(),
            "delta_sec": round(delta, 4),
            "type": chunk_type,
            "content": content
        }
        if metrics:
            entry["metrics"] = metrics
            
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Инкрементальная запись в файлы thinking.md и response.md
        if chunk_type == "thinking":
            with open(os.path.join(session_path, "thinking.md"), "a", encoding="utf-8") as f:
                f.write(content)
        elif chunk_type == "response":
            with open(os.path.join(session_path, "response.md"), "a", encoding="utf-8") as f:
                f.write(content)

    def write_file_header(self, session_path, file_name, model, num_ctx, prompt):
        """Записывает технический заголовок в файл в формате Markdown. Если файл существует, добавляет разделитель."""
        file_path = os.path.join(session_path, file_name)
        exists = os.path.exists(file_path)
        
        mode = "a" if exists else "w"
        header = ""
        
        if exists:
            header += "\n\n" + "#" * 40 + "\n"
            header += f"# NEW TURN: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            header += "#" * 40 + "\n\n"

        header += (
            f"```yaml\n"
            f"type: BOTINOK_SESSION_METADATA\n"
            f"status: START\n"
            f"timestamp: {datetime.now().isoformat()}\n"
            f"model: {model}\n"
            f"context_limit: {num_ctx}\n"
            f"prompt: |\n"
            f"  {prompt}\n"
            f"```\n\n"
            f"---\n\n"
        )
        with open(file_path, mode, encoding="utf-8") as f:
            f.write(header)

    def write_file_footer(self, session_path, file_name, stats):
        """Записывает технический футер в файл в формате Markdown."""
        file_path = os.path.join(session_path, file_name)
        footer = (
            f"\n\n---\n\n"
            f"```yaml\n"
            f"type: BOTINOK_SESSION_METADATA\n"
            f"status: END\n"
            f"metrics:\n"
            f"  total_tokens: {stats.get('total_tokens')}\n"
            f"  thinking_tokens: {stats.get('thinking_tokens')}\n"
            f"  response_tokens: {stats.get('response_tokens')}\n"
            f"  average_tps: {stats.get('tps'):.2f}\n"
            f"  ttft: {stats.get('ttft'):.2f}s\n"
            f"  total_duration: {stats.get('duration'):.2f}s\n"
            f"files:\n"
            f"  thinking: \"./thinking.log\"\n"
            f"  response: \"./response.md\"\n"
            f"  raw_log: \"./session_raw.log\"\n"
            f"```\n"
        )
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(footer)

    def log_tool_call(self, session_path, tool_name, arguments, result, status="success"):
        """Записывает подробный лог вызова инструмента в отдельный файл."""
        tool_log_file = os.path.join(session_path, "tools.log")
        
        # Вычисляем размер результата в КБ
        result_size_kb = len(str(result).encode('utf-8')) / 1024
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "arguments": arguments,
            "status": status,
            "size_kb": round(result_size_kb, 2),
            "full_result": str(result)
        }
        with open(tool_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def update_context(self, session_path, role, content, thinking="", tool_calls=None):
        context_path = os.path.join(session_path, "context.json")
        try:
            with open(context_path, "r") as f:
                context = json.load(f)
            
            entry = {
                "timestamp": datetime.now().isoformat(),
                "role": role,
                "content": content
            }
            if thinking:
                entry["thinking"] = thinking
            if tool_calls:
                entry["tool_calls"] = tool_calls
                
            context["history"].append(entry)
            
            with open(context_path, "w") as f:
                json.dump(context, f, indent=4, ensure_ascii=False)
        except Exception as e:
            pass

    def log_step(self, session_path, step_name, request_data, response_data, metrics):
        steps_subdir = self.config.get('Storage', 'StepsSubDir', fallback='steps')
        step_file = os.path.join(session_path, steps_subdir, f"{step_name}.json")
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "request": request_data,
            "response": response_data,
            "metrics": metrics
        }
        
        with open(step_file, "w") as f:
            json.dump(log_entry, f, indent=4, ensure_ascii=False)
            
        # Обновляем общий лог производительности
        perf_file = os.path.join(session_path, "performance.log")
        with open(perf_file, "a", encoding="utf-8") as f:
            # Компактный JSON в одну строку для удобства tail -f
            perf_entry = {
                "step": step_name,
                "time": datetime.now().isoformat(),
                "tps": response_data.get("tps") if isinstance(response_data, dict) else None,
                "vram": response_data.get("vram_gb") if isinstance(response_data, dict) else None,
                "ctx": metrics.get("context_used") if isinstance(metrics, dict) else None
            }
            f.write(json.dumps(perf_entry, ensure_ascii=False) + "\n")

    def load_proofreader_history(self, session_path: str) -> list:
        """Загружает историю сообщений корректора."""
        path = os.path.join(session_path, "proofreader", "context.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("history", [])
            except Exception:
                return []
        return []

    def save_proofreader_history(self, session_path: str, history: list):
        """Сохраняет историю сообщений корректора."""
        path = os.path.join(session_path, "proofreader", "context.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"history": history}, f, indent=4, ensure_ascii=False)
        except Exception:
            pass
