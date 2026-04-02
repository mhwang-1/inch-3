#!/bin/bash
# tg-send-audio.sh
# Sends a local audio file to the configured Telegram chat as a voice message.
#
# Usage: bash scripts/tg-send-audio.sh <audio-file-path>
# Audio file should be OGG/Opus format for best Telegram compatibility.
#
# Reads BOT_TOKEN from data/inch-3.db (telegram_config.bot_token) or INCH_BOT_TOKEN env var.
# Reads CHAT_ID from data/inch-3.db.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DB_FILE="$REPO_ROOT/data/inch-3.db"

AUDIO_FILE="${1:-}"
if [ -z "$AUDIO_FILE" ] || [ ! -f "$AUDIO_FILE" ]; then
    echo "ERROR: Audio file not found: $AUDIO_FILE" >&2
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
    echo "ERROR: chat_id not configured. Run /inch-connect-telegram first." >&2
    exit 1
fi

# Send voice message
RESPONSE=$(curl -sf \
    -X POST "https://api.telegram.org/bot${INCH_BOT_TOKEN}/sendVoice" \
    -F "chat_id=${CHAT_ID}" \
    -F "voice=@${AUDIO_FILE}" \
    -F "disable_notification=false")

OK=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok','false'))" 2>/dev/null || echo "false")
if [ "$OK" != "True" ] && [ "$OK" != "true" ]; then
    echo "ERROR: Telegram sendVoice failed: $RESPONSE" >&2
    exit 1
fi

echo "Audio sent successfully."
