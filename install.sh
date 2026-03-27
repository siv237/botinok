#!/bin/bash

# BOTINOK INSTALLER (Ollama style)
# This script installs BOTINOK AGENT to /opt/botinok and creates a symlink in /usr/local/bin

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Detect real user home (for sudo installs)
REAL_HOME="$HOME"
if [ -n "$SUDO_USER" ] && [ "$EUID" -eq 0 ]; then
    REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    [ -z "$REAL_HOME" ] && REAL_HOME="/home/$SUDO_USER"
fi

# Extract version info from git: date (DD.MM.YYYY) and first 4 chars of commit hash
BOTINOK_VERSION="unknown"
if [ -d ".git" ] || [ -d "$PWD/.git" ]; then
    COMMIT_DATE=$(git log -1 --format=%cd --date=format:%d.%m.%Y 2>/dev/null || echo "unknown")
    COMMIT_HASH=$(git log -1 --format=%h 2>/dev/null | cut -c1-4 || echo "????")
    BOTINOK_VERSION="0.2 | ${COMMIT_DATE} | ${COMMIT_HASH}"
fi

INSTALL_DIR="/opt/botinok"
OS_NAME="$(uname -s 2>/dev/null || echo unknown)"
# Detect BIN_DIR based on OS/distro
if [ "$OS_NAME" = "Darwin" ]; then
    BIN_DIR="/usr/local/bin"
elif command -v apt-get >/dev/null 2>&1; then
    BIN_DIR="/usr/local/bin"
else
    # RHEL/CentOS - /usr/local/bin not in root's PATH by default
    BIN_DIR="/usr/bin"
fi
SESSIONS_DIR="$REAL_HOME/.botinok"
SKILLS_DIR="$REAL_HOME/.botinok/skills"
EXPERIENCE_DIR="$REAL_HOME/.botinok/experience"
GITHUB_REPO="https://github.com/siv237/botinok.git"

# --- Functions ---

echo_blue() { echo -e "${BLUE}$1${NC}"; }
echo_green() { echo -e "${GREEN}$1${NC}"; }
echo_red() { echo -e "${RED}$1${NC}"; }

print_banner() {
    cat <<'EOF'
                                                           ^^:.                                     
                                                          !~.~!7^:::::....                          
                                                        ^?7^7!~~~7~~~~~~!!!!!!~~^^                  
                                                       :J7:J^!7~ ^           ..:~P^                 
                                                       7J !?:^~:~^::::........  !Y.                 
                                                      ~Y::J!!7..~      ........:J?                  
                                                     ~?7!?!:~!.^.              :Y!                  
                                                    ~J~!?7!!: ^:               ^5~                  
                                                  .!?!??~.~!:^:                !Y!                  
                                                .^???77!?! .^.                 7?7                  
                                              .~?J7??~.:~^::                   ?!?.                 
                                           .^7J5J7^:7?~.::.                 .:^J77!                 
                                         ^!7Y?~~7?! .:::.               :^!!~~^.  ?.                
                                       .?7J7!?! .^^::.               :~!~^.       !~                
                                   .:^~~^.?~:~^  ^.                 !7^.          .?                
                    .:::::::::^^~7~^^.    ~?: ..:~.:::....         7!              ?:               
                 .~~^:::::::::...!?        !?~~~~7!~!!~~~^::.     ^?.              7:               
                 7:               !7        ^^::.......:^~!!^::   !7               ?.               
               .~?..              .?^                      ^7~:^..J!.::::^^^^~~~~!!J!               
               J7!7!!!~^::..       ~?                 ..:^^~7?777!?777777777!7!!!!~^J:              
              ^7:::^~!!!!7!7!7!!~~^~J~:^:::::^^^^~~!!7777!!!!~~^^^^::.........      !^              
              .^!~^!^.:~::^^^^~~!!~!!7!7!7!7!7!7!!!!~^~^^^^~~~^!7^?                 !~              
                  .:^^~7~^7!:~?:.:~..^~..:^..^!:.:~..!~^::...   ^~J: ^^ :!^ ^~.^?!:^7^              
                         ...:::^^~!^^~~~^~7^^!!!^~~^^:            :~^~~^~^~^^~^^::::.               
EOF
    echo
    echo_blue "Version: ${BOTINOK_VERSION}"

    echo
}

