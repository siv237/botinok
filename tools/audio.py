#!/usr/bin/env python3
"""
Audio tool — анализ аудио мультимодальной (omni) моделью.

Принимает путь к аудиофайлу или URL, транскодирует в **WAV 16кГц моно PCM**
(через ffmpeg) и возвращает base64 для передачи в LLM.

Как правильно передавать аудио (Ollama): сообщению нужен отдельный массив
`audios: ["<base64-wav>"]` (не `images[]`, не `audio`), и принимаются только
WAV-файлы (детект по magic-байтам). Это поле доступно в Ollama-сборках
с нерелизнутой поддержкой аудио (PR ollama/ollama#15243). Модель с аудио-модальностью
(напр. gemma4, qwen-omni) получает звук именно так.

Usage:
  audio(audio_path="/path/to/speech.wav", prompt="Что сказано на записи?")
  audio(url="https://site.com/clip.mp3", prompt="Опиши звук")
  audio(audio_path="./recording.flac")  # использует дефолтный prompt

Returns:
  {"audio_data": "base64<WAV 16k mono>", "mime_type": "audio/wav", "prompt": "...", "format": "wav"}
  или текст ошибки если файл не найден/не валидный
"""

import base64
import os
import mimetypes
import subprocess
import tempfile
from urllib.parse import urlparse
from pathlib import Path

import httpx


# Поддерживаемые входные аудиоформаты (транскодируются в WAV)
SUPPORTED_MIMETYPES = {
    "audio/wav", "audio/x-wav", "audio/wave",
    "audio/mpeg", "audio/mp3",
    "audio/ogg", "application/ogg",
    "audio/flac",
    "audio/mp4", "audio/x-m4a", "audio/aac", "video/mp4",
    "audio/webm", "video/webm",
    "audio/aiff", "audio/x-aiff",
}

# Параметры транскодирования: WAV 16кГц моно PCM (стандарт для omni/аудио-моделей)
AUDIO_SAMPLE_RATE = int(os.environ.get("AUDIO_SAMPLE_RATE", 16000))
AUDIO_CHANNELS = int(os.environ.get("AUDIO_CHANNELS", 1))

# Лимит размера аудио (можно переопределить через env), по умолчанию 50 МБ
MAX_AUDIO_BYTES = int(os.environ.get("AUDIO_MAX_BYTES", 50 * 1024 * 1024))


def _looks_like_html(data: bytes) -> bool:
    head = (data[:512] or b"").lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def _detect_mime(data: bytes, ext_hint: str = "") -> str:
    """Определяет MIME аудио по magic-байтам, с фолбэком на расширение."""
    head = data[:16]

    # RIFF/WAVE
    if head.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    # RIFF/AIFF
    if head.startswith(b"FORM") and data[8:12] in (b"AIFF", b"AIFC"):
        return "audio/aiff"
    # FLAC
    if head.startswith(b"fLaC"):
        return "audio/flac"
    # OGG
    if head.startswith(b"OggS"):
        return "audio/ogg"
    # WebM / MKV (часто несёт аудио)
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    # MP4 / M4A (box-структура: size(4) + 'ftyp')
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "audio/mp4"
    # MP3: либо ID3-тег, либо frame-sync 0xFF E0-FF
    if head.startswith(b"ID3"):
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "audio/mpeg"

    # Фолбэк по расширению файла
    ext = ext_hint.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/mp4",
        ".mp4": "audio/mp4",
        ".webm": "audio/webm",
        ".aiff": "audio/aiff",
    }.get(ext, "")


def _download_audio(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """Скачивает аудио по URL, возвращает (data, mime_type).

    Лимит размера проверяется по мере стрима, а не после полной загрузки,
    чтобы не буферизовать в память весь большой файл (см. MAX_AUDIO_BYTES).
    """
    chunks = []
    size = 0
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    raise RuntimeError(
                        f"Audio too large: >{MAX_AUDIO_BYTES} bytes. "
                        f"Increase AUDIO_MAX_BYTES to allow bigger files."
                    )
                chunks.append(chunk)

        resp_content = b"".join(chunks)
        if content_type and not content_type.startswith(("audio/", "application/ogg", "video/")):
            content_start = resp_content[:100].lower()
            if content_start.startswith(b"<!doctype") or content_start.startswith(b"<html"):
                raise RuntimeError(f"URL returned HTML page instead of audio (Content-Type: {content_type})")

        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1].lower()
        mime_type = _detect_mime(resp_content, ext_hint=ext)
        if not mime_type:
            raise RuntimeError("Downloaded content is not a recognized audio format")

        return resp_content, mime_type
    except Exception as e:
        raise RuntimeError(f"Failed to download audio: {e}")


