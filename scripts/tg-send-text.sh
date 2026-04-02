#!/bin/bash
# tg-send-text.sh
# Sends a text message to the configured Telegram chat.
#
# Usage: bash scripts/tg-send-text.sh "Your message here"
# Supports Markdown formatting (parse_mode=Markdown).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DB_FILE="$REPO_ROOT/data/inch-3.db"

MESSAGE="${1:-}"
if [ -z "$MESSAGE" ]; then
    echo "ERROR: No message provided." >&2
    exit 1
fi

# Retrieve bot token from environment or database
if [ -z "${INCH_BOT_TOKEN:-}" ]; then
    INCH_BOT_TOKEN=$(sqlite3 "$DB_FILE" "SELECT bot_token FROM telegram_config WHERE id=1 LIMIT 1;" 2>/dev/null || echo "")
fi
if [ -z "${INCH_BOT_TOKEN:-}" ]; then
    echo "ERROR: bot_token not configured. Run /inch-connect-telegram first." >&2
    exit 1
fi

# Retrieve chat_id from environment or database
if [ -z "${INCH_CHAT_ID:-}" ]; then
    INCH_CHAT_ID=$(sqlite3 "$DB_FILE" "SELECT chat_id FROM telegram_config WHERE id=1 LIMIT 1;" 2>/dev/null || echo "")
fi
CHAT_ID="$INCH_CHAT_ID"
if [ -z "$CHAT_ID" ]; then
    echo "ERROR: chat_id not configured." >&2
    exit 1
fi

RESPONSE=$(curl -sf \
    -X POST "https://api.telegram.org/bot${INCH_BOT_TOKEN}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "{\"chat_id\": \"${CHAT_ID}\", \"text\": $(python3 -c "import sys,json; print(json.dumps(sys.argv[1]))" "$MESSAGE"), \"parse_mode\": \"Markdown\"}")

OK=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok','false'))" 2>/dev/null || echo "false")
if [ "$OK" != "True" ] && [ "$OK" != "true" ]; then
    echo "ERROR: Telegram sendMessage failed: $RESPONSE" >&2
    exit 1
fi

echo "Message sent."