check_root() {
    if [ "$EUID" -ne 0 ]; then 
        echo_red "Please run as root (use sudo)"
        exit 1
    fi
}

install_dependencies() {
    echo_blue "Checking system dependencies..."
    
    if [ "$OS_NAME" = "Darwin" ]; then
        if ! command -v brew >/dev/null 2>&1; then
            echo_red "Homebrew not found. Install it first: https://brew.sh"
            exit 1
        fi
        if [ "$EUID" -eq 0 ]; then
            BREW_USER="${SUDO_USER:-}"
            if [ -n "$BREW_USER" ] && [ "$BREW_USER" != "root" ]; then
                sudo -u "$BREW_USER" brew update
                sudo -u "$BREW_USER" brew install python3 lynx git curl
            else
                echo_red "Do not run Homebrew as root. Run installer via sudo from a normal user (so SUDO_USER is set), or install dependencies manually with brew."
                exit 1
            fi
        else
            brew update
            brew install python3 lynx git curl
        fi
        return 0
    fi

    # Detect package manager (Linux)
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -y
        apt-get install -y python3 python3-venv python3-pip lynx curl git ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-virtualenv python3-pip lynx curl git ca-certificates
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3 python3-virtualenv python3-pip lynx curl git ca-certificates
    else
        echo_red "No supported package manager found (apt-get, dnf, or yum)"
        exit 1
    fi
}

uninstall() {
    echo_blue "Uninstalling BOTINOK..."
    rm -f "$BIN_DIR/botinok"
    rm -rf "$INSTALL_DIR"
    # Оставляем сессии по умолчанию, но можно добавить флаг --purge
    echo_green "BOTINOK has been uninstalled."
    exit 0
}

# --- Main Logic ---

if [ "$1" = "--uninstall" ]; then
    check_root
    uninstall
fi

check_root

echo_blue "Starting BOTINOK installation/update..."

# Detect supported platform
if [ "$OS_NAME" = "Darwin" ]; then
    echo_green "macOS detected."
elif command -v apt-get >/dev/null 2>&1 || command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
    echo_green "Supported package manager detected."
else
    echo_red "No supported package manager found (apt-get, dnf, or yum)."
    exit 1
fi

install_dependencies

# Prepare directories
echo_blue "Preparing directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$SESSIONS_DIR"
mkdir -p "$SKILLS_DIR"
mkdir -p "$EXPERIENCE_DIR"

# Copy/Clone files
if [ -d ".git" ] && [ "$PWD" != "$INSTALL_DIR" ]; then
    echo_blue "Copying files from current directory..."
    cp -r . "$INSTALL_DIR/"
else
    echo_blue "Checking repository in $INSTALL_DIR..."
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo_blue "Existing repository found. Attempting to update..."
        if cd "$INSTALL_DIR" && git pull; then
            echo_green "Successfully updated via git pull."
        else
            echo_red "Failed to update repository (possibly local changes or network issue)."
            printf "Would you like to perform a clean reinstall? (y/N): "
            read confirm
            if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
                echo_blue "Performing clean reinstall..."
                rm -rf "$INSTALL_DIR"
                mkdir -p "$INSTALL_DIR"
                git clone "$GITHUB_REPO" "$INSTALL_DIR"
            else
                echo_red "Update failed. Please resolve conflicts in $INSTALL_DIR manually."
                exit 1
            fi
        fi
    else
        echo_blue "Cloning repository..."
        git clone "$GITHUB_REPO" "$INSTALL_DIR"
    fi
fi

# If this installer is executed via a pipe (e.g. wget|bash), interactive reads may consume script input.
# Re-exec the installer from the cloned/updated file to ensure correct behavior.
if [ -z "$BOTINOK_REEXEC" ]; then
    if [ ! -f "$0" ] || [ "$0" = "bash" ] || [ "$0" = "-" ]; then
        if [ -f "$INSTALL_DIR/install.sh" ]; then
            export BOTINOK_REEXEC=1
            exec bash "$INSTALL_DIR/install.sh" "$@"
        fi
    fi
