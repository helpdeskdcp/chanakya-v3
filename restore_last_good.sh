#!/bin/bash
echo "=== RESTORING LAST KNOWN GOOD ==="

if [ -f ".last_known_good" ]; then
    SHA=$(grep SHA .last_known_good | cut -d= -f2)
    echo "Restoring to: $SHA"
    git checkout $SHA -- templates/index_v3.html app/main.py
    echo "✅ Restored! Restart server:"
    echo "pkill -f start_v3; sleep 2; nohup python3 start_v3.py > logs/trading.log 2>&1 &"
elif [ -f "templates/index_v3.html.bak" ]; then
    echo "Restoring from .bak files"
    cp templates/index_v3.html.bak templates/index_v3.html
    cp app/main.py.bak app/main.py
    echo "✅ Restored from backup files"
else
    echo "❌ No backup found!"
    echo "Use: git log --oneline to find stable commit"
    echo "Then: git checkout <SHA> -- templates/index_v3.html app/main.py"
fi
