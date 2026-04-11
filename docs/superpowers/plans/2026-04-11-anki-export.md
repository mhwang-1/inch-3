# Anki Export Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add end-to-end Anki export integration to Inch 3 — capture vocab items during `/inch-continue`, auto-export at session end, push to Anki decks via AnkiConnect with two-card notes including merged audio, and provide a conservative pruning skill for well-learned cards.

**Architecture:** Two new SQLite tables (`anki_config`, `anki_vocab_items`), three new Claude Code slash-command skills (`/inch-connect-anki`, `/inch-export-anki-cards`, `/inch-prune-anki`), one new Python script (`scripts/anki-export.py` as the single source of truth for export work), and modifications to `/inch-continue` for inline capture plus session-end auto-export. Audio merging via ffmpeg `apad`+`concat`; AnkiConnect via HTTP `requests`.

**Tech Stack:** Python 3 with `uv run` and PEP 723 inline deps (`requests`), SQLite (WAL mode), ffmpeg, bash, graphviz (for skill `digraph` files), AnkiConnect HTTP API.

**Spec:** `docs/superpowers/specs/2026-04-11-anki-export-design.md` — this plan implements that spec.

---

## File Structure

**New files:**
- `scripts/migrations/0001_anki_tables.sql` — one-shot schema migration.
- `scripts/anki-export.py` — main export script (invoked by both manual skill and auto-export gate).
- `scripts/test_anki_export.py` — pytest unit tests for the pure-logic helpers in `anki-export.py`.
- `.claude/commands/inch-connect-anki.md` — connection setup skill (graphviz dot).
- `.claude/commands/inch-export-anki-cards.md` — export orchestration skill (graphviz dot).
- `.claude/commands/inch-prune-anki.md` — prune skill (graphviz dot).

**Modified files:**
- `.claude/commands/inch-continue.md` — add capture cluster, auto-export cluster, stop/pause response class.
- `TABLES.md` — document new tables and new `study_sessions.status` value.
- `CLAUDE.md` — add new skill commands and script path.

**Untouched:**
- `data/inch-3.db` is the authoritative DB. The migration is applied once as part of Task 1.
- `scripts/backup-db.sh` — no changes.
- `scripts/tts-generate.sh` — no changes (export script uses its own TTS path because it needs mp3, not opus).
- All other existing skills.

---

## Task 1: Schema migration

**Files:**
- Create: `scripts/migrations/0001_anki_tables.sql`

- [ ] **Step 1.1: Create migrations directory**

Run:
```bash
mkdir -p scripts/migrations
```
Expected: directory exists (no output on success).

- [ ] **Step 1.2: Write the migration SQL file**

Create `scripts/migrations/0001_anki_tables.sql` with exactly this content:

```sql
-- Migration 0001: Anki export integration
-- Creates anki_config (singleton) and anki_vocab_items tables.
-- Safe to re-run: all statements use IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS anki_config (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    host TEXT NOT NULL DEFAULT '127.0.0.1',
    port INTEGER NOT NULL DEFAULT 8765,
    api_key TEXT,
    is_active BOOLEAN DEFAULT 0,
    configured_at DATETIME,
    last_verified_at DATETIME
);

CREATE TABLE IF NOT EXISTS anki_vocab_items (
    id INTEGER PRIMARY KEY,
    lang_profile_id INTEGER NOT NULL REFERENCES language_profiles(id),
    sentence_id INTEGER NOT NULL REFERENCES sentences(id),
    expression TEXT NOT NULL,
    expression_l1 TEXT NOT NULL,
    source_block_id INTEGER REFERENCES sentence_blocks(id),
    trigger TEXT NOT NULL CHECK(trigger IN ('translate', 'explain')),
    captured_at DATETIME NOT NULL,
    exported_at DATETIME,
    anki_note_id INTEGER,
    pruned_at DATETIME,
    UNIQUE(lang_profile_id, sentence_id, expression)
);

CREATE INDEX IF NOT EXISTS idx_anki_vocab_unexported
    ON anki_vocab_items(lang_profile_id, exported_at)
    WHERE exported_at IS NULL AND pruned_at IS NULL;

INSERT OR IGNORE INTO anki_config (id) VALUES (1);

COMMIT;
```

- [ ] **Step 1.3: Apply the migration to the live DB**

First back up, then apply:
```bash
bash scripts/backup-db.sh
sqlite3 data/inch-3.db < scripts/migrations/0001_anki_tables.sql
```
Expected: no output on success. Backup script prints its own summary.

- [ ] **Step 1.4: Verify the schema**

Run:
```bash
sqlite3 data/inch-3.db ".schema anki_config" ".schema anki_vocab_items" "SELECT * FROM anki_config;"
```

Expected output:
- `CREATE TABLE anki_config (...)` matching the SQL above.
- `CREATE TABLE anki_vocab_items (...)` with all 12 columns.
- `CREATE INDEX idx_anki_vocab_unexported ...`.
- One row in `anki_config`: `1|127.0.0.1|8765|||0||`.

- [ ] **Step 1.5: Verify idempotence**

Re-apply the migration:
```bash
sqlite3 data/inch-3.db < scripts/migrations/0001_anki_tables.sql
```
Expected: no output, no error. The `IF NOT EXISTS` and `INSERT OR IGNORE` clauses make this safe.

- [ ] **Step 1.6: Commit**

```bash
git add scripts/migrations/0001_anki_tables.sql
git commit -m "Add migration 0001: anki_config and anki_vocab_items tables"
```

---

## Task 2: Python script skeleton and argument parsing

**Files:**
- Create: `scripts/anki-export.py`

- [ ] **Step 2.1: Create the script file with the PEP 723 header and CLI parser**

Create `scripts/anki-export.py` with exactly this content:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""
anki-export.py — push queued vocab items to Anki via AnkiConnect.

Called by:
  - /inch-export-anki-cards (manual)
  - /inch-continue auto-export gate (at session end)

Single source of truth for the Anki export operation. Reads un-exported
anki_vocab_items rows for the given language profile, generates TTS audio
for sentences and expressions, merges them with a 2-second pause via
ffmpeg, pushes to Anki, and marks rows as exported.

Environment variables (inherited from caller):
  INCH_TTS_ENDPOINT, INCH_TTS_MODEL, INCH_TTS_VOICE, INCH_TTS_API_KEY,
  INCH_TTS_SPEED_NORMAL

