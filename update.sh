#!/usr/bin/env bash
# Обновление BOTINOK: код из git + python-зависимости + системные компоненты.
#
# Запуск (под root или с sudo):
#   sudo bash update.sh
# Скрипт идемпотентен: можно запускать повторно, ставит только недостающее.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PY="$SCRIPT_DIR/venv/bin/python"
APP="$SCRIPT_DIR/botinok.py"
REQ="$SCRIPT_DIR/requirements.txt"

echo "[i] Каталог обновления: $SCRIPT_DIR"

# 1) Код из git (если это git-репозиторий).
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  BRANCH="$(git branch --show-current 2>/dev/null || echo main)"
  echo "[i] git pull origin ${BRANCH:-main}..."
  git -c safe.directory="$SCRIPT_DIR" pull --ff-only origin "${BRANCH:-main}" || \
    echo "[!] git pull не удался (локальные изменения или сеть) — продолжаю с текущим кодом."
else
  echo "[i] git-репозиторий не найден — обновление кода пропущено."
fi

# 2) Python-зависимости.
if [ -x "$PY" ] && [ -f "$REQ" ]; then
  echo "[i] Обновляю Python-зависимости..."
  "$PY" -m pip install --upgrade pip setuptools wheel -r "$REQ" || \
    echo "[!] pip install завершился с ошибкой."
else
  echo "[!] Не найден venv ($PY) — Python-зависимости не обновлены."
fi

# 3) Системные компоненты: chafa, ffmpeg, aria2, lynx, jq, file, curl, git.
if [ -x "$PY" ] && [ -f "$APP" ]; then
  "$PY" "$APP" --ensure-deps
else
  echo "[!] Не найден botinok.py — системные компоненты не проверены."
fi

echo "[+] Обновление завершено. Перезапусти BOTINOK."
