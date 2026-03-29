#!/usr/bin/env python3
"""
Vision tool — анализ изображений мультимодальной моделью.

Принимает путь к изображению или URL, конвертирует в base64 для передачи в LLM.

Usage:
  vision(image_path="/path/to/photo.jpg", prompt="Что на изображении?")
  vision(url="https://site.com/image.png", prompt="Опиши содержимое")
  vision(image_path="./photo.jpg")  # использует дефолтный prompt

Returns:
  {"image_data": "base64...", "mime_type": "image/jpeg", "prompt": "..."}
  или текст ошибки если файл не найден/не валидный
"""

import base64
import os
import mimetypes
from urllib.parse import urlparse
from pathlib import Path

import httpx


def _download_image(url: str, timeout_sec: int = 30) -> tuple[bytes, str]:
    """Скачивает изображение по URL, возвращает (data, mime_type)"""
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            
            # Определяем mime type из заголовка или расширения URL
            mime_type = resp.headers.get("content-type", "")
            if not mime_type or mime_type == "application/octet-stream":
                # Пытаемся угадать по расширению
                parsed = urlparse(url)
                ext = os.path.splitext(parsed.path)[1].lower()
                mime_type = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                    ".bmp": "image/bmp",
                    ".svg": "image/svg+xml",
                }.get(ext, "image/jpeg")  # default
            
            return resp.content, mime_type
    except Exception as e:
        raise RuntimeError(f"Failed to download image: {e}")


def _load_local_image(path: str) -> tuple[bytes, str]:
    """Загружает локальный файл, возвращает (data, mime_type)"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    mime_type, _ = mimetypes.guess_type(str(p))
    if not mime_type:
        # Угадываем по расширению
        ext = p.suffix.lower()
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }.get(ext, "image/jpeg")  # default
    
    with open(p, "rb") as f:
        return f.read(), mime_type


def execute(
    image_path: str = None,
    url: str = None,
    prompt: str = "Опиши что ты видишь на этом изображении",
    session_path: str = None,
    timeout_sec: int = 30,
) -> dict:
    """
    Анализ изображения мультимодальной моделью.
    
    Args:
        image_path: Путь к локальному файлу изображения
        url: URL изображения (альтернатива image_path)
        prompt: Запрос к модели (что спросить про изображение)
        session_path: Путь сессии (не используется, для совместимости)
        timeout_sec: Таймаут для скачивания по URL
    
    Returns:
        dict с полями: image_data (base64), mime_type, prompt, size_bytes
        или строку ошибки при неудаче
    """
    try:
        # Проверяем что указан хотя бы один источник
        if not image_path and not url:
            return "❌ Error: Specify either image_path or url"
        
        # Загружаем данные
        if url:
            image_bytes, mime_type = _download_image(url, timeout_sec)
            source = url
        else:
            image_bytes, mime_type = _load_local_image(image_path)
            source = image_path
        
        # Проверяем что это изображение
        if not mime_type.startswith("image/"):
            return f"❌ Error: File is not an image (detected: {mime_type})"
        
        # Конвертируем в base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        
        # Формируем результат
        result = {
            "image_data": image_b64,
            "mime_type": mime_type,
            "prompt": prompt,
            "source": source,
            "size_bytes": len(image_bytes),
        }
        
        return result
        
    except FileNotFoundError as e:
        return f"❌ Error: {e}"
    except RuntimeError as e:
        return f"❌ Error: {e}"
    except Exception as e:
        return f"❌ Error processing image: {type(e).__name__}: {e}"
