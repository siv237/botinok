"""
Интеграция Textual App с стримингом Ollama.

Заменяет Rich Live на Textual App с RichLog.
"""

import queue
import threading
import time
import json
import requests
from typing import Optional, List, Dict, Callable

from core.session_manager import SessionManager
from core.tool_manager import ToolManager
from core.textual_app import BotinokTextualApp


def ask_ollama_textual(
    model: str,
    messages: List[Dict],
    session_path: str,
    step_num: int,
    num_ctx: int = 8192,
    read_only_mode: bool = False,
    on_complete: Optional[Callable] = None
) -> List[Dict]:
    """
    Запускает стриминг Ollama с Textual UI вместо Rich Live.

    Args:
        model: Название модели Ollama
        messages: История сообщений
        session_path: Путь к сессии
        step_num: Номер шага
        num_ctx: Размер контекста
        read_only_mode: Режим только чтения
        on_complete: Callback при завершении

    Returns:
        Обновленная история сообщений
    """
    sm = SessionManager()
    tm = ToolManager()

    # Создаем Textual App
    app = BotinokTextualApp(session_path=session_path)

    # Queue для передачи данных из стриминга в UI
    ui_queue = queue.Queue()
    result_queue = queue.Queue()

    # Функция для обработки стриминга Ollama
    def stream_worker():
        try:
            # Загружаем identity
            if messages and not any(m.get("role") == "system" and "BOTINOK" in str(m.get("content", "")) for m in messages):
                identity_content = sm.load_prompt(session_path, "identity")
                if identity_content:
                    messages.insert(0, {"role": "system", "content": identity_content})

            # Подготовка инструментов
            tools = tm.get_tool_definitions()
            if read_only_mode:
                # Фильтруем инструменты для read-only режима
                read_only_tools = {}
                for name, desc in tools.items():
                    if name == "shell_exec":
                        continue
                    read_only_tools[name] = desc
                tools = read_only_tools

            tools_list = list(tools.values()) if isinstance(tools, dict) else (tools or [])

            # Payload для Ollama
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "logprobs": True,
                "options": {"num_ctx": num_ctx},
            }

            # Добавляем инструменты если модель поддерживает
            if model not in ["llama2", "mistral"]:  # Пример моделей без инструментов
                payload["tools"] = tools_list

            # Получаем URL Ollama
            ollama_base_url = sm.config.get('Ollama', 'BaseUrl', fallback='http://localhost:11434')
            ollama_chat_url = f"{ollama_base_url}/api/chat"
            verify_ssl = sm.config.getboolean('Ollama', 'VerifySSL', fallback=True)

            # Отправляем запрос Ollama
            response = requests.post(ollama_chat_url, json=payload, stream=True, verify=verify_ssl)

            full_response = ""
            full_thinking = ""
            tool_calls = []
            start_time = time.time()
            first_token_time = None
            thinking_tokens = 0
            response_tokens = 0

            ui_queue.put(("status", "Generating..."))
            ui_queue.put(("stats", {
                "status": "Generating...",
                "elapsed": 0.0,
                "no_chunks": 0.0,
                "ttft": "...",
                "thinking_tokens": 0,
                "response_tokens": 0,
                "stream_tool_tokens": 0,
                "final_tool_tokens": 0,
                "tps": 0.0,
                "vram": "...",
                "session_ctx": 0,
                "session_ctx_max": num_ctx,
                "last_req_ctx": 0,
                "last_req_ctx_max": num_ctx
            }))

            # Обработка стриминга
            for line in response.iter_lines():
                if not line:
                    continue

                try:
                    chunk = json.loads(line.decode('utf-8'))
                    msg = chunk.get("message", {})

                    # Первый токен
                    if not first_token_time:
                        first_token_time = time.time()

                    # Thinking
                    thought = msg.get("thinking", "")
                    if thought:
                        full_thinking += thought
                        thinking_tokens += 1
                        ui_queue.put(("chunk_thinking", thought))

                    # Content
                    token = msg.get("content", "")
                    if token:
                        full_response += token
                        response_tokens += 1
                        ui_queue.put(("chunk_content", token))

                    # Tool calls
                    if msg.get("tool_calls"):
                        tool_calls.extend(msg.get("tool_calls"))

                    # Done
                    if chunk.get("done"):
                        elapsed = time.time() - start_time
                        ttft = first_token_time - start_time if first_token_time else 0
                        tps = (thinking_tokens + response_tokens) / (time.time() - first_token_time) if first_token_time else 0

                        ui_queue.put(("status", "Done"))
                        ui_queue.put(("stats", {
                            "status": "Done",
                            "elapsed": elapsed,
                            "no_chunks": 0.0,
                            "ttft": f"{ttft:.2f}s",
                            "thinking_tokens": thinking_tokens,
                            "response_tokens": response_tokens,
                            "stream_tool_tokens": 0,
                            "final_tool_tokens": 0,
                            "tps": tps,
                            "vram": "...",
                            "session_ctx": len(str(messages)) * 4,  # Приблизительно
                            "session_ctx_max": num_ctx,
                            "last_req_ctx": (thinking_tokens + response_tokens) * 4,
                            "last_req_ctx_max": num_ctx
                        }))

                        # Сохраняем в контекст
                        sm.update_context(session_path, "assistant", full_response, thinking=full_thinking)
                        messages.append({"role": "assistant", "content": full_response, "tool_calls": tool_calls})

                        # Финализируем в UI
                        ui_queue.put(("finalize", (full_response, full_thinking, tool_calls)))

                        break

                except json.JSONDecodeError:
                    continue

            result_queue.put(("success", messages))

        except Exception as e:
            ui_queue.put(("error", str(e)))
            result_queue.put(("error", str(e)))

    # Callback для обработки ввода пользователя
    def on_user_input(text: str):
        if text.lower() == "exit":
            app.exit()
            return

        # Добавляем user message
        messages.append({"role": "user", "content": text})
        sm.update_context(session_path, "user", text)

        app.append_user_message(text)

        # Запускаем стриминг в отдельном потоке
        worker = threading.Thread(target=stream_worker, daemon=True)
        worker.start()

    # Устанавливаем callback
    app.on_submit = on_user_input

    # Функция для обновления UI из queue
    def ui_updater():
        while True:
            try:
                kind, data = ui_queue.get(timeout=0.1)

                if kind == "status":
                    pass  # Можно обновить статус

                elif kind == "stats":
                    app.update_stats(
                        status=data["status"],
                        elapsed=data["elapsed"],
                        no_chunks=data["no_chunks"],
                        ttft=data["ttft"],
                        thinking_tokens=data["thinking_tokens"],
                        response_tokens=data["response_tokens"],
                        stream_tool_tokens=data["stream_tool_tokens"],
                        final_tool_tokens=data["final_tool_tokens"],
                        tps=data["tps"],
                        vram=data["vram"],
                        session_ctx=data["session_ctx"],
                        session_ctx_max=data["session_ctx_max"],
                        last_req_ctx=data["last_req_ctx"],
                        last_req_ctx_max=data["last_req_ctx_max"]
                    )

                elif kind == "chunk_thinking":
                    app.rich_log.write(f"[dim]{data}[/dim]")

                elif kind == "chunk_content":
                    app.rich_log.write(data)

                elif kind == "finalize":
                    content, thinking, calls = data
                    app.rich_log.write("[bold green]Assistant:[/bold green]\n")
                    app.rich_log.write(content + "\n")

                elif kind == "error":
                    app.rich_log.write(f"[red]Error: {data}[/red]")

            except queue.Empty:
                continue
            except Exception as e:
                app.rich_log.write(f"[red]UI Error: {e}[/red]")

    # Запускаем UI updater в отдельном потоке
    ui_thread = threading.Thread(target=ui_updater, daemon=True)
    ui_thread.start()

    # Запускаем Textual App
    app.run()

    # Ждем завершения
    try:
        status, result = result_queue.get(timeout=1.0)
        if status == "success":
            if on_complete:
                on_complete(result)
            return result
        else:
            raise Exception(result)
    except queue.Empty:
        return messages


if __name__ == "__main__":
    # Тест
    messages = [{"role": "user", "content": "Привет"}]
    result = ask_ollama_textual(
        model="qwen2.5:0.5b",
        messages=messages,
        session_path="",
        step_num=1
    )
    print(f"Result: {result}")