fi

# Set up Virtual Environment
echo_blue "Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip --trusted-host pypi.org --trusted-host files.pythonhosted.org
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --trusted-host pypi.org --trusted-host files.pythonhosted.org

# Save version to file for non-root users to read
echo "$BOTINOK_VERSION" > "$INSTALL_DIR/.version"
chmod 644 "$INSTALL_DIR/.version"

# Configuration
CONFIG_FILE="$INSTALL_DIR/config.cfg"
if [ ! -f "$CONFIG_FILE" ]; then
    echo_blue "Creating initial config.cfg..."
    cat <<EOF > "$CONFIG_FILE"
[Ollama]
BaseUrl = http://localhost:11434
DefaultModel = qwen3.5:4b
DefaultContext = 16384
RequestTimeout = 300
VerifySSL = false

[Storage]
SessionsDir = $SESSIONS_DIR
SkillsDir = $SKILLS_DIR
ExperienceDir = $EXPERIENCE_DIR
StepsSubDir = steps

[Tools]
LynxUserAgent = Mozilla/5.0 (Compatible; Lynx/2.8.9rel.1; Linux)
LynxMaxChars = 8000
LynxConnectTimeout = 10
LynxReadTimeout = 15

[UI]
ShowVRAM = true
ShowTPS = true
EOF
else
    echo_blue "Config file already exists, skipping creation."
fi

# Create executable wrapper
echo_blue "Creating executable wrapper in $BIN_DIR/botinok..."
cat <<EOF > "$BIN_DIR/botinok"
#!/bin/bash
export BOTINOK_HOME="$INSTALL_DIR"
cd "\$BOTINOK_HOME"
./venv/bin/python3 botinok.py "\$@"
EOF

chmod +x "$BIN_DIR/botinok"

print_banner

LOCALE="${LC_ALL:-${LANG:-}}"
IS_RU=0
case "$LOCALE" in
    ru*|*ru_RU*) IS_RU=1 ;;
esac

if [ "$IS_RU" -eq 1 ]; then
    MSG_TITLE="BOTINOK успешно установлен"
    MSG_VERSION="Установленная версия"
    MSG_INSTALL_DIR="Каталог установки"
    MSG_CONFIG_FILE="Файл конфигурации"
    MSG_SESSIONS_DIR="Каталог сессий"
    MSG_SKILLS_DIR="Каталог скилов"
    MSG_EXPERIENCE_DIR="Каталог опыта"
    MSG_QUICK_START="Быстрый старт"
    MSG_TIP="Подсказка: если нужно отредактировать настройки вручную"
    MSG_WIZARD="Мастер настройки"
    MSG_RUN="Запуск"
else
    MSG_TITLE="BOTINOK successfully installed"
    MSG_VERSION="Installed version"
    MSG_INSTALL_DIR="Install directory"
    MSG_CONFIG_FILE="Config file"
    MSG_SESSIONS_DIR="Sessions dir"
    MSG_SKILLS_DIR="Skills dir"
    MSG_EXPERIENCE_DIR="Experience dir"
    MSG_QUICK_START="Quick start"
    MSG_TIP="Tip: if you need to edit settings manually"
    MSG_WIZARD="Configuration Wizard"
    MSG_RUN="Run"
fi

echo
cat <<EOF
+--------------------------------------------------------------+
| $MSG_TITLE
| 
| $MSG_VERSION:   ${BOTINOK_VERSION}
| $MSG_INSTALL_DIR:  ${INSTALL_DIR}
| $MSG_CONFIG_FILE:  ${INSTALL_DIR}/config.cfg
| $MSG_SESSIONS_DIR: ${SESSIONS_DIR}
| $MSG_SKILLS_DIR:   ${SKILLS_DIR}
| $MSG_EXPERIENCE_DIR: ${EXPERIENCE_DIR}
| 
| $MSG_QUICK_START:
|   $MSG_RUN:     botinok
|   $MSG_WIZARD:  botinok --wizard
| 
| $MSG_TIP:
|   nano ${INSTALL_DIR}/config.cfg
+--------------------------------------------------------------+
EOF
