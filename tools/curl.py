#!/usr/bin/env python3
"""
HTTP downloader tool. Downloads files, auto-saves binaries, returns file info.

Usage:
  curl(url="https://site.com/file.png")  # auto-saves to artifacts/
  curl(url="...", output_path="./file.png")  # save to specific path
  curl(url="...", headers=["User-Agent: Mozilla/5.0"])  # custom headers

Returns for binary files:
  ✅ Downloaded: URL
  📁 Saved to: PATH
  📊 Size: X bytes
  📝 Type: FILE_TYPE
  🔐 SHA256: HASH

Returns for text/JSON:
  (content directly)
"""

import hashlib
import os
import re
import subprocess
from urllib.parse import urlparse


def execute(
    url: str,
    output_path: str = None,
    timeout_sec: int = 30,
    max_bytes: int = 256_000,
    follow_redirects: bool = True,
    headers: list = None,
    session_path: str = None,
) -> str:
    """Download URL, auto-save binary, return file info or text content."""
    
    if not url.startswith(('http://', 'https://')):
        return "❌ Error: URL must start with http:// or https://"
    
    # Quick HEAD check to verify file exists (5 sec timeout)
    head_cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--head", "--max-time", "5"]
    if follow_redirects:
        head_cmd.append("-L")
    if headers:
        for h in headers:
            head_cmd.extend(["-H", str(h)])
    head_cmd.append(url)
    
    try:
        head_result = subprocess.run(head_cmd, capture_output=True, text=True, timeout=10)
        http_code = head_result.stdout.strip()
        if http_code in ["404", "410"]:
            return f"❌ File not found (HTTP {http_code}): {url}"
        if http_code.startswith("4") or http_code.startswith("5"):
            # Non-fatal: continue anyway but warn
            pass
    except:
        pass  # Continue even if HEAD check fails
    
    # Build curl command
    cmd = ["curl", "-s", "-S", "-f", "-o", "-"]
    
    if follow_redirects:
        cmd.append("-L")
    
    cmd.extend(["--connect-timeout", str(min(timeout_sec, 60))])
    cmd.extend(["--max-time", str(min(timeout_sec, 120))])
    
    if headers:
        for h in headers:
            cmd.extend(["-H", str(h)])
    
    cmd.append(url)
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                              timeout=min(timeout_sec + 10, 130))
        
        raw = result.stdout
        
        if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='replace')[:200]
            if result.returncode == 22:
                return f"❌ HTTP error (403/404). Try different URL or headers.\n{err}"
            return f"❌ Download failed (code {result.returncode}): {err}"
        
        if not raw:
            return " Empty response"
        
        if len(raw) > max_bytes:
            return f" File too large: {len(raw)} bytes (limit: {max_bytes})"
        
        # If output_path specified, always save file (even text content like SVG, JSON, XML)
        if output_path:
            # Save file
            parent = os.path.dirname(output_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            
            with open(output_path, 'wb') as f:
                f.write(raw)
            
            # Get file info
            size = len(raw)
            sha256 = hashlib.sha256(raw).hexdigest()
            
            # Detect type from extension or content
            ext = os.path.splitext(output_path)[1].lower()
            ftype_map = {'.svg': 'SVG image', '.json': 'JSON', '.xml': 'XML', 
                         '.txt': 'Text', '.html': 'HTML', '.css': 'CSS',
                         '.js': 'JavaScript', '.md': 'Markdown', '.png': 'PNG image',
                         '.jpg': 'JPEG image', '.jpeg': 'JPEG image', '.pdf': 'PDF',
                         '.gif': 'GIF image', '.zip': 'ZIP archive'}
            ftype = ftype_map.get(ext, 'file')
            
            # Try file command for better detection
            try:
                r = subprocess.run(['file', '-b', output_path], capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    ftype = r.stdout.strip()
            except:
                pass
            
            return (f"✅ Downloaded: {url}\n"
                    f"📁 Saved: {output_path}\n"
                    f"📊 Size: {size} bytes\n"
                    f"📝 Type: {ftype}\n"
                    f"🔐 SHA256: {sha256}")
        
        # Check if text (only when no output_path specified)
        is_text = False
        try:
            sample = raw[:1024].decode('utf-8')
            is_text = sample.strip().startswith(('{', '[', '"')) or all(b < 128 or b in (9,10,13) for b in raw[:200])
        except:
            pass
        
        if is_text:
            return raw.decode('utf-8', errors='replace')[:10000]
        
        # Binary: auto-save if session_path provided
        if session_path:
            parsed = urlparse(url)
            fname = os.path.basename(parsed.path) or "download"
            fname = re.sub(r'[^\w.-]', '_', fname)[:100]
            
            # Add extension from magic bytes
            ext_map = {
                b'\x89PNG': ".png",
                b'\xff\xd8': ".jpg",
                b'%PDF': ".pdf",
                b'PK\x03\x04': ".zip",
                b'GIF8': ".gif",
            }
            for magic, ext in ext_map.items():
                if raw[:len(magic)] == magic:
                    if not fname.endswith(ext):
                        fname += ext
                    break
            
            output_path = os.path.join(session_path, "downloads", fname)
        
        if not output_path:
            return f"❌ Binary file ({len(raw)} bytes) - provide output_path or session_path"
        
        # Save file (auto-save path from session_path)
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        
        with open(output_path, 'wb') as f:
            f.write(raw)
        
        # Get file info
        size = len(raw)
        sha256 = hashlib.sha256(raw).hexdigest()
        
        # Detect type from magic bytes
        ftype = "unknown"
        for magic, name in [(b'\x89PNG', "PNG"), (b'\xff\xd8', "JPEG"), 
                            (b'%PDF', "PDF"), (b'GIF8', "GIF"),
                            (b'PK\x03\x04', "ZIP")]:
            if raw[:len(magic)] == magic:
                ftype = f"{name} image/file"
                break
        
        # Try file command
        try:
            r = subprocess.run(['file', '-b', output_path], capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                ftype = r.stdout.strip()
        except:
            pass
        
        return (f"✅ Downloaded: {url}\n"
                f"📁 Saved: {output_path}\n"
                f"📊 Size: {size} bytes\n"
                f"📝 Type: {ftype}\n"
                f"🔐 SHA256: {sha256}")
        
    except subprocess.TimeoutExpired:
        return f"❌ Timeout ({timeout_sec}s)"
    except FileNotFoundError:
        return "❌ curl not found"
    except Exception as e:
        return f"❌ Error: {str(e)}"


# Alias для совместимости с системным вызовом
curl = execute
