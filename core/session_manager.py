import os
import json
import time
import configparser
from datetime import datetime
import requests

class SessionManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config_path = os.getenv("BOTINOK_CONFIG", "config.cfg")
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding='utf-8')
        else:
            # Дефолтные значения, если конфиг не найден
            self.config['Ollama'] = {'BaseUrl': 'http://localhost:11434', 'DefaultModel': 'qwen3.5:9b', 'DefaultContext': '8192'}
            self.config['Storage'] = {'SessionsDir': 'sessions', 'StepsSubDir': 'steps'}
            
        self.base_path = self.config.get('Storage', 'SessionsDir', fallback='sessions')
        self.last_chunk_time = None
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)
            
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
        
        # Начальный контекст
        context = {
            "session_id": session_name,
            "created_at": timestamp,
            "history": []
        }
        
        with open(os.path.join(session_path, "context.json"), "w") as f:
            json.dump(context, f, indent=4)
            
        return session_path

    def get_ollama_status(self, base_url=None):
        if base_url is None:
            base_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        try:
            response = requests.get(f"{base_url}/api/ps", timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            # Не печатаем ошибку в консоль, чтобы не ломать Rich Layout
            pass
        return None

    def unload_models(self, base_url=None):
        """Выгружает все модели из памяти Ollama"""
        if base_url is None:
            base_url = self.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
        status = self.get_ollama_status(base_url)
        if status and "models" in status:
            for m in status["models"]:
                try:
                    requests.post(f"{base_url}/api/generate", json={
                        "model": m["name"],
                        "keep_alive": 0
                    }, timeout=5)
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
