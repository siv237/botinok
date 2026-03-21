#!/bin/bash

# BOTINOK INSTALLER (Ollama style)
# This script installs BOTINOK AGENT to /opt/botinok and creates a symlink in /usr/local/bin

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

 BOTINOK_VERSION="0.1 (2026-03-21)"

INSTALL_DIR="/opt/botinok"
BIN_DIR="/usr/local/bin"
SESSIONS_DIR="/var/log/botinok/sessions"
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
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip lynx curl git ca-certificates
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

# Detect OS
if [ -f /etc/debian_version ]; then
    echo_green "Debian-based system detected."
else
    echo_red "This script is designed for Debian-based distributions."
    exit 1
fi

install_dependencies

# Prepare directories
echo_blue "Preparing directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$SESSIONS_DIR"
chmod 777 "$SESSIONS_DIR"

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

# Set up Virtual Environment
echo_blue "Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# Configuration
CONFIG_FILE="$INSTALL_DIR/config.cfg"
if [ ! -f "$CONFIG_FILE" ]; then
    echo_blue "Creating initial config.cfg..."
    cat <<EOF > "$CONFIG_FILE"
[Ollama]
BaseUrl = http://ollama.localnet:11434
DefaultModel = qwen3.5:4b
DefaultContext = 8192
RequestTimeout = 300

[Storage]
SessionsDir = $SESSIONS_DIR
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

# Run Configuration Wizard (Interactive)
echo
printf "Would you like to run the Configuration Wizard now? (Y/n): "
read run_wizard
if [ "$run_wizard" = "n" ] || [ "$run_wizard" = "N" ]; then
    echo_blue "Skipping configuration. You can run it later with: botinok --wizard"
else
    echo_blue "Launching Configuration Wizard..."
    "$BIN_DIR/botinok" --wizard
fi

print_banner

echo_green "BOTINOK has been successfully installed!"
echo -e "You can now run it by typing: ${BLUE}botinok${NC}"
