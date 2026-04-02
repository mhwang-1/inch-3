#!/bin/bash
# backup-db.sh
# Creates a consistent daily backup of inch-3.db using SQLite's VACUUM INTO.
# Idempotent: skips if today's backup already exists.
# Enforces a rolling 10-day retention limit.
#
# Usage: bash scripts/backup-db.sh
# Run from any directory — uses paths relative to this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$REPO_ROOT/data"
DB_FILE="$DATA_DIR/inch-3.db"
MAX_BACKUPS=10

# Verify database exists
if [ ! -f "$DB_FILE" ]; then
    echo "INFO: Database not found at $DB_FILE. Skipping backup."
    exit 0
fi

# Check if sqlite3 is available
if ! command -v sqlite3 &>/dev/null; then
    echo "ERROR: sqlite3 not found. Install sqlite3 to enable backups."
    exit 1
fi

# Idempotency: skip if any backup for today already exists
TODAY=$(date +"%Y%m%d")
if ls "$DATA_DIR"/inch-3_${TODAY}_*.db 2>/dev/null | head -1 | grep -q .; then
    echo "INFO: Backup for today ($TODAY) already exists. Skipping."
    exit 0
fi

# Create WAL-safe backup using SQLite's VACUUM INTO
# This acquires a read lock, checkpoints the WAL, and writes a single consistent file.
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$DATA_DIR/inch-3_${TIMESTAMP}.db"

echo "Creating backup: $(basename "$BACKUP_FILE") ..."
sqlite3 "$DB_FILE" "VACUUM INTO '$BACKUP_FILE'"
echo "Backup created successfully."

# Enforce rolling retention: keep only the MAX_BACKUPS most recent backups
BACKUP_LIST=$(ls -1t "$DATA_DIR"/inch-3_????????_??????.db 2>/dev/null || true)
BACKUP_COUNT=$(echo "$BACKUP_LIST" | grep -c . || true)

if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    EXCESS=$(echo "$BACKUP_LIST" | tail -n +"$((MAX_BACKUPS + 1))")
    echo "Pruning old backups (keeping $MAX_BACKUPS of $BACKUP_COUNT):"
    echo "$EXCESS" | while IFS= read -r OLD_BACKUP; do
        [ -z "$OLD_BACKUP" ] && continue
        echo "  Deleting: $(basename "$OLD_BACKUP")"
        rm -f "$OLD_BACKUP"
    done
fi

FINAL_COUNT=$(ls -1 "$DATA_DIR"/inch-3_????????_??????.db 2>/dev/null | wc -l || echo 0)
echo "Done. $FINAL_COUNT backup(s) retained in $DATA_DIR."