Usage:
  uv run scripts/anki-export.py --lang-profile-id <int> [--dry-run]
  uv run scripts/anki-export.py --lang-profile-id <int> --db-path <path>
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB_PATH = Path("data/inch-3.db")
MEDIA_ROOT = Path("data/anki-media")
SENTENCE_CACHE_DIR = MEDIA_ROOT / "sentences"
TMP_DIR = MEDIA_ROOT / "tmp"
NOTE_TYPE_NAME = "Inch 3 Vocab"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export Inch 3 vocab items to Anki.")
    p.add_argument("--lang-profile-id", type=int, required=True,
                   help="Language profile ID (from language_profiles.id).")
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH,
                   help="Path to the SQLite database (default: data/inch-3.db).")
    p.add_argument("--dry-run", action="store_true",
                   help="List queued items and exit without calling AnkiConnect.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db_path.exists():
        print(f"ERROR: database not found at {args.db_path}", file=sys.stderr)
        return 1
    # Further logic added in later tasks.
    print(f"[anki-export] stub: lang_profile_id={args.lang_profile_id} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2.2: Make the script executable**

Run:
```bash
chmod +x scripts/anki-export.py
```

- [ ] **Step 2.3: Smoke test the stub**

Run:
```bash
uv run scripts/anki-export.py --lang-profile-id 1 --dry-run
```
Expected output: `[anki-export] stub: lang_profile_id=1 dry_run=True` and exit code 0.

- [ ] **Step 2.4: Smoke test the error path**

Run:
```bash
uv run scripts/anki-export.py --lang-profile-id 1 --db-path /tmp/nonexistent.db
```
Expected: stderr contains `ERROR: database not found at /tmp/nonexistent.db` and exit code 1.

- [ ] **Step 2.5: Commit**

```bash
git add scripts/anki-export.py
git commit -m "Add anki-export.py skeleton with CLI parser"
```

---

## Task 3: Unit test harness

**Files:**
- Create: `scripts/test_anki_export.py`

- [ ] **Step 3.1: Write the test file with a first trivial test**

Create `scripts/test_anki_export.py` with exactly this content:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=8", "requests>=2.31"]
# ///
"""
Unit tests for anki-export.py.

Run with:
  uv run scripts/test_anki_export.py
or:
  uv run --with pytest pytest scripts/test_anki_export.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load anki-export.py as a module (hyphen in filename prevents normal import).
_SPEC = importlib.util.spec_from_file_location(
    "anki_export", Path(__file__).parent / "anki-export.py"
)
assert _SPEC is not None and _SPEC.loader is not None
anki_export = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(anki_export)


def test_parse_args_minimal():
    ns = anki_export.parse_args(["--lang-profile-id", "1"])
    assert ns.lang_profile_id == 1
    assert ns.dry_run is False
    assert ns.db_path == anki_export.DEFAULT_DB_PATH


def test_parse_args_dry_run():
    ns = anki_export.parse_args(["--lang-profile-id", "2", "--dry-run"])
    assert ns.dry_run is True


def test_parse_args_custom_db_path():
    ns = anki_export.parse_args(["--lang-profile-id", "1", "--db-path", "/tmp/x.db"])
    assert str(ns.db_path) == "/tmp/x.db"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
```

- [ ] **Step 3.2: Run the tests**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 3 passed.

- [ ] **Step 3.3: Commit**

```bash
git add scripts/test_anki_export.py
git commit -m "Add unit test harness for anki-export.py"
```

---

## Task 4: Filename helpers

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 4.1: Write failing tests for filename helpers**

Append to `scripts/test_anki_export.py` (before the `if __name__` block):

```python
def test_sentence_filename():
    assert anki_export.sentence_filename("spa", 4521) == "inch3_spa_s4521_sentence.mp3"
    assert anki_export.sentence_filename("jpn", 17) == "inch3_jpn_s17_sentence.mp3"


def test_expression_filename():
    assert anki_export.expression_filename("spa", 128) == "inch3_spa_v128_expr.mp3"


def test_combo_filename():
    assert anki_export.combo_filename("spa", 128) == "inch3_spa_v128_combo.mp3"


def test_sound_tag():
    assert anki_export.sound_tag("inch3_spa_v128_expr.mp3") == "[sound:inch3_spa_v128_expr.mp3]"
```

- [ ] **Step 4.2: Run the tests to verify they fail**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 4 new tests FAIL with `AttributeError: module 'anki_export' has no attribute 'sentence_filename'` (and similar).

- [ ] **Step 4.3: Implement the helpers**

In `scripts/anki-export.py`, add these functions immediately after the constants block (before `parse_args`):

```python
def sentence_filename(lang_code: str, sentence_id: int) -> str:
    return f"inch3_{lang_code}_s{sentence_id}_sentence.mp3"


def expression_filename(lang_code: str, item_id: int) -> str:
    return f"inch3_{lang_code}_v{item_id}_expr.mp3"


def combo_filename(lang_code: str, item_id: int) -> str:
    return f"inch3_{lang_code}_v{item_id}_combo.mp3"


def sound_tag(filename: str) -> str:
    return f"[sound:{filename}]"
```

- [ ] **Step 4.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 7 passed.

- [ ] **Step 4.5: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Add filename helpers to anki-export.py"
```

---

## Task 5: AnkiConnect HTTP wrapper

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 5.1: Write failing tests for the AnkiConnect wrapper**

Append to `scripts/test_anki_export.py` (before the `if __name__` block):

```python
class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise anki_export.requests.HTTPError(f"HTTP {self.status_code}")


def test_anki_call_success(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse({"result": 6, "error": None})

    monkeypatch.setattr(anki_export.requests, "post", fake_post)

    client = anki_export.AnkiConnectClient("http://127.0.0.1:8765", api_key=None)
    result = client.call("version")

    assert result == 6
    assert captured["url"] == "http://127.0.0.1:8765"
    assert captured["json"]["action"] == "version"
    assert captured["json"]["version"] == 6
    assert "key" not in captured["json"] or captured["json"]["key"] is None


def test_anki_call_with_api_key(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse({"result": ["Default"], "error": None})

    monkeypatch.setattr(anki_export.requests, "post", fake_post)

    client = anki_export.AnkiConnectClient("http://127.0.0.1:8765", api_key="secret")
    client.call("deckNames")
    assert captured["json"]["key"] == "secret"


def test_anki_call_error_raises(monkeypatch):
    def fake_post(url, json, timeout):
        return _FakeResponse({"result": None, "error": "deck not found"})

    monkeypatch.setattr(anki_export.requests, "post", fake_post)

    client = anki_export.AnkiConnectClient("http://127.0.0.1:8765", api_key=None)
    with pytest.raises(anki_export.AnkiConnectError, match="deck not found"):
        client.call("deckNames")


def test_anki_call_passes_params(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse({"result": None, "error": None})

    monkeypatch.setattr(anki_export.requests, "post", fake_post)

    client = anki_export.AnkiConnectClient("http://127.0.0.1:8765", api_key=None)
    client.call("createDeck", deck="Inch 3 - spa")
    assert captured["json"]["params"] == {"deck": "Inch 3 - spa"}
```

- [ ] **Step 5.2: Run the tests to verify they fail**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 4 new tests FAIL with `AttributeError: module 'anki_export' has no attribute 'AnkiConnectClient'`.

- [ ] **Step 5.3: Implement AnkiConnectClient**

In `scripts/anki-export.py`, add `import requests` to the imports at the top. Then add these classes/functions after the filename helpers:

```python
import requests  # add near the other imports at the top of the file

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
```

(Remember to place `import requests` with the other imports near the top, not inline.)

- [ ] **Step 5.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 11 passed.

- [ ] **Step 5.5: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Add AnkiConnectClient to anki-export.py"
```

---

## Task 6: TTS helper (direct HTTP call, mp3 format)

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 6.1: Write failing tests for the TTS helper**

Append to `scripts/test_anki_export.py` (before the `if __name__` block):

```python
def test_tts_generate_writes_file(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        resp = _FakeResponse({}, 200)
        resp.content = b"FAKE_MP3_BYTES"
        return resp

    monkeypatch.setattr(anki_export.requests, "post", fake_post)
    monkeypatch.setenv("INCH_TTS_ENDPOINT", "https://example/v1/audio/speech")
    monkeypatch.setenv("INCH_TTS_MODEL", "tts-1")
    monkeypatch.setenv("INCH_TTS_VOICE", "alloy")
    monkeypatch.setenv("INCH_TTS_API_KEY", "sk-test")
    monkeypatch.setenv("INCH_TTS_SPEED_NORMAL", "0.85")

    out = tmp_path / "sentence.mp3"
    anki_export.tts_generate("Hola mundo", out)

    assert out.read_bytes() == b"FAKE_MP3_BYTES"
    assert captured["url"] == "https://example/v1/audio/speech"
    assert captured["json"] == {
        "model": "tts-1",
        "input": "Hola mundo",
        "voice": "alloy",
        "speed": 0.85,
        "response_format": "mp3",
    }
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_tts_generate_missing_env(monkeypatch, tmp_path):
    monkeypatch.delenv("INCH_TTS_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="INCH_TTS_ENDPOINT"):
        anki_export.tts_generate("hola", tmp_path / "x.mp3")
```

- [ ] **Step 6.2: Run the tests to verify they fail**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 2 new tests FAIL with `AttributeError: module 'anki_export' has no attribute 'tts_generate'`.

- [ ] **Step 6.3: Implement tts_generate**

Add this function in `scripts/anki-export.py` after `AnkiConnectClient`:

```python
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
```

- [ ] **Step 6.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 13 passed.

- [ ] **Step 6.5: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Add tts_generate helper to anki-export.py"
```

---

## Task 7: ffmpeg merge helper

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 7.1: Write failing tests for the ffmpeg helper**

Append to `scripts/test_anki_export.py`:

```python
def test_ffmpeg_merge_command_shape(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, check, capture_output):
        captured["cmd"] = cmd
        # Create a fake output file so the caller's stat() succeeds.
        Path(cmd[cmd.index("-filter_complex") + 2]).write_bytes(b"FAKE")
        class _CP:
            returncode = 0
            stdout = b""
            stderr = b""
        return _CP()

    monkeypatch.setattr(anki_export.subprocess, "run", fake_run)

    sentence = tmp_path / "s.mp3"; sentence.write_bytes(b"A")
    expr = tmp_path / "e.mp3"; expr.write_bytes(b"B")
    combo = tmp_path / "c.mp3"

    anki_export.merge_audio(sentence, expr, combo, pause_seconds=2)

    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "-i" in cmd
    assert str(sentence) in cmd
    assert str(expr) in cmd
    assert str(combo) in cmd
    filter_idx = cmd.index("-filter_complex")
    assert "apad=pad_dur=2" in cmd[filter_idx + 1]
    assert "concat=n=2" in cmd[filter_idx + 1]


def test_ffmpeg_merge_raises_on_failure(monkeypatch, tmp_path):
    def fake_run(cmd, check, capture_output):
        class _CP:
            returncode = 1
            stdout = b""
            stderr = b"ffmpeg: bad input"
        return _CP()

    monkeypatch.setattr(anki_export.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        anki_export.merge_audio(
            tmp_path / "s.mp3", tmp_path / "e.mp3", tmp_path / "c.mp3", pause_seconds=2
        )
```

- [ ] **Step 7.2: Run the tests to verify they fail**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 2 new tests FAIL with `AttributeError: module 'anki_export' has no attribute 'merge_audio'`.

- [ ] **Step 7.3: Implement merge_audio**

Add `import subprocess` to the imports at the top of `scripts/anki-export.py`. Then add this function after `tts_generate`:

```python
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
```

- [ ] **Step 7.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 15 passed.

- [ ] **Step 7.5: Real ffmpeg smoke test**

Run (requires ffmpeg installed):
```bash
ffmpeg -version >/dev/null 2>&1 && echo "ffmpeg OK" || echo "MISSING — apt install ffmpeg"
# Generate two tiny silent mp3s to prove the merge pipeline works
ffmpeg -y -f lavfi -i anullsrc=r=24000:cl=mono -t 1 -acodec libmp3lame /tmp/inch-s.mp3 2>/dev/null
ffmpeg -y -f lavfi -i anullsrc=r=24000:cl=mono -t 0.5 -acodec libmp3lame /tmp/inch-e.mp3 2>/dev/null
uv run python -c "
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location('ae', 'scripts/anki-export.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.merge_audio(pathlib.Path('/tmp/inch-s.mp3'), pathlib.Path('/tmp/inch-e.mp3'), pathlib.Path('/tmp/inch-c.mp3'))
print('combo size:', pathlib.Path('/tmp/inch-c.mp3').stat().st_size)
"
rm -f /tmp/inch-s.mp3 /tmp/inch-e.mp3 /tmp/inch-c.mp3
```
Expected: `combo size: <non-zero>`. If the ffmpeg check reports MISSING, stop and install ffmpeg before proceeding.

- [ ] **Step 7.6: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Add ffmpeg merge_audio helper to anki-export.py"
```

---

## Task 8: DB query helpers

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 8.1: Write failing tests using an in-memory SQLite fixture**

Append to `scripts/test_anki_export.py`:

```python
@pytest.fixture
def memdb():
    """An in-memory SQLite DB with enough schema for export tests."""
    import sqlite3 as sqlite
    conn = sqlite.connect(":memory:")
    conn.executescript("""
        CREATE TABLE language_profiles (
            id INTEGER PRIMARY KEY, lang_code TEXT NOT NULL, lang_name TEXT,
            l1_code TEXT, l1_name TEXT
        );
        CREATE TABLE sentences (
            id INTEGER PRIMARY KEY, l2_text TEXT NOT NULL, lang_profile_id INTEGER
        );
        CREATE TABLE sentence_blocks (
            id INTEGER PRIMARY KEY, sentence_id INTEGER, tts_text TEXT, l1_text TEXT
        );
        CREATE TABLE anki_config (
            id INTEGER PRIMARY KEY CHECK(id=1),
            host TEXT NOT NULL DEFAULT '127.0.0.1',
            port INTEGER NOT NULL DEFAULT 8765,
            api_key TEXT,
            is_active BOOLEAN DEFAULT 0,
            configured_at DATETIME, last_verified_at DATETIME
        );
        CREATE TABLE anki_vocab_items (
            id INTEGER PRIMARY KEY,
            lang_profile_id INTEGER NOT NULL,
            sentence_id INTEGER NOT NULL,
            expression TEXT NOT NULL,
            expression_l1 TEXT NOT NULL,
            source_block_id INTEGER,
            trigger TEXT NOT NULL,
            captured_at DATETIME NOT NULL,
            exported_at DATETIME,
            anki_note_id INTEGER,
            pruned_at DATETIME,
            UNIQUE(lang_profile_id, sentence_id, expression)
        );
        INSERT INTO language_profiles (id, lang_code, lang_name) VALUES (1, 'spa', 'Spanish');
        INSERT INTO sentences (id, l2_text, lang_profile_id)
            VALUES (10, 'Me da igual, vamos cuando quieras.', 1),
                   (11, 'No tengo ni idea.', 1);
        INSERT INTO anki_config (id, host, port, is_active) VALUES (1, '127.0.0.1', 8765, 1);
        INSERT INTO anki_vocab_items
            (id, lang_profile_id, sentence_id, expression, expression_l1,
             source_block_id, trigger, captured_at)
        VALUES
            (1, 1, 10, 'me da igual', '無所謂', NULL, 'translate', '2026-04-10 10:00:00'),
            (2, 1, 11, 'ni idea', '一無所知', NULL, 'explain', '2026-04-10 10:05:00'),
            (3, 1, 10, 'already pushed', 'already', NULL, 'translate', '2026-04-10 09:00:00');
        UPDATE anki_vocab_items SET exported_at = '2026-04-10 09:01:00', anki_note_id = 9999
            WHERE id = 3;
    """)
    conn.commit()
    yield conn
    conn.close()


def test_load_anki_config(memdb):
    cfg = anki_export.load_anki_config(memdb)
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == 8765
    assert cfg["api_key"] is None
    assert cfg["is_active"] == 1


def test_load_unexported_items(memdb):
    items = anki_export.load_unexported_items(memdb, lang_profile_id=1)
    assert len(items) == 2
    assert items[0]["id"] == 1
    assert items[0]["expression"] == "me da igual"
    assert items[0]["expression_l1"] == "無所謂"
    assert items[0]["sentence_l2"] == "Me da igual, vamos cuando quieras."
    assert items[0]["lang_code"] == "spa"
    assert items[1]["id"] == 2
    # Item 3 is already exported and must NOT appear.
    assert all(it["id"] != 3 for it in items)


def test_load_unexported_items_empty(memdb):
    # Mark everything exported.
    memdb.execute("UPDATE anki_vocab_items SET exported_at = '2026-04-11 00:00:00'")
    memdb.commit()
    items = anki_export.load_unexported_items(memdb, lang_profile_id=1)
    assert items == []


def test_mark_exported(memdb):
    anki_export.mark_exported(memdb, item_id=1, anki_note_id=12345)
    row = memdb.execute(
        "SELECT exported_at, anki_note_id FROM anki_vocab_items WHERE id = 1"
    ).fetchone()
    assert row[0] is not None
    assert row[1] == 12345
```

- [ ] **Step 8.2: Run the tests to verify they fail**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 4 new tests FAIL with `AttributeError: module 'anki_export' has no attribute 'load_anki_config'`.

- [ ] **Step 8.3: Implement the DB helpers**

Add these functions in `scripts/anki-export.py` after `merge_audio`:

```python
def load_anki_config(conn: sqlite3.Connection) -> dict:
    """Return the singleton anki_config row as a dict, or None if missing."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT host, port, api_key, is_active FROM anki_config WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def load_unexported_items(conn: sqlite3.Connection, lang_profile_id: int) -> list[dict]:
    """Return queued vocab items for one language profile, oldest first."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT av.id, av.sentence_id, av.expression, av.expression_l1,
               s.l2_text AS sentence_l2, lp.lang_code
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
```

- [ ] **Step 8.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 19 passed.

- [ ] **Step 8.5: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Add DB query helpers to anki-export.py"
```

---

## Task 9: Anki model and deck setup helpers

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 9.1: Write failing tests**

Append to `scripts/test_anki_export.py`:

```python
def test_ensure_deck_calls_create_deck(monkeypatch):
    calls = []

    class FakeClient:
        def call(self, action, **params):
            calls.append((action, params))
            if action == "createDeck":
                return 12345
            return None

    anki_export.ensure_deck(FakeClient(), "Inch 3 - spa")
    assert calls == [("createDeck", {"deck": "Inch 3 - spa"})]


def test_ensure_model_creates_if_missing(monkeypatch):
    calls = []

    class FakeClient:
        def call(self, action, **params):
            calls.append((action, params))
            if action == "modelNames":
                return ["Basic", "Cloze"]  # Our model is missing
            return None

    anki_export.ensure_model(FakeClient())
    # Should have called modelNames then createModel
    assert calls[0][0] == "modelNames"
    assert calls[1][0] == "createModel"
    payload = calls[1][1]
    assert payload["modelName"] == anki_export.NOTE_TYPE_NAME
    assert payload["inOrderFields"] == [
        "SentenceL2", "SentenceAudio", "ComboAudio",
        "Expression", "ExpressionAudio", "ExpressionL1",
    ]
    assert len(payload["cardTemplates"]) == 2
    assert "{{ComboAudio}}" in payload["cardTemplates"][0]["Front"]
    assert "{{SentenceAudio}}" in payload["cardTemplates"][1]["Front"]


def test_ensure_model_skips_if_present(monkeypatch):
    calls = []

    class FakeClient:
        def call(self, action, **params):
            calls.append((action, params))
            if action == "modelNames":
                return ["Basic", anki_export.NOTE_TYPE_NAME]
            return None

    anki_export.ensure_model(FakeClient())
    assert [c[0] for c in calls] == ["modelNames"]  # createModel NOT called
```

- [ ] **Step 9.2: Run the tests to verify they fail**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 3 new tests FAIL with `AttributeError`.

- [ ] **Step 9.3: Implement ensure_deck and ensure_model**

Add to `scripts/anki-export.py` after the DB helpers:

```python
CARD_A_FRONT = "{{ComboAudio}}"

CARD_A_BACK = """{{FrontSide}}
<hr id=answer>
<div class="expr-l1">{{ExpressionL1}}</div>
<div class="expr-l2">{{Expression}}</div>
<div class="sentence-l2">{{SentenceL2}}</div>"""

CARD_B_FRONT = """{{SentenceAudio}}
<br>
<div class="expr-l1">{{ExpressionL1}}</div>"""

CARD_B_BACK = """{{FrontSide}}
<hr id=answer>
{{ExpressionAudio}}
<div class="expr-l2">{{Expression}}</div>"""

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
            "SentenceL2", "SentenceAudio", "ComboAudio",
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
```

- [ ] **Step 9.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 22 passed.

- [ ] **Step 9.5: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Add ensure_deck and ensure_model helpers"
```

---

## Task 10: Store media and add note helpers

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 10.1: Write failing tests**

Append to `scripts/test_anki_export.py`:

```python
def test_store_media_file_sends_base64(monkeypatch, tmp_path):
    import base64
    calls = []

    class FakeClient:
        def call(self, action, **params):
            calls.append((action, params))
            return "inch3_spa_s10_sentence.mp3"

    path = tmp_path / "inch3_spa_s10_sentence.mp3"
    path.write_bytes(b"BINARY_DATA_HERE")

    anki_export.store_media_file(FakeClient(), path)

    assert calls[0][0] == "storeMediaFile"
    params = calls[0][1]
    assert params["filename"] == "inch3_spa_s10_sentence.mp3"
    assert base64.b64decode(params["data"]) == b"BINARY_DATA_HERE"


def test_add_vocab_note_builds_fields():
    captured = {}

    class FakeClient:
        def call(self, action, **params):
            captured[action] = params
            return 1724567890123  # fake note id

    item = {
        "id": 128, "sentence_id": 4521,
        "expression": "me da igual",
        "expression_l1": "無所謂",
        "sentence_l2": "Me da igual, vamos cuando quieras.",
        "lang_code": "spa",
    }

    note_id = anki_export.add_vocab_note(FakeClient(), item, deck_name="Inch 3 - spa")

    assert note_id == 1724567890123
    note = captured["addNote"]["note"]
    assert note["deckName"] == "Inch 3 - spa"
    assert note["modelName"] == anki_export.NOTE_TYPE_NAME
    assert note["fields"]["SentenceL2"] == "Me da igual, vamos cuando quieras."
    assert note["fields"]["SentenceAudio"] == "[sound:inch3_spa_s4521_sentence.mp3]"
    assert note["fields"]["ComboAudio"] == "[sound:inch3_spa_v128_combo.mp3]"
    assert note["fields"]["Expression"] == "me da igual"
    assert note["fields"]["ExpressionAudio"] == "[sound:inch3_spa_v128_expr.mp3]"
    assert note["fields"]["ExpressionL1"] == "無所謂"
    assert note["tags"] == ["inch3", "lang:spa"]
    assert note["options"]["allowDuplicate"] is True
```

- [ ] **Step 10.2: Run the tests to verify they fail**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 2 new tests FAIL with `AttributeError`.

- [ ] **Step 10.3: Implement store_media_file and add_vocab_note**

Add to `scripts/anki-export.py` after `ensure_model`:

```python
import base64  # add to imports at top of file


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
```

- [ ] **Step 10.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 24 passed.

- [ ] **Step 10.5: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Add store_media_file and add_vocab_note helpers"
```

---

## Task 11: Main export loop (dry-run path first)

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 11.1: Write failing tests for the dry-run path**

Append to `scripts/test_anki_export.py`:

```python
def test_run_export_dry_run(memdb, capsys, tmp_path):
    # Write DB to a temp file so the script can open it via Path.
    import sqlite3 as sqlite
    db_file = tmp_path / "test.db"
    disk = sqlite.connect(db_file)
    for line in memdb.iterdump():
        disk.execute(line)
    disk.commit()
    disk.close()

    exit_code = anki_export.main([
        "--lang-profile-id", "1",
        "--db-path", str(db_file),
        "--dry-run",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[anki-export] 2 items to export" in captured.out
    assert "me da igual" in captured.out
    assert "ni idea" in captured.out


def test_run_export_empty_queue(memdb, capsys, tmp_path):
    import sqlite3 as sqlite
    memdb.execute("UPDATE anki_vocab_items SET exported_at = '2026-04-11 00:00:00'")
    memdb.commit()
    db_file = tmp_path / "test.db"
    disk = sqlite.connect(db_file)
    for line in memdb.iterdump():
        disk.execute(line)
    disk.commit()
    disk.close()

    exit_code = anki_export.main([
        "--lang-profile-id", "1",
        "--db-path", str(db_file),
        "--dry-run",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "0 items" in captured.out or "No new vocab items" in captured.out
```

- [ ] **Step 11.2: Run tests to verify they fail**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 2 new tests FAIL (because `main` still prints the stub message).

- [ ] **Step 11.3: Replace the stub main with the real dry-run logic**

In `scripts/anki-export.py`, replace the `main` function with:

```python
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db_path.exists():
        print(f"ERROR: database not found at {args.db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(args.db_path))
    try:
        items = load_unexported_items(conn, args.lang_profile_id)
        if not items:
            print("[anki-export] 0 items to export — queue empty")
            return 0

        lang_code = items[0]["lang_code"]
        print(f"[anki-export] {len(items)} items to export for lang={lang_code}")

        if args.dry_run:
            for it in items:
                print(
                    f"  id={it['id']} sentence_id={it['sentence_id']} "
                    f"expr={it['expression']!r}"
                )
            return 0

        # Non-dry-run path implemented in Task 12.
        print("[anki-export] non-dry-run path not yet implemented (Task 12)")
        return 0
    finally:
        conn.close()
```

- [ ] **Step 11.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 26 passed.

- [ ] **Step 11.5: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Implement dry-run path in anki-export main"
```

---

## Task 12: Main export loop (full export path)

**Files:**
- Modify: `scripts/anki-export.py`
- Modify: `scripts/test_anki_export.py`

- [ ] **Step 12.1: Write failing test for the full export path with mocked TTS/ffmpeg/Anki**

Append to `scripts/test_anki_export.py`:

```python
def test_run_export_full_path(memdb, monkeypatch, tmp_path, capsys):
    import sqlite3 as sqlite
    db_file = tmp_path / "test.db"
    disk = sqlite.connect(db_file)
    for line in memdb.iterdump():
        disk.execute(line)
    disk.commit()
    disk.close()

    # Route media dirs under tmp_path so we don't pollute the repo.
    monkeypatch.setattr(anki_export, "MEDIA_ROOT", tmp_path / "anki-media")
    monkeypatch.setattr(anki_export, "SENTENCE_CACHE_DIR", tmp_path / "anki-media/sentences")
    monkeypatch.setattr(anki_export, "TMP_DIR", tmp_path / "anki-media/tmp")

    # Mock tts_generate to just write a fake byte blob.
    def fake_tts(text, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"FAKE_MP3_" + text.encode("utf-8"))
    monkeypatch.setattr(anki_export, "tts_generate", fake_tts)

    # Mock merge_audio to produce a fake combo file.
    def fake_merge(sentence_path, expression_path, combo_path, pause_seconds=2):
        combo_path.parent.mkdir(parents=True, exist_ok=True)
        combo_path.write_bytes(b"FAKE_COMBO")
    monkeypatch.setattr(anki_export, "merge_audio", fake_merge)

    # Mock AnkiConnectClient so we don't need a running Anki.
    calls = []
    class FakeClient:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
        def call(self, action, **params):
            calls.append((action, params))
            if action == "version":
                return 6
            if action == "modelNames":
                return [anki_export.NOTE_TYPE_NAME]
            if action == "addNote":
                return 9000 + len(calls)
            return None
    monkeypatch.setattr(anki_export, "AnkiConnectClient", FakeClient)

    exit_code = anki_export.main([
        "--lang-profile-id", "1",
        "--db-path", str(db_file),
    ])

    assert exit_code == 0
    # Expect both items exported.
    actions = [c[0] for c in calls]
    assert actions.count("addNote") == 2
    assert "createDeck" in actions
    assert "storeMediaFile" in actions

    # Verify DB updated.
    check = sqlite.connect(db_file)
    rows = check.execute(
        "SELECT id, exported_at, anki_note_id FROM anki_vocab_items "
        "WHERE pruned_at IS NULL ORDER BY id"
    ).fetchall()
    check.close()
    # id 1 and 2 should now be exported (3 already was).
    assert rows[0][1] is not None and rows[0][2] is not None
    assert rows[1][1] is not None and rows[1][2] is not None
```

- [ ] **Step 12.2: Run the test to verify it fails**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 1 new test FAILS because `main` still short-circuits with "not yet implemented".

- [ ] **Step 12.3: Implement the full export path**

Replace `main` in `scripts/anki-export.py` with:

```python
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db_path.exists():
        print(f"ERROR: database not found at {args.db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(args.db_path))
    try:
        items = load_unexported_items(conn, args.lang_profile_id)
        if not items:
            print("[anki-export] 0 items to export — queue empty")
            return 0

        lang_code = items[0]["lang_code"]
        print(f"[anki-export] {len(items)} items to export for lang={lang_code}")

        if args.dry_run:
            for it in items:
                print(
                    f"  id={it['id']} sentence_id={it['sentence_id']} "
                    f"expr={it['expression']!r}"
                )
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
        for item in items:
            try:
                _export_one_item(conn, client, item, deck_name)
                success += 1
            except Exception as exc:
                failure += 1
                print(f"[anki-export] item id={item['id']} failed: {exc}",
                      file=sys.stderr)
                continue

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
```

- [ ] **Step 12.4: Run the tests to verify they pass**

Run:
```bash
uv run scripts/test_anki_export.py
```
Expected: 27 passed.

- [ ] **Step 12.5: Commit**

```bash
git add scripts/anki-export.py scripts/test_anki_export.py
git commit -m "Implement full export path in anki-export main"
```

---

## Task 13: /inch-connect-anki skill file

**Files:**
- Create: `.claude/commands/inch-connect-anki.md`

- [ ] **Step 13.1: Write the skill file as a graphviz digraph**

Create `.claude/commands/inch-connect-anki.md` with exactly this content:

```
`` `dot
digraph inch_connect_anki {
    // Connect Anki
    // Sets up the AnkiConnect connection for Inch 3.
    // Reads/writes: anki_config (singleton).
    //
    // ARCHITECTURE: This skill runs as a Claude Code task. It probes the
    // AnkiConnect HTTP endpoint, stores host/port/api_key in anki_config,
    // and marks is_active=1 on success.
    // Python: inline `uv run --with requests python -c "..."` for the HTTP probe.
    // SQLite: direct `sqlite3 data/inch-3.db` commands.
    //
    // NEVER log or print api_key values after entry.

    "START" [shape=ellipse];
    "Check ffmpeg installed:\ncommand -v ffmpeg" [shape=diamond];
    "Abort: ffmpeg missing.\nPrint: 'ffmpeg is required for Anki export.\nInstall: apt install ffmpeg (Debian/Ubuntu)\nor brew install ffmpeg (macOS).'" [shape=box];
    "Read current anki_config row:\nsqlite3 data/inch-3.db\n\"SELECT host,port,api_key,is_active FROM anki_config WHERE id=1;\"" [shape=box];
    "Ask user: Where does Anki run?\n(a) same machine (127.0.0.1:8765)\n(b) different host (prompt for host + port)\n(c) re-verify existing config" [shape=diamond];
    "Prompt user for host and port;\nstore in local shell vars" [shape=box];
    "Probe AnkiConnect:\nuv run --with requests python -c \"\nimport requests, json, sys\nr = requests.post('http://HOST:PORT',\n  json={'action':'version','version':6},\n  timeout=10)\nprint(r.status_code, r.text)\n\"" [shape=box];
    "Probe result?" [shape=diamond];
    "Success: result>=6, error is null.\nAlso call deckNames to confirm full RPC path." [shape=box];
    "Update DB:\nsqlite3 data/inch-3.db \"\nUPDATE anki_config\nSET host=?, port=?, api_key=?, is_active=1,\n    configured_at = COALESCE(configured_at, CURRENT_TIMESTAMP),\n    last_verified_at = CURRENT_TIMESTAMP\nWHERE id=1;\"" [shape=box];
    "bash scripts/tg-send-text.sh\n'Anki is connected. Ready to export vocab cards.'" [shape=plaintext];
    "SUCCESS" [shape=doublecircle];

    "Connection refused / timeout:\nprint setup instructions, abort" [shape=box];
    "Print to Claude Code console:\n'AnkiConnect is not reachable at http://HOST:PORT.\n\nTo set up AnkiConnect:\n  1. Install Anki desktop: https://apps.ankiweb.net\n  2. In Anki: Tools > Add-ons > Get Add-ons...\n  3. Enter code: 2055492159  (AnkiConnect)\n  4. Restart Anki.\n  5. Keep Anki running, then re-run /inch-connect-anki.\n\nIf Anki runs on a different machine than Claude Code,\nedit the AnkiConnect config to allow remote origins.\nSee: https://foosoft.net/projects/anki-connect/'" [shape=plaintext];
    "ABORT (not connected)" [shape=doublecircle];

    "HTTP 403 / auth error:\nAnkiConnect has an apiKey configured.\nPrompt user for key." [shape=box];
    "Update anki_config.api_key;\nretry probe once." [shape=box];
    "Retry probe result?" [shape=diamond];

    "Unexpected response:\nsomething is listening but it isn't AnkiConnect.\nPrint error and abort." [shape=box];

    "START" -> "Check ffmpeg installed:\ncommand -v ffmpeg";
    "Check ffmpeg installed:\ncommand -v ffmpeg" -> "Abort: ffmpeg missing.\nPrint: 'ffmpeg is required for Anki export.\nInstall: apt install ffmpeg (Debian/Ubuntu)\nor brew install ffmpeg (macOS).'" [label="no"];
    "Abort: ffmpeg missing.\nPrint: 'ffmpeg is required for Anki export.\nInstall: apt install ffmpeg (Debian/Ubuntu)\nor brew install ffmpeg (macOS).'" -> "ABORT (not connected)";
    "Check ffmpeg installed:\ncommand -v ffmpeg" -> "Read current anki_config row:\nsqlite3 data/inch-3.db\n\"SELECT host,port,api_key,is_active FROM anki_config WHERE id=1;\"" [label="yes"];
    "Read current anki_config row:\nsqlite3 data/inch-3.db\n\"SELECT host,port,api_key,is_active FROM anki_config WHERE id=1;\"" -> "Ask user: Where does Anki run?\n(a) same machine (127.0.0.1:8765)\n(b) different host (prompt for host + port)\n(c) re-verify existing config";
    "Ask user: Where does Anki run?\n(a) same machine (127.0.0.1:8765)\n(b) different host (prompt for host + port)\n(c) re-verify existing config" -> "Prompt user for host and port;\nstore in local shell vars" [label="(b)"];
    "Ask user: Where does Anki run?\n(a) same machine (127.0.0.1:8765)\n(b) different host (prompt for host + port)\n(c) re-verify existing config" -> "Probe AnkiConnect:\nuv run --with requests python -c \"\nimport requests, json, sys\nr = requests.post('http://HOST:PORT',\n  json={'action':'version','version':6},\n  timeout=10)\nprint(r.status_code, r.text)\n\"" [label="(a) or (c)"];
    "Prompt user for host and port;\nstore in local shell vars" -> "Probe AnkiConnect:\nuv run --with requests python -c \"\nimport requests, json, sys\nr = requests.post('http://HOST:PORT',\n  json={'action':'version','version':6},\n  timeout=10)\nprint(r.status_code, r.text)\n\"";
    "Probe AnkiConnect:\nuv run --with requests python -c \"\nimport requests, json, sys\nr = requests.post('http://HOST:PORT',\n  json={'action':'version','version':6},\n  timeout=10)\nprint(r.status_code, r.text)\n\"" -> "Probe result?";
    "Probe result?" -> "Success: result>=6, error is null.\nAlso call deckNames to confirm full RPC path." [label="200 OK + valid version"];
    "Probe result?" -> "Connection refused / timeout:\nprint setup instructions, abort" [label="connection refused / timeout"];
    "Probe result?" -> "HTTP 403 / auth error:\nAnkiConnect has an apiKey configured.\nPrompt user for key." [label="HTTP 403 / auth error"];
    "Probe result?" -> "Unexpected response:\nsomething is listening but it isn't AnkiConnect.\nPrint error and abort." [label="HTML / unexpected"];
    "Success: result>=6, error is null.\nAlso call deckNames to confirm full RPC path." -> "Update DB:\nsqlite3 data/inch-3.db \"\nUPDATE anki_config\nSET host=?, port=?, api_key=?, is_active=1,\n    configured_at = COALESCE(configured_at, CURRENT_TIMESTAMP),\n    last_verified_at = CURRENT_TIMESTAMP\nWHERE id=1;\"";
    "Update DB:\nsqlite3 data/inch-3.db \"\nUPDATE anki_config\nSET host=?, port=?, api_key=?, is_active=1,\n    configured_at = COALESCE(configured_at, CURRENT_TIMESTAMP),\n    last_verified_at = CURRENT_TIMESTAMP\nWHERE id=1;\"" -> "bash scripts/tg-send-text.sh\n'Anki is connected. Ready to export vocab cards.'";
    "bash scripts/tg-send-text.sh\n'Anki is connected. Ready to export vocab cards.'" -> "SUCCESS";
    "Connection refused / timeout:\nprint setup instructions, abort" -> "Print to Claude Code console:\n'AnkiConnect is not reachable at http://HOST:PORT.\n\nTo set up AnkiConnect:\n  1. Install Anki desktop: https://apps.ankiweb.net\n  2. In Anki: Tools > Add-ons > Get Add-ons...\n  3. Enter code: 2055492159  (AnkiConnect)\n  4. Restart Anki.\n  5. Keep Anki running, then re-run /inch-connect-anki.\n\nIf Anki runs on a different machine than Claude Code,\nedit the AnkiConnect config to allow remote origins.\nSee: https://foosoft.net/projects/anki-connect/'";
    "Print to Claude Code console:\n'AnkiConnect is not reachable at http://HOST:PORT.\n\nTo set up AnkiConnect:\n  1. Install Anki desktop: https://apps.ankiweb.net\n  2. In Anki: Tools > Add-ons > Get Add-ons...\n  3. Enter code: 2055492159  (AnkiConnect)\n  4. Restart Anki.\n  5. Keep Anki running, then re-run /inch-connect-anki.\n\nIf Anki runs on a different machine than Claude Code,\nedit the AnkiConnect config to allow remote origins.\nSee: https://foosoft.net/projects/anki-connect/'" -> "ABORT (not connected)";
    "HTTP 403 / auth error:\nAnkiConnect has an apiKey configured.\nPrompt user for key." -> "Update anki_config.api_key;\nretry probe once.";
    "Update anki_config.api_key;\nretry probe once." -> "Retry probe result?";
    "Retry probe result?" -> "Success: result>=6, error is null.\nAlso call deckNames to confirm full RPC path." [label="success"];
    "Retry probe result?" -> "ABORT (not connected)" [label="still failing"];
    "Unexpected response:\nsomething is listening but it isn't AnkiConnect.\nPrint error and abort." -> "ABORT (not connected)";

    subgraph cluster_rules {
        label="ABSOLUTE RULES";
        "NEVER log or print api_key values after entry." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
        "Only set is_active=1 after a successful probe." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
        "If invoked from /inch-export-anki-cards,\nreturn control to that skill on success." [shape=octagon, style=filled, fillcolor=orange];
    }
}
`` `
```

NOTE: replace the `` ` ` characters (with no spaces) with actual triple-backticks when saving — the plan uses spaced backticks only to prevent this code block from terminating early.

- [ ] **Step 13.2: Verify the skill file parses as valid markdown with a dot block**

Run:
```bash
head -5 .claude/commands/inch-connect-anki.md && wc -l .claude/commands/inch-connect-anki.md
```
Expected: first line starts with ``` ```dot ``` and total line count is ~60+.

- [ ] **Step 13.3: Commit**

```bash
git add .claude/commands/inch-connect-anki.md
git commit -m "Add /inch-connect-anki skill"
```

---

## Task 14: /inch-export-anki-cards skill file

**Files:**
- Create: `.claude/commands/inch-export-anki-cards.md`

- [ ] **Step 14.1: Write the skill file**

Create `.claude/commands/inch-export-anki-cards.md` with this content (replacing the spaced backticks with real triple-backticks):

```
`` `dot
digraph inch_export_anki_cards {
    // Export Anki Cards
    // Pushes queued vocab items to Anki via AnkiConnect.
    // Reads: anki_config, language_profiles, anki_vocab_items, sentences.
    // Writes: anki_vocab_items.exported_at, anki_vocab_items.anki_note_id.
    //
    // ARCHITECTURE: Thin orchestration wrapper. All real work lives in
    // scripts/anki-export.py which is also invoked by /inch-continue's
    // auto-export gate at session end.

    "START" [shape=ellipse];
    "Run: bash scripts/backup-db.sh" [shape=plaintext];
    "Pre-cache TTS credentials as env vars\n(same pattern as /inch-continue):\nsource /tmp/inch3-env.sh if present,\notherwise read from language_profiles\nWHERE is_active=1." [shape=box];
    "Active language profile exists?" [shape=diamond];
    "Abort: run /inch-switch-language-profile first" [shape=box];
    "anki_config.is_active = 1?" [shape=diamond];
    "Hand off to /inch-connect-anki.\nOn success, resume here.\nOn abort, propagate abort." [shape=box];
    "Probe AnkiConnect version (quick check):\nuv run --with requests python -c \"\nimport requests\ntry: r=requests.post('http://HOST:PORT',\n  json={'action':'version','version':6},timeout=5)\nexcept: exit(2)\nexit(0 if r.ok else 1)\n\"" [shape=box];
    "Probe OK?" [shape=diamond];
    "Abort: AnkiConnect not reachable.\nRun /inch-connect-anki to re-verify." [shape=box];
    "SELECT COUNT(*) FROM anki_vocab_items\nWHERE lang_profile_id=? AND exported_at IS NULL\nAND pruned_at IS NULL" [shape=box];
    "Count > 0?" [shape=diamond];
    "bash scripts/tg-send-text.sh\n'No new vocab items to export.'" [shape=plaintext];
    "Run: uv run scripts/anki-export.py\n--lang-profile-id <active_id>\n(credentials inherited via env vars)" [shape=box];
    "Script exit code 0?" [shape=diamond];
    "Read summary line from script stdout:\n'[anki-export] N exported, M failed'" [shape=box];
    "bash scripts/tg-send-text.sh\n'Exported N cards to Inch 3 - {lang}. M failed (see console).'" [shape=plaintext];
    "SUCCESS" [shape=doublecircle];
    "bash scripts/tg-send-text.sh\n'Anki export failed — see Claude Code console.'" [shape=plaintext];
    "ABORT" [shape=doublecircle];

    "START" -> "Run: bash scripts/backup-db.sh";
    "Run: bash scripts/backup-db.sh" -> "Pre-cache TTS credentials as env vars\n(same pattern as /inch-continue):\nsource /tmp/inch3-env.sh if present,\notherwise read from language_profiles\nWHERE is_active=1.";
    "Pre-cache TTS credentials as env vars\n(same pattern as /inch-continue):\nsource /tmp/inch3-env.sh if present,\notherwise read from language_profiles\nWHERE is_active=1." -> "Active language profile exists?";
    "Active language profile exists?" -> "Abort: run /inch-switch-language-profile first" [label="no"];
    "Abort: run /inch-switch-language-profile first" -> "ABORT";
    "Active language profile exists?" -> "anki_config.is_active = 1?" [label="yes"];
    "anki_config.is_active = 1?" -> "Hand off to /inch-connect-anki.\nOn success, resume here.\nOn abort, propagate abort." [label="no"];
    "Hand off to /inch-connect-anki.\nOn success, resume here.\nOn abort, propagate abort." -> "Probe AnkiConnect version (quick check):\nuv run --with requests python -c \"\nimport requests\ntry: r=requests.post('http://HOST:PORT',\n  json={'action':'version','version':6},timeout=5)\nexcept: exit(2)\nexit(0 if r.ok else 1)\n\"";
    "anki_config.is_active = 1?" -> "Probe AnkiConnect version (quick check):\nuv run --with requests python -c \"\nimport requests\ntry: r=requests.post('http://HOST:PORT',\n  json={'action':'version','version':6},timeout=5)\nexcept: exit(2)\nexit(0 if r.ok else 1)\n\"" [label="yes"];
    "Probe AnkiConnect version (quick check):\nuv run --with requests python -c \"\nimport requests\ntry: r=requests.post('http://HOST:PORT',\n  json={'action':'version','version':6},timeout=5)\nexcept: exit(2)\nexit(0 if r.ok else 1)\n\"" -> "Probe OK?";
    "Probe OK?" -> "Abort: AnkiConnect not reachable.\nRun /inch-connect-anki to re-verify." [label="no"];
    "Abort: AnkiConnect not reachable.\nRun /inch-connect-anki to re-verify." -> "ABORT";
    "Probe OK?" -> "SELECT COUNT(*) FROM anki_vocab_items\nWHERE lang_profile_id=? AND exported_at IS NULL\nAND pruned_at IS NULL" [label="yes"];
    "SELECT COUNT(*) FROM anki_vocab_items\nWHERE lang_profile_id=? AND exported_at IS NULL\nAND pruned_at IS NULL" -> "Count > 0?";
    "Count > 0?" -> "bash scripts/tg-send-text.sh\n'No new vocab items to export.'" [label="no"];
    "bash scripts/tg-send-text.sh\n'No new vocab items to export.'" -> "SUCCESS";
    "Count > 0?" -> "Run: uv run scripts/anki-export.py\n--lang-profile-id <active_id>\n(credentials inherited via env vars)" [label="yes"];
    "Run: uv run scripts/anki-export.py\n--lang-profile-id <active_id>\n(credentials inherited via env vars)" -> "Script exit code 0?";
    "Script exit code 0?" -> "Read summary line from script stdout:\n'[anki-export] N exported, M failed'" [label="yes"];
    "Read summary line from script stdout:\n'[anki-export] N exported, M failed'" -> "bash scripts/tg-send-text.sh\n'Exported N cards to Inch 3 - {lang}. M failed (see console).'";
    "bash scripts/tg-send-text.sh\n'Exported N cards to Inch 3 - {lang}. M failed (see console).'" -> "SUCCESS";
    "Script exit code 0?" -> "bash scripts/tg-send-text.sh\n'Anki export failed — see Claude Code console.'" [label="no"];
    "bash scripts/tg-send-text.sh\n'Anki export failed — see Claude Code console.'" -> "ABORT";

    subgraph cluster_rules {
        label="ABSOLUTE RULES";
        "NEVER skip the backup step." [shape=octagon, style=filled, fillcolor=orange];
        "NEVER re-export rows where exported_at IS NOT NULL\nor pruned_at IS NOT NULL.\n(Python script enforces this via its SELECT.)" [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
        "Credentials: read once into env vars,\nnever log or print values." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
    }
}
`` `
```

- [ ] **Step 14.2: Commit**

```bash
git add .claude/commands/inch-export-anki-cards.md
git commit -m "Add /inch-export-anki-cards skill"
```

---

### Task 15: `/inch-prune-anki` Skill File

**Files:**
- Create: `.claude/commands/inch-prune-anki.md`

- [ ] **Step 15.1: Write the skill file**

Create `.claude/commands/inch-prune-anki.md`. Use real triple-backticks in place of `` ` ` ` `` below:

`` ` ` ` ``dot
digraph inch_prune_anki {
    rankdir=TB;
    node [shape=box, style=rounded];

    START [shape=oval];
    SUCCESS [shape=oval, style=filled, fillcolor=lightgreen];
    ABORT [shape=oval, style=filled, fillcolor=lightcoral];

    START -> "Read TABLES.md\n(reference — do not edit)";
    "Read TABLES.md\n(reference — do not edit)" -> "bash scripts/backup-db.sh";
    "bash scripts/backup-db.sh" -> "Backup OK?";
    "Backup OK?" -> ABORT [label="no"];
    "Backup OK?" -> "SELECT id, is_active, lang_code FROM language_profiles WHERE is_active=1" [label="yes"];

    "SELECT id, is_active, lang_code FROM language_profiles WHERE is_active=1" -> "Active profile?";
    "Active profile?" -> "bash scripts/tg-send-text.sh\n'No active language profile.'" [label="no"];
    "bash scripts/tg-send-text.sh\n'No active language profile.'" -> ABORT;

    "Active profile?" -> "SELECT is_active FROM anki_config WHERE id=1" [label="yes"];
    "SELECT is_active FROM anki_config WHERE id=1" -> "Anki connected?";
    "Anki connected?" -> "bash scripts/tg-send-text.sh\n'Anki not configured. Run /inch-connect-anki first.'" [label="no"];
    "bash scripts/tg-send-text.sh\n'Anki not configured. Run /inch-connect-anki first.'" -> ABORT;

    "Anki connected?" -> "AnkiConnect: findNotes\n{query: 'deck:\"Inch 3 - {lang_code}\"'}" [label="yes"];
    "AnkiConnect: findNotes\n{query: 'deck:\"Inch 3 - {lang_code}\"'}" -> "Probe OK?";
    "Probe OK?" -> "bash scripts/tg-send-text.sh\n'Cannot reach AnkiConnect. Is Anki open?'" [label="no"];
    "bash scripts/tg-send-text.sh\n'Cannot reach AnkiConnect. Is Anki open?'" -> ABORT;

    "Probe OK?" -> "For each note_id batch (100):\nAnkiConnect: notesInfo → cards[]\nthen cardsInfo for each card" [label="yes"];
    "For each note_id batch (100):\nAnkiConnect: notesInfo → cards[]\nthen cardsInfo for each card" -> "Filter candidates:\nALL of the note's cards must have\nqueue==2 AND interval>=548\nAND lapses/max(reps,1) < 0.3";
    "Filter candidates:\nALL of the note's cards must have\nqueue==2 AND interval>=548\nAND lapses/max(reps,1) < 0.3" -> "Any candidates?";
    "Any candidates?" -> "bash scripts/tg-send-text.sh\n'No cards meet the pruning threshold (interval ≥ 548 days, low lapse rate).'" [label="no"];
    "bash scripts/tg-send-text.sh\n'No cards meet the pruning threshold (interval ≥ 548 days, low lapse rate).'" -> SUCCESS;

    "Any candidates?" -> "Print candidate list to console:\nexpression, l1, interval, lapses/reps\n(sorted by interval DESC)" [label="yes"];
    "Print candidate list to console:\nexpression, l1, interval, lapses/reps\n(sorted by interval DESC)" -> "Ask user via console prompt:\n'Prune N candidates? [y/N]'";
    "Ask user via console prompt:\n'Prune N candidates? [y/N]'" -> "User confirmed?";
    "User confirmed?" -> "bash scripts/tg-send-text.sh\n'Pruning cancelled.'" [label="no"];
    "bash scripts/tg-send-text.sh\n'Pruning cancelled.'" -> SUCCESS;

    "User confirmed?" -> "AnkiConnect: deleteNotes {notes: [note_ids]}" [label="yes"];
    "AnkiConnect: deleteNotes {notes: [note_ids]}" -> "Delete OK?";
    "Delete OK?" -> "bash scripts/tg-send-text.sh\n'AnkiConnect deleteNotes failed — see console.'" [label="no"];
    "bash scripts/tg-send-text.sh\n'AnkiConnect deleteNotes failed — see console.'" -> ABORT;

    "Delete OK?" -> "UPDATE anki_vocab_items\nSET pruned_at=datetime('now')\nWHERE anki_note_id IN (...)" [label="yes"];
    "UPDATE anki_vocab_items\nSET pruned_at=datetime('now')\nWHERE anki_note_id IN (...)" -> "bash scripts/tg-send-text.sh\n'Pruned N cards from Inch 3 - {lang_code}.'";
    "bash scripts/tg-send-text.sh\n'Pruned N cards from Inch 3 - {lang_code}.'" -> SUCCESS;

    subgraph cluster_rules {
        label="ABSOLUTE RULES";
        "NEVER skip the backup step." [shape=octagon, style=filled, fillcolor=orange];
        "NEVER prune a card with interval < 548 days\n(1.5 years). This is non-negotiable." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
        "NEVER prune without user confirmation." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
        "ALWAYS require ALL of a note's cards to meet the threshold.\nIf any card is still new/learning, keep the whole note." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
    }
}
`` ` ` ` ``

- [ ] **Step 15.2: Commit**

```bash
git add .claude/commands/inch-prune-anki.md
git commit -m "Add /inch-prune-anki skill"
```

---

### Task 16: Update `/inch-continue` — Capture Triggers

**Files:**
- Modify: `.claude/commands/inch-continue.md`

Locate the existing escalation ladder in the digraph. Add INSERT OR IGNORE capture calls at 5 points where the user asks for meaning/explanation. The capture logic is identical everywhere — always insert using the **current block's `tts_text` as `expression` and `l1_text` as `expression_l1`**. No parsing. No span detection. If a block has no `l1_text` at the moment of capture, SKIP capture silently (do not insert NULL into expression_l1).

- [ ] **Step 16.1: Add a shared capture helper node**

Near the top of the digraph (before the main session loop), add this helper node so it can be referenced from multiple points:

```
"CAPTURE VOCAB:\n(conditional — only if block has l1_text)\nINSERT OR IGNORE INTO anki_vocab_items\n(lang_profile_id, sentence_id, expression, expression_l1,\n source_block_id, trigger, captured_at)\nVALUES (?, ?, block.tts_text, block.l1_text,\n        block.id, <trigger>, datetime('now'))" [shape=box, style=filled, fillcolor=lightyellow];
```

- [ ] **Step 16.2: Wire capture to the 5 trigger points**

The 5 points where capture fires, each tagged with the `<trigger>` value to record:

| # | Ladder step | User response class | Trigger value |
|---|---|---|---|
| 1 | L0 → L1 (single block, translate branch) | `translate` | `translate` |
| 2 | L0 → L1 compound (`?` means translate current block) | `translate` (compound) | `translate` |
| 3 | L1 → L2 single block | `explain` | `explain` |
| 4 | L0 → L2 compound (`??` → skip L1, go to L2) | `explain` (compound) | `explain` |
| 5 | L1 → L2 compound (user asks explain after translation) | `explain` (compound) | `explain` |

After each of those 5 classification outcomes, insert an arrow to the CAPTURE VOCAB node BEFORE the arrow that delivers L1/explanation to Telegram. The CAPTURE VOCAB node's outgoing edge should flow into whatever node was previously next (the L1 delivery or L2 delivery).

Example rewire for trigger point 1 (before):
```
"Classify response" -> "bash scripts/tg-send-text.sh block.l1_text" [label="translate"];
```

After:
```
"Classify response" -> "CAPTURE VOCAB:\n(conditional — only if block has l1_text)\nINSERT OR IGNORE INTO anki_vocab_items\n..." [label="translate"];
"CAPTURE VOCAB:\n..." -> "bash scripts/tg-send-text.sh block.l1_text";
```

Apply analogous rewrites for trigger points 2–5. The **trigger column value** varies by site — encode it by using 5 distinct CAPTURE VOCAB nodes (or, if you prefer one node, add the trigger label onto the incoming edge and pass it through — but the plan explicitly allows duplicating the node for clarity).

- [ ] **Step 16.3: Add capture rules to cluster_rules**

Inside the existing `subgraph cluster_rules` block in `inch-continue.md`, append these three rules:

```
"ALWAYS capture vocab on translate and explain responses\n(INSERT OR IGNORE deduplicates automatically)." [shape=octagon, style=filled, fillcolor=lightblue];
"NEVER parse the user's message to detect a specific span.\nAlways use the current block's tts_text verbatim." [shape=octagon, style=filled, fillcolor=red, fontcolor=white];
"Skip capture silently if block.l1_text IS NULL.\nDo not insert NULL into expression_l1." [shape=octagon, style=filled, fillcolor=orange];
```

- [ ] **Step 16.4: Commit**

```bash
git add .claude/commands/inch-continue.md
git commit -m "Add vocab capture to /inch-continue escalation ladder"
```

---

### Task 17: Update `/inch-continue` — Stop/Pause Response Class

**Files:**
- Modify: `.claude/commands/inch-continue.md`

- [ ] **Step 17.1: Add stop/pause to the response classification node**

Find the response classification node (the one listing response classes: `ok`, `slower`, `translate`, `explain`, `confused`, etc.). Add a new class `stop_pause`.

Update the classifier node's label to include:

```
stop_pause: stop, pause, break, quit, bye, done, 停, 暫停, 結束, 到這
```

- [ ] **Step 17.2: Wire stop_pause to session termination**

Add an outgoing edge from the classification node labeled `stop_pause` that flows to a new node:

```
"Set session status = 'paused'\nUPDATE study_sessions\nSET status='paused', ended_at=datetime('now')\nWHERE id = session_id" [shape=box, style=filled, fillcolor=khaki];
```

That node's outgoing edge goes to the **same "Print session notes to console" node** used by the normal completion path. From there, the existing flow continues into the auto-export gate (added in Task 18) and then `SESSION COMPLETE`.

- [ ] **Step 17.3: Add stop/pause rule to cluster_rules**

Inside `subgraph cluster_rules`, append:

```
"stop_pause ends the session gracefully.\nAlways write status='paused' and ended_at before exiting." [shape=octagon, style=filled, fillcolor=lightblue];
```

- [ ] **Step 17.4: Commit**

```bash
git add .claude/commands/inch-continue.md
git commit -m "Add stop/pause response class to /inch-continue"
```

---

### Task 18: Update `/inch-continue` — Auto-Export Gate

**Files:**
- Modify: `.claude/commands/inch-continue.md`

- [ ] **Step 18.1: Add the auto-export gate node**

Find the "Print session notes to console" node that leads to `SESSION COMPLETE`. Between them, insert:

```
"Auto-export gate:\nSELECT is_active FROM anki_config WHERE id=1" [shape=box];
"Anki connected?" [shape=diamond];
"SELECT COUNT(*) FROM anki_vocab_items\nWHERE lang_profile_id=? AND exported_at IS NULL\nAND pruned_at IS NULL" [shape=box];
"Pending vocab?" [shape=diamond];
"Invoke /inch-export-anki-cards\n(as sub-skill; inherits active lang profile)" [shape=box, style=filled, fillcolor=lightyellow];
```

- [ ] **Step 18.2: Wire the gate edges**

Replace the existing edge from "Print session notes to console" -> "SESSION COMPLETE" with this chain:

```
"Print session notes to console" -> "Auto-export gate:\nSELECT is_active FROM anki_config WHERE id=1";
"Auto-export gate:\nSELECT is_active FROM anki_config WHERE id=1" -> "Anki connected?";
"Anki connected?" -> "SESSION COMPLETE" [label="no"];
"Anki connected?" -> "SELECT COUNT(*) FROM anki_vocab_items\nWHERE lang_profile_id=? AND exported_at IS NULL\nAND pruned_at IS NULL" [label="yes"];
"SELECT COUNT(*) FROM anki_vocab_items\nWHERE lang_profile_id=? AND exported_at IS NULL\nAND pruned_at IS NULL" -> "Pending vocab?";
"Pending vocab?" -> "SESSION COMPLETE" [label="0"];
"Pending vocab?" -> "Invoke /inch-export-anki-cards\n(as sub-skill; inherits active lang profile)" [label="≥1"];
"Invoke /inch-export-anki-cards\n(as sub-skill; inherits active lang profile)" -> "SESSION COMPLETE";
```

This chain runs on ALL three termination paths: `completed`, `abandoned`, and `paused` — because all three flow through "Print session notes to console" before reaching `SESSION COMPLETE`. Verify this is the case in the existing digraph before committing; if any termination path bypasses "Print session notes to console", rewire that path too.

- [ ] **Step 18.3: Add auto-export rule to cluster_rules**

Inside `subgraph cluster_rules`, append:

```
"Auto-export runs on every session end\n(completed, abandoned, paused).\nSkip silently if Anki is not connected or no pending vocab." [shape=octagon, style=filled, fillcolor=lightblue];
"NEVER fail the session if auto-export fails.\nThe session already ended — export errors go to console only." [shape=octagon, style=filled, fillcolor=orange];
```

- [ ] **Step 18.4: Commit**

```bash
git add .claude/commands/inch-continue.md
git commit -m "Add auto-export gate to end of /inch-continue session"
```

---

### Task 19: Update `TABLES.md`

**Files:**
- Modify: `TABLES.md`

- [ ] **Step 19.1: Add `anki_config` section**

In the Table of Contents, add entries 11 and 12:

```markdown
11. [anki_config](#11-anki_config)
12. [anki_vocab_items](#12-anki_vocab_items)
```

At the end of the table sections (after section 10 `sentence_study_records`, before the "Indexes" section), append:

```markdown
## 11. `anki_config`

Singleton table holding the AnkiConnect connection details. The `CHECK(id=1)` constraint enforces that only one row can ever exist.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY, CHECK(id=1) | Always 1. Enforces singleton. |
| `host` | TEXT | NOT NULL, DEFAULT `'127.0.0.1'` | Host where AnkiConnect listens. Loopback by default — Anki must be running on the same machine as Inch 3, or this must be changed to a reachable address. |
| `port` | INTEGER | NOT NULL, DEFAULT `8765` | AnkiConnect HTTP port. Default is `8765` (AnkiConnect's factory default). |
| `api_key` | TEXT | | Optional AnkiConnect API key. If set, sent as the `key` field in every request. Stored directly in the local DB — never committed to git. |
| `is_active` | BOOLEAN | DEFAULT 0 | Set to `1` only after a successful probe (`version` + `deckNames`). Scripts refuse to export if `is_active = 0`. |
| `configured_at` | DATETIME | | Timestamp of initial configuration. |
| `last_verified_at` | DATETIME | | Timestamp of the last successful probe. Updated by `/inch-connect-anki` on reconfiguration. |

**Notes:**
- Created and populated by `/inch-connect-anki`.
- Read by `scripts/anki-export.py` to build the AnkiConnect endpoint URL.

---

## 12. `anki_vocab_items`

One row per captured expression (word or fixed expression) the user asked Claude to translate or explain during a study session. Exported to Anki lazily — see `/inch-export-anki-cards`.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `lang_profile_id` | INTEGER | FK → `language_profiles.id`, NOT NULL | The language profile this vocab belongs to. Determines the target Anki deck (`Inch 3 - {lang_code}`). |
| `sentence_id` | INTEGER | FK → `sentences.id`, NOT NULL | The sentence that contained the expression when it was captured. Used to regenerate the sentence TTS on export. |
| `expression` | TEXT | NOT NULL | The captured expression — always equal to the `tts_text` of the block the user was asking about. No parsing, no span detection. |
| `expression_l1` | TEXT | NOT NULL | Translation of the expression into the user's L1 — always equal to the `l1_text` of the same block. Capture is skipped if `l1_text` IS NULL. |
| `source_block_id` | INTEGER | FK → `sentence_blocks.id` | The block the user was on when capture fired. For traceability. |
| `trigger` | TEXT | NOT NULL, CHECK(trigger IN ('translate', 'explain')) | Which escalation step triggered the capture. |
| `captured_at` | DATETIME | NOT NULL | When the capture fired. |
| `exported_at` | DATETIME | | Set by `scripts/anki-export.py` after a successful `addNote`. `NULL` means the item has not been exported yet. |
| `anki_note_id` | INTEGER | | The Anki note ID returned by AnkiConnect. Set alongside `exported_at`. Used by `/inch-prune-anki` to delete the note if the user later prunes it. |
| `pruned_at` | DATETIME | | Set by `/inch-prune-anki` after a successful delete. Pruned rows are never re-exported. |

**Constraints:**

```
UNIQUE(lang_profile_id, sentence_id, expression)
```

This is the dedup key — the same expression captured twice in the same sentence collapses to one row. The same expression in a different sentence is a separate row (different sentence audio).

**Notes:**
- Rows are created by `/inch-continue` using `INSERT OR IGNORE`.
- Rows are exported by `scripts/anki-export.py`, invoked by `/inch-export-anki-cards` or auto-triggered at session end.
- Rows are pruned (soft-deleted, `pruned_at` set) by `/inch-prune-anki` once the underlying Anki cards have been mastered.

---
```

- [ ] **Step 19.2: Update `sentences.study_status` documentation**

This task does NOT need to modify the `study_status` column — it remains `unstudied`, `in_progress`, `completed`. The new `paused` status is on `study_sessions.status`, not `sentences.study_status`.

Find the `study_sessions.status` row in section 9 (`study_sessions`). Change:

```
| `status` | TEXT | DEFAULT `'active'` | Session state: `active` (in progress), `completed` (10 sentences finished normally), `abandoned` (user quit or timeout). |
```

To:

```
| `status` | TEXT | DEFAULT `'active'` | Session state: `active` (in progress), `completed` (10 sentences finished normally), `abandoned` (user quit or timeout), `paused` (user said stop/pause; `ended_at` is set). |
```

- [ ] **Step 19.3: Update the Entity Relationship Summary**

At the bottom of `TABLES.md`, in the ER summary section, add after the existing `language_profiles` branches:

```
language_profiles
  └─< anki_vocab_items (lang_profile_id)
        └── sentences (sentence_id)
        └── sentence_blocks (source_block_id)

anki_config                           (singleton, no FK)
```

- [ ] **Step 19.4: Add indexes row for `anki_vocab_items`**

In the Indexes table, add:

```
| `idx_anki_vocab_export` | `anki_vocab_items` | `(lang_profile_id, exported_at, pruned_at)` | Covers the "pending export" query used by auto-export gate and `scripts/anki-export.py`. |
```

(The index itself is created in Task 1's migration.)

- [ ] **Step 19.5: Commit**

```bash
git add TABLES.md
git commit -m "Document anki_config and anki_vocab_items tables"
```

---

### Task 20: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 20.1: Add new skill commands to the Skill Commands table**

In the "Skill Commands" table (the one listing `/inch-import-books`, `/inch-continue`, etc.), append three rows:

```markdown
| `/inch-connect-anki` | Guide AnkiConnect setup (install add-on, configure host/port/API key), probe the endpoint, store config. |
| `/inch-export-anki-cards` | Export all unexported vocab items captured in the active language profile to Anki. Generates TTS audio, merges sentence + expression into a combined clip, and creates notes via AnkiConnect. Auto-triggered at session end. |
| `/inch-prune-anki` | Inspect Anki review stats for the active language's deck, list cards meeting the pruning threshold (interval ≥ 548 days, low lapse rate), and soft-delete confirmed candidates from both Anki and the local DB. |
```

- [ ] **Step 20.2: Add `anki_config` and `anki_vocab_items` to the Key Rules section**

In the "Key Rules" section, append:

```markdown
- **Anki credentials are stored in the database.** The AnkiConnect host, port, and optional API key live in `anki_config`. They are never logged or printed.
- **Vocab capture is lazy and automatic.** `/inch-continue` captures vocab rows when the user asks for translation or explanation. Export to Anki is lazy — nothing leaves the DB until `/inch-export-anki-cards` runs (manually or automatically at session end).
- **Pruning requires a 1.5-year interval minimum.** `/inch-prune-anki` only proposes cards where every card of the note has `interval >= 548` days AND a lapse rate below 30%. This threshold is non-negotiable.
```

- [ ] **Step 20.3: Add `scripts/anki-export.py` and `data/anki-media/` to the Directory Structure section**

In the "Directory Structure" tree near the top of `CLAUDE.md`, update the `scripts/` and `data/` subtrees:

Find:
```
├── scripts/                           ← Bash and Python utility scripts.
│   ├── backup-db.sh                   ← Daily DB backup; called at session start.
│   ├── tts-generate.sh                ← Call TTS API; credentials via env vars.
│   ├── tg-send-audio.sh               ← Send a local audio file to Telegram chat.
│   ├── tg-poll-response.sh            ← Poll Telegram getUpdates for next user message.
│   └── tg-send-text.sh                ← Send a text message to Telegram chat.
```

Replace with:
```
├── scripts/                           ← Bash and Python utility scripts.
│   ├── backup-db.sh                   ← Daily DB backup; called at session start.
│   ├── tts-generate.sh                ← Call TTS API; credentials via env vars.
│   ├── tg-send-audio.sh               ← Send a local audio file to Telegram chat.
│   ├── tg-poll-response.sh            ← Poll Telegram getUpdates for next user message.
│   ├── tg-send-text.sh                ← Send a text message to Telegram chat.
│   ├── anki-export.py                 ← Export captured vocab to Anki via AnkiConnect.
│   └── migrations/
│       └── 0001_anki_tables.sql       ← Idempotent migration adding anki_config + anki_vocab_items.
```

Find:
```
└── data/                              ← Runtime data. NEVER committed to git.
    ├── inch-3.db                      ← SQLite database (all study data, API configs).
    ├── inch-3.db-wal                  ← SQLite WAL journal.
    ├── inch-3.db-shm                  ← SQLite shared memory.
    └── inch-3_YYYYMMDD_HHmmss.db     ← Daily backups (rolling 10-day max).
```

Replace with:
```
└── data/                              ← Runtime data. NEVER committed to git.
    ├── inch-3.db                      ← SQLite database (all study data, API configs).
    ├── inch-3.db-wal                  ← SQLite WAL journal.
    ├── inch-3.db-shm                  ← SQLite shared memory.
    ├── inch-3_YYYYMMDD_HHmmss.db      ← Daily backups (rolling 10-day max).
    └── anki-media/                    ← Cached TTS clips for Anki export.
        ├── sentences/                 ← Per-sentence audio (keyed by sentence_id).
        ├── expressions/               ← Per-expression audio (keyed by anki_vocab_items.id).
        └── combos/                    ← Merged sentence+expression clips (Card A front).
```

- [ ] **Step 20.4: Add the new commands to `.claude/commands/` listing**

In the Directory Structure tree, update `.claude/commands/`:

Find:
```
├── .claude/
│   └── commands/                      ← Skill files (slash commands for Claude Code).
│       ├── inch-import-books.md
│       ├── inch-setup-new-language-profile.md
│       ├── inch-connect-telegram.md
│       ├── inch-continue.md
│       └── inch-switch-language-profile.md
```

Replace with:
```
├── .claude/
│   └── commands/                      ← Skill files (slash commands for Claude Code).
│       ├── inch-import-books.md
│       ├── inch-setup-new-language-profile.md
│       ├── inch-connect-telegram.md
│       ├── inch-connect-anki.md
│       ├── inch-continue.md
│       ├── inch-switch-language-profile.md
│       ├── inch-export-anki-cards.md
│       └── inch-prune-anki.md
```

- [ ] **Step 20.5: Commit**

```bash
git add CLAUDE.md
git commit -m "Document Anki export commands and directory layout"
```

---

### Task 21: End-to-End Manual Verification

**Files:**
- None (verification only)

This task is a manual smoke test on a real Anki instance to verify the integration works end-to-end. All previous tasks have unit-tested individual pieces; this one confirms the full pipeline.

- [ ] **Step 21.1: Prerequisite check**

Before running the smoke test, verify:

```bash
# 1. Anki is installed and open with the AnkiConnect add-on (code 2055492159)
# 2. There is an active language profile in the DB
sqlite3 data/inch-3.db "SELECT id, lang_code, is_active FROM language_profiles WHERE is_active=1;"
# Expected: one row

# 3. There is at least one sentence with l1_text on its blocks
sqlite3 data/inch-3.db "SELECT s.id FROM sentences s JOIN sentence_blocks sb ON sb.sentence_id=s.id WHERE sb.l1_text IS NOT NULL AND s.lang_profile_id=(SELECT id FROM language_profiles WHERE is_active=1) LIMIT 1;"
# Expected: one row
```

If any prerequisite fails, fix it before proceeding.

- [ ] **Step 21.2: Run `/inch-connect-anki`**

Invoke the skill in Claude Code:

```
/inch-connect-anki
```

Expected:
- Skill walks through AnkiConnect add-on install (if not already installed).
- Skill probes `version` (returns `6`) and `deckNames`.
- `anki_config` row is written with `is_active=1`, `configured_at`, `last_verified_at`.

Verify:

```bash
sqlite3 data/inch-3.db "SELECT host, port, is_active, configured_at FROM anki_config WHERE id=1;"
# Expected: 127.0.0.1|8765|1|<timestamp>
```

- [ ] **Step 21.3: Manually seed a vocab item**

Skip a full study session for the smoke test — manually insert one vocab row:

```bash
LANG_ID=$(sqlite3 data/inch-3.db "SELECT id FROM language_profiles WHERE is_active=1;")
sqlite3 data/inch-3.db "
INSERT OR IGNORE INTO anki_vocab_items
  (lang_profile_id, sentence_id, expression, expression_l1, source_block_id, trigger, captured_at)
SELECT
  $LANG_ID,
  s.id,
  sb.tts_text,
  sb.l1_text,
  sb.id,
  'translate',
  datetime('now')
FROM sentences s
JOIN sentence_blocks sb ON sb.sentence_id = s.id
WHERE s.lang_profile_id = $LANG_ID
  AND sb.l1_text IS NOT NULL
LIMIT 1;
"
sqlite3 data/inch-3.db "SELECT id, expression, expression_l1 FROM anki_vocab_items WHERE exported_at IS NULL AND pruned_at IS NULL;"
# Expected: one row
```

- [ ] **Step 21.4: Run `/inch-export-anki-cards`**

Invoke in Claude Code:

```
/inch-export-anki-cards
```

Expected Telegram message:
```
Exported 1 cards to Inch 3 - <lang_code>. 0 failed.
```

Verify:

```bash
sqlite3 data/inch-3.db "SELECT id, anki_note_id, exported_at FROM anki_vocab_items WHERE exported_at IS NOT NULL ORDER BY id DESC LIMIT 1;"
# Expected: row with non-NULL anki_note_id and exported_at
ls -la data/anki-media/sentences/ data/anki-media/tmp/
# Expected: sentences/ retains a persistent .mp3 cache; tmp/ is emptied after a
# successful run (expression and combo clips are unlinked after upload).
```

Open Anki and confirm:
- Deck `Inch 3 - <lang_code>` exists.
- Note type `Inch 3 Vocab` exists with fields: SentenceL2, SentenceAudio, ComboAudio, Expression, ExpressionAudio, ExpressionL1.
- One note exists in the deck, with two cards (Card A: Combo Front, Card B: Sentence+L1 Front).
- Card A plays: sentence audio → 2s silence → expression audio.
- Card B front shows sentence text + L1 translation of the expression.

- [ ] **Step 21.5: Run `/inch-export-anki-cards` a second time**

Verify idempotency — re-running should find no pending items:

```
/inch-export-anki-cards
```

Expected Telegram message:
```
No new vocab items to export.
```

- [ ] **Step 21.6: Manually test auto-export gate**

Seed another vocab row (same SQL as Step 21.3 but target a different sentence). Then run `/inch-continue` and immediately say `stop`. Expected:

- Session ends with `status='paused'`.
- Auto-export gate fires.
- Telegram reports the new card was exported.
- `anki_vocab_items` shows `exported_at` set on the new row.

- [ ] **Step 21.7: Test `/inch-prune-anki` with no candidates**

Invoke:

```
/inch-prune-anki
```

Since the freshly exported cards have interval 0, no candidates should match. Expected Telegram message:

```
No cards meet the pruning threshold (interval ≥ 548 days, low lapse rate).
```

- [ ] **Step 21.8: Document any issues found**

If any step produced unexpected behavior, file an issue summary in a scratch note, then fix the implementation and re-run the affected steps. Do NOT commit "fix smoke test" patches blindly — understand the root cause first.

- [ ] **Step 21.9: Commit a smoke-test completion marker (optional)**

```bash
git commit --allow-empty -m "Smoke test: Anki export pipeline verified end-to-end"
```

---

## Plan Self-Review

Before execution, confirm:

**Spec coverage check:**
- [x] Section 1 Capture → Task 16
- [x] Section 2 Data model → Task 1
- [x] Section 3 Connect flow → Tasks 12 + 13
- [x] Section 4 Export flow (/inch-export-anki-cards skill) → Task 14
- [x] Section 5 anki-export.py script → Tasks 2–11
- [x] Section 6 Note model + templates → Task 11 (createModel) + Task 10 (addNote)
- [x] Section 7 Auto-export at session end → Task 18
- [x] Section 8 Prune flow → Task 15
- [x] Section 9 Documentation (TABLES.md, CLAUDE.md) → Tasks 19 + 20
- [x] Section 10 File manifest → all files accounted for across tasks
- [x] Section 11 Absolute rules → embedded in each skill file's cluster_rules
- [x] Section 12 Out-of-scope → not implemented (correct)

**Placeholder scan:**
- All tasks contain concrete code or commands. No "TBD", "TODO", "implement later", or vague hand-waves.
- The skill files in Tasks 13, 14, 15 use `` ` ` ` `` (spaced backticks) with explicit instructions to replace with real triple-backticks on save — this is intentional to avoid breaking the plan's own markdown.

**Type consistency:**
- Function names stable: `tts_generate`, `merge_audio`, `ensure_deck`, `ensure_model`, `export_item`, `load_anki_config`, `load_unexported_items`, `mark_exported`.
- DB column names stable: `anki_vocab_items.expression`, `expression_l1`, `source_block_id`, `trigger`, `captured_at`, `exported_at`, `anki_note_id`, `pruned_at`.
- AnkiConnect field names match: `interval`, `factor`, `queue`, `lapses`, `reps` (not `ivl`/`ease`).
- Note field order consistent everywhere: `SentenceL2`, `SentenceAudio`, `ComboAudio`, `Expression`, `ExpressionAudio`, `ExpressionL1`.
- Media filename helpers consistent: `sentence_filename`, `expression_filename`, `combo_filename`, `sound_tag`.

---
