#!/bin/bash
FEATURE=$1
if [ -z "$FEATURE" ]; then
    echo "Usage: bash feature_add.sh <feature_name>"
    echo "Example: bash feature_add.sh 'telegram_alerts'"
    exit 1
fi

echo "=== ADDING FEATURE: $FEATURE ==="

# Step 1: Save current state
bash safe_update.sh

# Step 2: Test current state
echo "Testing current state..."
STATUS=$(curl -sf http://127.0.0.1:5001/api/v3/status | python3 -m json.tool | grep connected)
if [ -z "$STATUS" ]; then
    echo "❌ Server not responding — fix first!"
    exit 1
fi
echo "✅ Server OK — safe to proceed"

# Step 3: Reminder
echo ""
echo "BEFORE ADDING FEATURE:"
echo "1. py_compile check after every edit"
echo "2. Balance check (JS {})"  
echo "3. Test login after template changes"
echo "4. git commit after each working step"
echo ""
echo "TEMPLATE CHANGES: Always use python3 file edits (not heredoc)"
echo "JS CHANGES: No optional chaining (?.) — use && instead"
echo ""
