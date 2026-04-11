#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""
anki-export.py — push queued vocab items to Anki via AnkiConnect.

Called by: /inch-export-anki-cards (manual, user-invoked only).

Single source of truth for the Anki export operation. Reads un-exported
anki_vocab_items rows for the given language profile, partitions them
into short (word_count < MAX_WORDS) and long items, generates TTS audio
for sentences and expressions, merges them with a 2-second pause via
ffmpeg, pushes short items to Anki, and marks rows as exported. Long
items are auto-pruned after the first successful export so they don't
reappear in future runs.

--dry-run emits a JSON preview of both buckets on stdout so the caller
can display the list and ask for user confirmation before a real run.

Environment variables (inherited from caller):
  INCH_TTS_ENDPOINT, INCH_TTS_MODEL, INCH_TTS_VOICE, INCH_TTS_API_KEY,
  INCH_TTS_SPEED_NORMAL

Usage:
  uv run scripts/anki-export.py --lang-profile-id <int> [--dry-run]
  uv run scripts/anki-export.py --lang-profile-id <int> --db-path <path>
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import requests

DEFAULT_DB_PATH = Path("data/inch-3.db")
MEDIA_ROOT = Path("data/anki-media")
SENTENCE_CACHE_DIR = MEDIA_ROOT / "sentences"
TMP_DIR = MEDIA_ROOT / "tmp"
NOTE_TYPE_NAME = "Inch 3 Vocab"

# Expressions with word_count >= MAX_WORDS are not good Anki material
# (too long to serve as atomic vocabulary cards). They are filtered out
# of the export list and marked as pruned_at on successful export.
MAX_WORDS = 6


def word_count(s: str) -> int:
    """Count whitespace-separated words, treating hyphenated forms as one."""
    s = re.sub(r"[^\w\s'-]", " ", s)
    return len([w for w in s.split() if w])


def sentence_filename(lang_code: str, sentence_id: int) -> str:
    return f"inch3_{lang_code}_s{sentence_id}_sentence.mp3"


def expression_filename(lang_code: str, item_id: int) -> str:
    return f"inch3_{lang_code}_v{item_id}_expr.mp3"


def combo_filename(lang_code: str, item_id: int) -> str:
    return f"inch3_{lang_code}_v{item_id}_combo.mp3"


def sound_tag(filename: str) -> str:
    return f"[sound:{filename}]"


ANKI_TIMEOUT_SECONDS = 30


class AnkiConnectError(RuntimeError):
    """Raised when AnkiConnect returns an error in the response payload."""


