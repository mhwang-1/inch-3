#!/bin/bash
# tts-generate.sh
# Calls a TTS API endpoint and saves the audio to a file.
#
# Usage: bash scripts/tts-generate.sh <text> <output_path> [speed]
#
# Required env vars:
#   INCH_TTS_ENDPOINT  — TTS API URL (e.g. https://api.openai.com/v1/audio/speech)
#   INCH_TTS_MODEL     — Model name (e.g. tts-1)
#   INCH_TTS_VOICE     — Voice ID (e.g. alloy)
#   INCH_TTS_API_KEY   — API key for TTS service
#
# Arguments:
#   $1 — text to speak
#   $2 — output file path (e.g. /tmp/inch3-block-1.ogg)
#   $3 — speed (default: 0.85)
#
# Exit codes:
#   0 — success, audio written to output path
#   1 — error (missing args, missing env vars, API failure, empty response)

set -euo pipefail

TEXT="${1:-}"
OUTPUT_PATH="${2:-}"
SPEED="${3:-0.85}"

# Validate arguments
if [ -z "$TEXT" ]; then
    echo "ERROR: No text provided." >&2
    exit 1
fi
if [ -z "$OUTPUT_PATH" ]; then
    echo "ERROR: No output path provided." >&2
    exit 1
fi

# Validate env vars
for VAR in INCH_TTS_ENDPOINT INCH_TTS_MODEL INCH_TTS_VOICE INCH_TTS_API_KEY; do
    if [ -z "${!VAR:-}" ]; then
        echo "ERROR: $VAR not set." >&2
        exit 1
    fi
done

# Build JSON payload using python3 for safe escaping
PAYLOAD=$(python3 -c "
import sys, json
print(json.dumps({
    'model': sys.argv[1],
    'input': sys.argv[2],
    'voice': sys.argv[3],
    'speed': float(sys.argv[4]),
    'response_format': 'opus'
}))
" "$INCH_TTS_MODEL" "$TEXT" "$INCH_TTS_VOICE" "$SPEED")

# Call TTS API
HTTP_CODE=$(curl -sf -w "%{http_code}" \
    -X POST "$INCH_TTS_ENDPOINT" \
    -H "Authorization: Bearer $INCH_TTS_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    -o "$OUTPUT_PATH")

# Validate response
if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: TTS API returned HTTP $HTTP_CODE" >&2
    rm -f "$OUTPUT_PATH"
    exit 1
fi

if [ ! -s "$OUTPUT_PATH" ]; then
    echo "ERROR: TTS API returned empty audio." >&2
    rm -f "$OUTPUT_PATH"
    exit 1
fi

echo "Audio saved to $OUTPUT_PATH"