def _load_local_audio(path: str) -> tuple[bytes, str]:
    """Загружает локальный файл, возвращает (data, mime_type)"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(p, "rb") as f:
        data = f.read()
    mime_type = _detect_mime(data, ext_hint=p.suffix)
    if not mime_type:
        guessed, _ = mimetypes.guess_type(str(p))
        mime_type = guessed or ""
    return data, mime_type


def _transcode_to_wav16k(audio_bytes: bytes) -> bytes:
    """Транскодирует любые входные байты аудио в WAV 16кГц моно PCM через ffmpeg.

    Ollama-аудио принимает только WAV (детект по magic-байтам), поэтому вход
    (mp3/ogg/flac/m4a/webm/aiff/wav) приводится к стандартному WAV 16кГц моно.
    """
    try:
        import shutil
        ff = shutil.which("ffmpeg")
        if not ff:
            raise RuntimeError("ffmpeg not found; required to transcode audio to WAV")
        proc = subprocess.run(
            [ff, "-v", "error", "-i", "-",
             "-ar", str(AUDIO_SAMPLE_RATE), "-ac", str(AUDIO_CHANNELS),
             "-f", "wav", "-"],
            input=audio_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=int(os.environ.get("AUDIO_TRANSCODE_TIMEOUT", 120)),
        )
        if proc.returncode != 0 or not proc.stdout:
            raise RuntimeError(f"ffmpeg transcoding failed: {proc.stderr.decode('utf-8', 'ignore')[:300]}")
        return proc.stdout
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ffmpeg error: {type(e).__name__}: {e}")


def _validate_audio(audio_bytes: bytes, mime_type: str) -> tuple[bytes, str, dict]:
    """Проверяет аудио, возвращает (data, output_mime, metadata)"""
    meta = {
        "original_size": len(audio_bytes),
        "final_size": len(audio_bytes),
        "mime_type": mime_type or "unknown",
        "valid": False,
        "was_transcoded": False,
    }

    if _looks_like_html(audio_bytes):
        raise RuntimeError("Input looks like HTML, not audio")

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise RuntimeError(
            f"Audio too large: {len(audio_bytes)} bytes "
            f"(max {MAX_AUDIO_BYTES}). Increase AUDIO_MAX_BYTES to allow bigger files."
        )

    if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] != b"WAVE":
        raise RuntimeError("RIFF container is not a WAVE audio file")

    # Пусть mime_type определён; дополнительно по magic байтам не нашли формат — откажем
    if not mime_type or not any(mime_type.startswith(p) for p in ("audio/", "application/ogg", "video/")):
        raise RuntimeError(f"File is not recognized audio (detected: {mime_type})")

    # Приводим к WAV 16кГц моно PCM — единственный формат аудио-входа Ollama
    wav_bytes = _transcode_to_wav16k(audio_bytes)
    meta["valid"] = True
    meta["final_size"] = len(wav_bytes)
    meta["was_transcoded"] = True
    return wav_bytes, "audio/wav", meta


def execute(
    audio_path: str = None,
    url: str = None,
    prompt: str = "Опиши, что ты слышишь в этом аудио. Если там есть речь — процитируй её",
    session_path: str = None,
    timeout_sec: int = 30,
) -> dict:
    """
    Анализ аудио мультимодальной (omni) моделью.

    Args:
        audio_path: Путь к локальному аудиофайлу (wav, mp3, ogg, flac, m4a и т.п.)
        url: URL аудио (альтернатива audio_path)
        prompt: Запрос к модели (что спросить про аудио)
        session_path: Путь сессии (не используется, для совместимости)
        timeout_sec: Таймаут для скачивания по URL

    Returns:
        dict с полями: audio_data (base64), mime_type, prompt, size_bytes
        или строку ошибки при неудаче
    """
    try:
        if not audio_path and not url:
            return "❌ Error: Specify either audio_path or url"

        if url:
            audio_bytes, mime_type = _download_audio(url, timeout_sec)
            source = url
        else:
            audio_bytes, mime_type = _load_local_audio(audio_path)
            source = audio_path

        processed_bytes, final_mime_type, metadata = _validate_audio(audio_bytes, mime_type)

        audio_b64 = base64.b64encode(processed_bytes).decode("utf-8")

        return {
            "audio_data": audio_b64,
            "mime_type": final_mime_type,  # всегда audio/wav (WAV 16кГц моно)
            "format": "wav",
            "prompt": prompt,
            "source": source,
            "size_bytes": len(processed_bytes),
        }

    except FileNotFoundError as e:
        return f"❌ Error: {e}"
    except RuntimeError as e:
        return f"❌ Error: {e}"
    except Exception as e:
        return f"❌ Error processing audio: {type(e).__name__}: {e}"
