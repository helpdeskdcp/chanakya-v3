#!/bin/bash
# ============================================================
# CHANAKYA AI v3 — One-Click Setup Script
# Supports: Debian/Ubuntu (Linux) + Windows (WSL/Git Bash)
# ============================================================

set -e
REPO_URL="https://github.com/helpdeskdcp/chanakya-v3.git"
APP_DIR="chanakya_v3"
PYTHON_MIN="3.10"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo -e "${BLUE}"
echo "  ██████╗██╗  ██╗ █████╗ ███╗   ██╗ █████╗ ██╗  ██╗██╗   ██╗ █████╗ "
echo "  ██╔════╝██║  ██║██╔══██╗████╗  ██║██╔══██╗██║ ██╔╝╚██╗ ██╔╝██╔══██╗"
echo "  ██║     ███████║███████║██╔██╗ ██║███████║█████╔╝  ╚████╔╝ ███████║"
echo "  ██║     ██╔══██║██╔══██║██║╚██╗██║██╔══██║██╔═██╗   ╚██╔╝  ██╔══██║"
echo "  ╚██████╗██║  ██║██║  ██║██║ ╚████║██║  ██║██║  ██╗   ██║   ██║  ██║"
echo "   ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝"
echo "  AI Trading Platform v3.0 — Setup Script"
echo -e "${NC}"

# ── OS Detection ─────────────────────────────────────────
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if [ -f /etc/debian_version ]; then
            OS="debian"
        elif [ -f /etc/redhat-release ]; then
            OS="redhat"
        else
            OS="linux"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
        OS="windows"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        OS="wsl"
    else
        OS="unknown"
    fi
    info "Detected OS: $OS"
}

# ── OS Selection Menu ────────────────────────────────────
select_os() {
    echo ""
    echo -e "${YELLOW}Select your OS:${NC}"
    echo "  1) Debian/Ubuntu Linux (VPS/Server)"
    echo "  2) Windows (WSL2)"
    echo "  3) macOS"
    echo "  4) Auto-detect"
    echo ""
    read -p "Enter choice [1-4] (default: 4): " choice
    case $choice in
        1) OS="debian" ;;
        2) OS="wsl" ;;
        3) OS="macos" ;;
        *) detect_os ;;
    esac
    success "Using OS: $OS"
}

# ── Install System Dependencies ──────────────────────────
install_deps() {
    info "Installing system dependencies..."
    if [[ "$OS" == "debian" ]] || [[ "$OS" == "wsl" ]]; then
        apt-get update -qq
        apt-get install -y -qq \
            python3 python3-pip python3-venv \
            git curl wget build-essential \
            libssl-dev libffi-dev python3-dev \
            sqlite3 2>/dev/null || warn "Some packages failed"
        success "Debian deps installed"

    elif [[ "$OS" == "macos" ]]; then
        if ! command -v brew &>/dev/null; then
            warn "Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        brew install python3 git sqlite3 2>/dev/null || true
        success "macOS deps installed"

    elif [[ "$OS" == "windows" ]]; then
        warn "Windows detected. Please ensure Python 3.10+ is installed."
        warn "Download from: https://www.python.org/downloads/"
    fi
}

# ── Clone / Update Repo ──────────────────────────────────
setup_repo() {
    if [ -d "$APP_DIR" ]; then
        info "Repo exists — pulling latest..."
        cd "$APP_DIR"
        git pull origin main
        cd ..
    else
        info "Cloning Chanakya AI v3..."
        git clone "$REPO_URL" "$APP_DIR"
    fi
    success "Repo ready: $APP_DIR"
}

# ── Python Virtual Environment ───────────────────────────
setup_venv() {
    info "Setting up Python virtual environment..."
    cd "$APP_DIR"
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate || . venv/Scripts/activate 2>/dev/null
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    success "Virtual environment ready"
}

# ── Environment Config ───────────────────────────────────
setup_env() {
    info "Setting up environment config..."
    if [ ! -f ".env" ]; then
        cp .env.example .env 2>/dev/null || cat > .env << 'ENVEOF'
# Chanakya AI v3 — Environment Config
# Fill in your Angel One credentials

ANGEL_API_KEY=your_api_key_here
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_password
ANGEL_TOTP_KEY=your_totp_key

PAPER_MODE=true
PAPER_CAPITAL=100000

TELEGRAM_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id

SECRET_KEY=chanakya_secret_2026
FLASK_PORT=5001
ENVEOF
        warn ".env created — fill in your credentials!"
    else
        success ".env already exists"
    fi
}

# ── Database Init ────────────────────────────────────────
setup_db() {
    info "Initializing database..."
    source venv/bin/activate || . venv/Scripts/activate 2>/dev/null
    python3 -c "
import sys; sys.path.insert(0,'.')
from data.users import init_db
init_db()
print('DB initialized')
" 2>/dev/null || warn "DB init skipped"
    success "Database ready"
}

# ── Systemd Service (Linux only) ─────────────────────────
setup_service() {
    if [[ "$OS" == "debian" ]] && command -v systemctl &>/dev/null; then
        info "Setting up systemd service..."
        INSTALL_DIR="$(pwd)/$APP_DIR"
        cat > /etc/systemd/system/chanakya-v3.service << SVCEOF
[Unit]
Description=Chanakya AI v3 Trading System
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 start_v3.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/trading.log
StandardError=append:$INSTALL_DIR/logs/trading.log

[Install]
WantedBy=multi-user.target
SVCEOF
        systemctl daemon-reload
        systemctl enable chanakya-v3.service
        success "Systemd service installed"
    fi
}

# ── Start Application ────────────────────────────────────
start_app() {
    info "Starting Chanakya AI v3..."
    cd "$APP_DIR" 2>/dev/null || true
    mkdir -p logs
    source venv/bin/activate || . venv/Scripts/activate 2>/dev/null

    if [[ "$OS" == "debian" ]] && command -v systemctl &>/dev/null; then
        systemctl start chanakya-v3.service
        sleep 5
        if systemctl is-active chanakya-v3.service &>/dev/null; then
            success "Service started via systemd"
        fi
    else
        nohup python3 start_v3.py > logs/trading.log 2>&1 &
        sleep 8
    fi

    # Health check
    if curl -sf http://127.0.0.1:5001/api/v3/status > /dev/null 2>&1; then
        success "Chanakya AI v3 is RUNNING!"
        echo ""
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}  ✅ CHANAKYA AI v3 — ONLINE!${NC}"
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "  Dashboard: ${CYAN}http://localhost:5001/v3${NC}"
        echo -e "  Admin:     ${CYAN}http://localhost:5001/v3/admin${NC}"
        echo -e "  API:       ${CYAN}http://localhost:5001/api/v3/status${NC}"
        echo ""
        echo -e "  Default login: ${YELLOW}avinash / chanakya2026${NC}"
        echo ""
    else
        warn "Server starting... check logs/trading.log"
    fi
}

# ── Main ─────────────────────────────────────────────────
main() {
    echo -e "${CYAN}Starting setup...${NC}"
    select_os
    install_deps
    setup_repo
    setup_venv
    setup_env
    setup_db
    setup_service
    start_app
    echo -e "${GREEN}Setup complete!${NC}"
}

main "$@"