class AnkiConnectClient:
    """Thin wrapper around the AnkiConnect HTTP API (version 6)."""

    def __init__(self, base_url: str, api_key: str | None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def call(self, action: str, **params):
        body: dict = {"action": action, "version": 6}
        if params:
            body["params"] = params
        if self.api_key:
            body["key"] = self.api_key
        response = requests.post(self.base_url, json=body, timeout=ANKI_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise AnkiConnectError(payload["error"])
        return payload.get("result")


TTS_TIMEOUT_SECONDS = 60
_TTS_REQUIRED_ENV = (
    "INCH_TTS_ENDPOINT",
    "INCH_TTS_MODEL",
    "INCH_TTS_VOICE",
    "INCH_TTS_API_KEY",
    "INCH_TTS_SPEED_NORMAL",
)


def tts_generate(text: str, output_path: Path) -> None:
    """Call the configured TTS endpoint and write an mp3 file to output_path."""
    for var in _TTS_REQUIRED_ENV:
        if not os.environ.get(var):
            raise RuntimeError(f"{var} environment variable not set")

    endpoint = os.environ["INCH_TTS_ENDPOINT"]
    payload = {
        "model": os.environ["INCH_TTS_MODEL"],
        "input": text,
        "voice": os.environ["INCH_TTS_VOICE"],
        "speed": float(os.environ["INCH_TTS_SPEED_NORMAL"]),
        "response_format": "mp3",
    }
    headers = {
        "Authorization": f"Bearer {os.environ['INCH_TTS_API_KEY']}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        endpoint, json=payload, headers=headers, timeout=TTS_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    if output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("TTS API returned empty audio")


def merge_audio(
    sentence_path: Path,
    expression_path: Path,
    combo_path: Path,
    pause_seconds: int = 2,
) -> None:
    """Concatenate sentence + N seconds of silence + expression into combo_path.

    Uses ffmpeg's apad filter to append silence to the sentence audio in its
    native sample rate, then concats with the expression. No separate silence
    file needed; no sample-rate mismatch risk.
    """
    combo_path.parent.mkdir(parents=True, exist_ok=True)
    filter_expr = (
        f"[0:a]apad=pad_dur={pause_seconds}[a0];"
        f"[a0][1:a]concat=n=2:v=0:a=1"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(sentence_path),
        "-i", str(expression_path),
        "-filter_complex", filter_expr,
        str(combo_path),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {result.returncode}): {result.stderr.decode('utf-8', errors='replace')}"
        )


def load_anki_config(conn: sqlite3.Connection) -> dict | None:
    """Return the singleton anki_config row as a dict, or None if missing."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT host, port, api_key, is_active FROM anki_config WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def load_unexported_items(conn: sqlite3.Connection, lang_profile_id: int) -> list[dict]:
    """Return queued vocab items for one language profile, oldest first.

    sentence_l1 is pulled from the 'full sentence' sentence_blocks row for
    the same sentence. Each sentence has exactly one such row; if it is
    missing, sentence_l1 falls back to an empty string so the note still
    validates against AnkiConnect.
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT av.id, av.sentence_id, av.expression, av.expression_l1,
               s.l2_text AS sentence_l2,
               COALESCE(
                   (SELECT b.l1_text FROM sentence_blocks b
                    WHERE b.sentence_id = av.sentence_id
                      AND b.role = 'full sentence'
                    LIMIT 1),
                   ''
               ) AS sentence_l1,
               lp.lang_code
        FROM anki_vocab_items av
        JOIN sentences s ON s.id = av.sentence_id
        JOIN language_profiles lp ON lp.id = av.lang_profile_id
        WHERE av.lang_profile_id = ?
          AND av.exported_at IS NULL
          AND av.pruned_at IS NULL
        ORDER BY av.captured_at ASC
        """,
        (lang_profile_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_exported(conn: sqlite3.Connection, item_id: int, anki_note_id: int) -> None:
    """Set exported_at and anki_note_id for one row. Commits immediately."""
    conn.execute(
        "UPDATE anki_vocab_items "
        "SET exported_at = CURRENT_TIMESTAMP, anki_note_id = ? "
        "WHERE id = ?",
        (anki_note_id, item_id),
    )
    conn.commit()


CARD_A_FRONT = "{{ComboAudio}}"

CARD_A_BACK = """{{FrontSide}}
<hr id=answer>
<div class="expr-l2">{{Expression}}</div>
<div class="expr-l1">{{ExpressionL1}}</div>
<div class="sentence-l2">{{SentenceL2}}</div>
<div class="sentence-l1">{{SentenceL1}}</div>"""

CARD_B_FRONT = """{{SentenceAudio}}
<br>
<div class="expr-l1">{{ExpressionL1}}</div>"""

CARD_B_BACK = """{{FrontSide}}
<hr id=answer>
{{ExpressionAudio}}
<div class="expr-l2">{{Expression}}</div>
<div class="sentence-l2">{{SentenceL2}}</div>
<div class="sentence-l1">{{SentenceL1}}</div>"""

CARD_CSS = """.card {
  font-family: -apple-system, "Segoe UI", sans-serif;
  font-size: 20px;
  text-align: center;
  color: #222;
  background: #fafafa;
}
.expr-l2 { font-size: 28px; font-weight: 600; margin: 16px 0 8px; }
.expr-l1 { font-size: 22px; color: #555; margin: 12px 0; }
.sentence-l2 { font-size: 16px; color: #888; margin-top: 20px; }
.sentence-l1 { font-size: 15px; color: #999; margin-top: 4px; }
"""


def ensure_deck(client: "AnkiConnectClient", deck_name: str) -> None:
    """Idempotently create the deck."""
    client.call("createDeck", deck=deck_name)


def ensure_model(client: "AnkiConnectClient") -> None:
    """Create the 'Inch 3 Vocab' note type if it does not already exist."""
    existing = client.call("modelNames") or []
    if NOTE_TYPE_NAME in existing:
        return
    client.call(
        "createModel",
        modelName=NOTE_TYPE_NAME,
        inOrderFields=[
            "SentenceL2", "SentenceL1", "SentenceAudio", "ComboAudio",
            "Expression", "ExpressionAudio", "ExpressionL1",
        ],
        css=CARD_CSS,
        cardTemplates=[
            {"Name": "Card A — L1 to L2 audio",
             "Front": CARD_A_FRONT, "Back": CARD_A_BACK},
            {"Name": "Card B — L2 audio + L1 to L2 audio",
             "Front": CARD_B_FRONT, "Back": CARD_B_BACK},
        ],
    )


def store_media_file(client: "AnkiConnectClient", path: Path) -> None:
    """Push a local file to Anki's media folder under its basename."""
    data_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    client.call("storeMediaFile", filename=path.name, data=data_b64)


def add_vocab_note(
    client: "AnkiConnectClient", item: dict, deck_name: str
) -> int:
    """Create one note via addNote and return the new note ID."""
    lang_code = item["lang_code"]
    sentence_id = item["sentence_id"]
    item_id = item["id"]
    note_payload = {
        "deckName": deck_name,
        "modelName": NOTE_TYPE_NAME,
        "fields": {
            "SentenceL2": item["sentence_l2"],
            "SentenceL1": item.get("sentence_l1") or "",
            "SentenceAudio": sound_tag(sentence_filename(lang_code, sentence_id)),
            "ComboAudio": sound_tag(combo_filename(lang_code, item_id)),
            "Expression": item["expression"],
            "ExpressionAudio": sound_tag(expression_filename(lang_code, item_id)),
            "ExpressionL1": item["expression_l1"],
        },
        "tags": ["inch3", f"lang:{lang_code}"],
        "options": {"allowDuplicate": True},
    }
    return client.call("addNote", note=note_payload)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export Inch 3 vocab items to Anki.")
    p.add_argument("--lang-profile-id", type=int, required=True,
                   help="Language profile ID (from language_profiles.id).")
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH,
                   help="Path to the SQLite database (default: data/inch-3.db).")
    p.add_argument("--dry-run", action="store_true",
                   help="List queued items and exit without calling AnkiConnect.")
    return p.parse_args(argv)


def partition_by_word_count(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split items into (to_export, filtered_long) based on MAX_WORDS."""
    to_export: list[dict] = []
    filtered_long: list[dict] = []
    for it in items:
        if word_count(it["expression"]) >= MAX_WORDS:
            filtered_long.append(it)
        else:
            to_export.append(it)
    return to_export, filtered_long


def mark_pruned(conn: sqlite3.Connection, item_ids: list[int]) -> None:
    """Set pruned_at = CURRENT_TIMESTAMP for the given item ids. Commits."""
    if not item_ids:
        return
    conn.executemany(
        "UPDATE anki_vocab_items SET pruned_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(i,) for i in item_ids],
    )
    conn.commit()


def _preview_row(it: dict) -> dict:
    """Compact dict for JSON preview output."""
    return {
        "id": it["id"],
        "sentence_id": it["sentence_id"],
        "expression": it["expression"],
        "expression_l1": it["expression_l1"],
        "word_count": word_count(it["expression"]),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db_path.exists():
        print(f"ERROR: database not found at {args.db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(args.db_path))
    try:
        items = load_unexported_items(conn, args.lang_profile_id)

        if args.dry_run:
            # Emit a JSON preview so the calling skill can display the list
            # and ask the user for confirmation before a real run.
            to_export, filtered_long = partition_by_word_count(items)
            lang_code = items[0]["lang_code"] if items else None
            preview = {
                "lang_profile_id": args.lang_profile_id,
                "lang_code": lang_code,
                "total_pending": len(items),
                "max_words": MAX_WORDS,
                "to_export": [_preview_row(it) for it in to_export],
                "filtered_long": [_preview_row(it) for it in filtered_long],
            }
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return 0

        if not items:
            print("[anki-export] 0 items to export — queue empty")
            return 0

        to_export, filtered_long = partition_by_word_count(items)
        lang_code = items[0]["lang_code"]
        print(
            f"[anki-export] {len(to_export)} items to export for lang={lang_code}"
            f" ({len(filtered_long)} filtered by word_count >= {MAX_WORDS})"
        )

        if not to_export:
            # Nothing short enough to export. Still prune the long ones so
            # they don't keep reappearing.
            if filtered_long:
                mark_pruned(conn, [it["id"] for it in filtered_long])
                print(f"[anki-export] pruned {len(filtered_long)} long items")
            print("[anki-export] 0 exported, 0 failed")
            return 0

        cfg = load_anki_config(conn)
        if cfg is None or not cfg.get("is_active"):
            print("ERROR: Anki is not connected (anki_config.is_active != 1). "
                  "Run /inch-connect-anki first.", file=sys.stderr)
            return 1

        base_url = f"http://{cfg['host']}:{cfg['port']}"
        client = AnkiConnectClient(base_url, cfg.get("api_key"))

        # Connection probe.
        try:
            version = client.call("version")
        except Exception as exc:
            print(f"ERROR: AnkiConnect not reachable at {base_url}: {exc}",
                  file=sys.stderr)
            return 1
        if not isinstance(version, int) or version < 6:
            print(f"ERROR: unexpected AnkiConnect version: {version!r}",
                  file=sys.stderr)
            return 1

        deck_name = f"Inch 3 - {lang_code}"
        ensure_deck(client, deck_name)
        ensure_model(client)

        SENTENCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        TMP_DIR.mkdir(parents=True, exist_ok=True)

        success = 0
        failure = 0
        for item in to_export:
            try:
                _export_one_item(conn, client, item, deck_name)
                success += 1
            except Exception as exc:
                failure += 1
                print(f"[anki-export] item id={item['id']} failed: {exc}",
                      file=sys.stderr)
                continue

        # Auto-prune the long items only if at least one real export
        # succeeded. This prevents losing them to pruning when the export
        # run was a total dud (e.g. AnkiConnect flaked mid-run).
        if success > 0 and filtered_long:
            mark_pruned(conn, [it["id"] for it in filtered_long])
            print(f"[anki-export] pruned {len(filtered_long)} long items")

        print(f"[anki-export] {success} exported, {failure} failed")
        # Exit 1 only if nothing at all succeeded.
        return 1 if success == 0 and failure > 0 else 0
    finally:
        conn.close()


def _export_one_item(
    conn: sqlite3.Connection,
    client: "AnkiConnectClient",
    item: dict,
    deck_name: str,
) -> None:
    lang_code = item["lang_code"]
    sentence_id = item["sentence_id"]
    item_id = item["id"]

    sentence_path = SENTENCE_CACHE_DIR / sentence_filename(lang_code, sentence_id)
    expr_path = TMP_DIR / expression_filename(lang_code, item_id)
    combo_path = TMP_DIR / combo_filename(lang_code, item_id)

    if not sentence_path.exists():
        tts_generate(item["sentence_l2"], sentence_path)
    tts_generate(item["expression"], expr_path)
    merge_audio(sentence_path, expr_path, combo_path, pause_seconds=2)

    store_media_file(client, sentence_path)
    store_media_file(client, expr_path)
    store_media_file(client, combo_path)

    note_id = add_vocab_note(client, item, deck_name=deck_name)
    mark_exported(conn, item_id=item_id, anki_note_id=note_id)

    # Clean up tmp files (sentence stays in cache).
    expr_path.unlink(missing_ok=True)
    combo_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
