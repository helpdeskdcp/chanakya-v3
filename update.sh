#!/bin/bash
# ============================================================
# CHANAKYA AI v3 — One-Key Update Script
# Run on any system to pull latest from GitHub
# ============================================================
set -e
GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}=== CHANAKYA AI v3 — UPDATE ===${NC}"

# Pull latest
git pull origin main
echo -e "${GREEN}✅ Code updated${NC}"

# Install new requirements if any
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null
pip install -r requirements.txt -q
echo -e "${GREEN}✅ Requirements updated${NC}"

# Verify
python3 -m py_compile app/main.py && echo -e "${GREEN}✅ Syntax OK${NC}"

# Restart
if command -v systemctl &>/dev/null && systemctl is-active chanakya-v3.service &>/dev/null; then
    systemctl restart chanakya-v3.service
    sleep 5
    systemctl is-active chanakya-v3.service && echo -e "${GREEN}✅ Service restarted${NC}"
else
    pkill -f "start_v3" 2>/dev/null || true
    sleep 2
    nohup python3 start_v3.py > logs/trading.log 2>&1 &
    sleep 8
fi

# Health check
if curl -sf http://127.0.0.1:5001/api/v3/status > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Chanakya AI v3 running!${NC}"
    echo -e "  Version: $(git log --oneline -1)"
    echo -e "  Dashboard: http://localhost:5001/v3"
else
    echo "⚠️ Check logs: tail -f logs/trading.log"
fi
