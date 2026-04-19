#!/bin/bash
# Safe update script — backup before any change
echo "=== SAFE UPDATE SCRIPT ==="

# Auto backup before change
BACKUP_COMMIT=$(git log --oneline -1 | awk '{print $1}')
echo "Current stable: $BACKUP_COMMIT"
echo "Saving to .last_known_good"
echo "SHA=$BACKUP_COMMIT" > .last_known_good
echo "DATE=$(date)" >> .last_known_good

# Backup templates + main.py
cp templates/index_v3.html templates/index_v3.html.bak
cp app/main.py app/main.py.bak

echo "✅ Backup created"
echo "To restore: bash restore_last_good.sh"
