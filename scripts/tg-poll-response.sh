#!/bin/bash
# tg-poll-response.sh
# Polls Telegram getUpdates for the next message from the user.
# Clears the update queue before polling to avoid stale messages.
#
# Usage: bash scripts/tg-poll-response.sh [timeout_seconds]
# Default timeout: 900 seconds (15 minutes).
# Override via INCH_POLL_TIMEOUT env var or first CLI argument.
# Outputs the user's message text to stdout.
# Exits with code 1 on timeout or error.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DB_FILE="$REPO_ROOT/data/inch-3.db"

TIMEOUT="${INCH_POLL_TIMEOUT:-${1:-900}}"

# Retrieve bot token from environment or database
if [ -z "${INCH_BOT_TOKEN:-}" ]; then
    INCH_BOT_TOKEN=$(sqlite3 "$DB_FILE" "SELECT bot_token FROM telegram_config WHERE id=1 LIMIT 1;" 2>/dev/null || echo "")
fi
if [ -z "${INCH_BOT_TOKEN:-}" ]; then
    echo "ERROR: bot_token not configured. Run /inch-connect-telegram first." >&2
    exit 1
fi

# Retrieve expected chat_id from environment or database
if [ -z "${INCH_CHAT_ID:-}" ]; then
    INCH_CHAT_ID=$(sqlite3 "$DB_FILE" "SELECT chat_id FROM telegram_config WHERE id=1 LIMIT 1;" 2>/dev/null || echo "")
fi
CHAT_ID="$INCH_CHAT_ID"
if [ -z "$CHAT_ID" ]; then
    echo "ERROR: chat_id not configured." >&2
    exit 1
fi

# Flush ALL pending updates before polling.
# offset=-1 tells Telegram to return only the latest update and confirm
# all earlier ones. We then advance past that latest update too, so the
# poll loop only sees messages sent AFTER this point.
CLEAR_RESP=$(curl -sf "https://api.telegram.org/bot${INCH_BOT_TOKEN}/getUpdates?offset=-1&timeout=0&allowed_updates=%5B%22message%22%5D")
LAST_ID=$(echo "$CLEAR_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
results = d.get('result', [])
if results:
    print(results[-1]['update_id'])
else:
    print(0)
" 2>/dev/null || echo "0")

# Advance offset past the latest update — only truly new messages will be seen
OFFSET=$((LAST_ID + 1))

# Poll loop
DEADLINE=$((SECONDS + TIMEOUT))
while [ "$SECONDS" -lt "$DEADLINE" ]; do
    REMAINING=$((DEADLINE - SECONDS))
    POLL_TIMEOUT=$(( REMAINING < 20 ? REMAINING : 20 ))
    [ "$POLL_TIMEOUT" -le 0 ] && break

    RESP=$(curl -sf "https://api.telegram.org/bot${INCH_BOT_TOKEN}/getUpdates?offset=${OFFSET}&timeout=${POLL_TIMEOUT}&allowed_updates=%5B%22message%22%5D" || echo "")

    if [ -z "$RESP" ]; then
        continue
    fi

    RESULT=$(echo "$RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
chat_id = '$CHAT_ID'
for update in d.get('result', []):
    msg = update.get('message', {})
    if str(msg.get('chat', {}).get('id', '')) == str(chat_id):
        text = msg.get('text', '').strip()
        if text:
            print(update['update_id'])
            print(text)
            break
" 2>/dev/null || echo "")

    if [ -n "$RESULT" ]; then
        UPDATE_ID=$(echo "$RESULT" | head -1)
        MSG_TEXT=$(echo "$RESULT" | tail -n +2)
        # Advance offset
        OFFSET=$((UPDATE_ID + 1))
        echo "$MSG_TEXT"
        exit 0
    fi
done

echo "TIMEOUT" >&2
exit 1
