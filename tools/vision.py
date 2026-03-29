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
from io import BytesIO

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

import httpx


# Поддерживаемые форматы для Ollama vision моделей
SUPPORTED_FORMATS = {"JPEG", "PNG", "GIF", "BMP", "WEBP"}
SUPPORTED_MIMETYPES = {"image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp"}

# Лимиты для Qwen3.5 (можно переопределить через env)
MAX_IMAGE_SIZE = int(os.environ.get("VISION_MAX_PIXELS", 16777216))  # 4096×4096
MAX_EDGE = int(os.environ.get("VISION_MAX_EDGE", 4096))  # Максимальная сторона


def _looks_like_html(data: bytes) -> bool:
    head = (data[:512] or b"").lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def _download_image(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """Скачивает изображение по URL, возвращает (data, mime_type)"""
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        
        # Проверяем Content-Type из заголовков
        content_type = resp.headers.get("content-type", "").lower()
        
        # Если Content-Type указан и это не image/* - возможно это ошибка или HTML страница
        if content_type and not content_type.startswith("image/"):
            # Проверяем начало контента - может быть HTML?
            content_start = resp.content[:100].lower()
            if content_start.startswith(b"<!doctype") or content_start.startswith(b"<html"):
                raise RuntimeError(f"URL returned HTML page instead of image (Content-Type: {content_type})")
        
        # Пытаемся определить MIME тип
        mime_type = content_type.split(";")[0] if content_type else None
        
        if not mime_type:
            # Пробуем угадать по расширению URL
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
        
        # Валидируем что это реальное изображение через Pillow
        if PIL_AVAILABLE:
            try:
                img = Image.open(BytesIO(resp.content))
                img.verify()  # Проверяем целостность файла
            except Exception as e:
                raise RuntimeError(f"Downloaded content is not a valid image: {e}")
        
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


def _validate_and_process_image(image_bytes: bytes, mime_type: str) -> tuple[bytes, str, dict]:
    """
    Проверяет и обрабатывает изображение для Ollama.
    
    Returns:
        tuple: (processed_bytes, output_mime_type, metadata)
        metadata содержит: original_size, final_size, was_resized, was_converted
    """
    metadata = {
        "original_size": len(image_bytes),
        "final_size": len(image_bytes),
        "was_resized": False,
        "was_converted": False,
        "original_format": "unknown",
        "final_format": mime_type,
    }
    
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for image validation/conversion")
    
    try:
        if _looks_like_html(image_bytes):
            raise RuntimeError("Input looks like HTML, not an image")

        img_probe = Image.open(BytesIO(image_bytes))
        img_probe.verify()

        img = Image.open(BytesIO(image_bytes))
        metadata["original_format"] = img.format or "unknown"
        
        # Определяем нужна ли конвертация
        current_format = img.format
        needs_conversion = False
        
        # Если формат не определен или не поддерживается - конвертируем
        if current_format is None:
            needs_conversion = True
        elif current_format not in SUPPORTED_FORMATS:
            needs_conversion = True
        elif mime_type not in SUPPORTED_MIMETYPES:
            needs_conversion = True
        # SVG всегда конвертируем
        elif mime_type == "image/svg+xml" or current_format == "SVG":
            needs_conversion = True
        # Прозрачность требует конвертации в RGB
        elif img.mode in ("RGBA", "P"):
            needs_conversion = True
        
        # Проверяем размер
        width, height = img.size
        num_pixels = width * height
        max_edge = max(width, height)
        
        needs_resize = False
        if num_pixels > MAX_IMAGE_SIZE:
            needs_resize = True
        if max_edge > MAX_EDGE:
            needs_resize = True
        
        # Если ничего не нужно - возвращаем как есть
        if not needs_conversion and not needs_resize:
            metadata["original_format"] = current_format or "unknown"
            return image_bytes, mime_type, metadata
        
        # Конвертация/ресайз нужен
        # Конвертируем в RGB для JPEG
        if img.mode in ("RGBA", "P", "L", "LA", "CMYK", "I;16", "I;16B"):
            img = img.convert("RGB")
        
        # Ресайз если нужно (только уменьшаем, не увеличиваем)
        if needs_resize:
            # Считаем новый размер сохраняя aspect ratio
            if num_pixels > MAX_IMAGE_SIZE:
                scale = (MAX_IMAGE_SIZE / num_pixels) ** 0.5
                new_width = int(width * scale)
                new_height = int(height * scale)
            else:
                scale = MAX_EDGE / max_edge
                new_width = int(width * scale)
                new_height = int(height * scale)
            
            # Убеждаемся что не превышаем MAX_EDGE по любой стороне
            if max(new_width, new_height) > MAX_EDGE:
                scale = MAX_EDGE / max(new_width, new_height)
                new_width = int(new_width * scale)
                new_height = int(new_height * scale)
            
            # Ресайз с качеством LANCOZOS если доступен, иначем BICUBIC
            try:
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            except AttributeError:
                img = img.resize((new_width, new_height), Image.Resampling.BICUBIC)
            
            metadata["was_resized"] = True
            metadata["new_size"] = f"{new_width}x{new_height}"
        
        # Сохраняем в JPEG (самый совместимый формат)
        output = BytesIO()
        img.save(output, format="JPEG", quality=85, optimize=True)
        output_bytes = output.getvalue()
        
        metadata["was_converted"] = True
        metadata["final_size"] = len(output_bytes)
        metadata["final_format"] = "JPEG"
        
        return output_bytes, "image/jpeg", metadata
        
    except Exception as e:
        # При ошибке обработки - пробуем принудительную конвертацию через RGB
        try:
            img = Image.open(BytesIO(image_bytes))
            # Принудительно конвертируем в RGB
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Проверяем размер и ресайзим если нужно
            width, height = img.size
            if width * height > MAX_IMAGE_SIZE or max(width, height) > MAX_EDGE:
                scale = min((MAX_IMAGE_SIZE / (width * height)) ** 0.5, MAX_EDGE / max(width, height))
                new_size = (int(width * scale), int(height * scale))
                try:
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                except AttributeError:
                    img = img.resize(new_size, Image.Resampling.BICUBIC)
                metadata["was_resized"] = True
            
            output = BytesIO()
            img.save(output, format="JPEG", quality=85)
            output_bytes = output.getvalue()
            metadata["was_converted"] = True
            metadata["final_size"] = len(output_bytes)
            metadata["final_format"] = "JPEG"
            return output_bytes, "image/jpeg", metadata
            
        except Exception as e2:
            raise RuntimeError(f"Invalid/unsupported image input: {type(e).__name__}: {e}") from e2


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
        
        if _looks_like_html(image_bytes):
            return "❌ Error: Input looks like HTML, not an image"

        if not mime_type.startswith("image/"):
            return f"❌ Error: File is not an image (detected: {mime_type})"
        
        # Валидируем и обрабатываем изображение (конвертация/ресайз если нужно)
        processed_bytes, final_mime_type, metadata = _validate_and_process_image(image_bytes, mime_type)
        
        # Конвертируем в base64
        image_b64 = base64.b64encode(processed_bytes).decode("utf-8")
        
        # Формируем результат
        result = {
            "image_data": image_b64,
            "mime_type": final_mime_type,
            "prompt": prompt,
            "source": source,
            "size_bytes": len(processed_bytes),
            "original_size_bytes": metadata["original_size"],
            "processing": {
                "was_resized": metadata["was_resized"],
                "was_converted": metadata["was_converted"],
                "original_format": metadata["original_format"],
                "final_format": metadata["final_format"],
            }
        }
        
        # Добавляем новый размер если ресайзили
        if metadata.get("new_size"):
            result["processing"]["new_size"] = metadata["new_size"]
        
        return result
        
    except FileNotFoundError as e:
        return f"❌ Error: {e}"
    except RuntimeError as e:
        return f"❌ Error: {e}"
    except Exception as e:
        return f"❌ Error processing image: {type(e).__name__}: {e}"
