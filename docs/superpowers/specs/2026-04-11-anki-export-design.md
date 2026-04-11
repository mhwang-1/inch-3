# Anki Export Integration — Design Spec

**Date:** 2026-04-11
**Status:** Draft — awaiting user review

## 1. Overview

Inch 3 captures words and fixed expressions that the user asks Claude about during a study session, stores them in the local database, and pushes them to Anki as vocabulary cards via AnkiConnect. Cards are decomposed per-language into decks named `Inch 3 - {lang_code}` (e.g. `Inch 3 - spa`). Each note produces two card types: a production card (L1 → L2 audio) and a recognition card (L2 audio + L1 → L2 audio).

Capture is implicit: whenever the user triggers a translate or explain action on a block during `/inch-continue`, the block text and its L1 translation are inserted into a vocab queue. Nothing happens to Anki in real time — the queue accumulates silently. At session end (or on explicit `/inch-export-anki-cards`), the queue is flushed to Anki: TTS audio is generated for each item, an ffmpeg concat produces the combined audio with a 2-second pause, and notes are added via AnkiConnect's HTTP API.

A conservative pruning skill (`/inch-prune-anki`) lets the user later reclaim space and review time by deleting cards that Anki itself considers over-learned (interval ≥ 1.5 years, ≥5 reviews, both cards correct).

## 2. Scope

**In scope:**
- Two new database tables: `anki_config` (singleton) and `anki_vocab_items`.
- New column `anki_vocab_items.pruned_at` (added by the same migration).
- New value `paused` for `study_sessions.status`.
- New response class `stop/pause` in `/inch-continue`.
- Inline vocab capture on translate/explain actions in `/inch-continue`.
- Auto-export hook at session end (all three termination paths).
- Three new skill files: `/inch-connect-anki`, `/inch-export-anki-cards`, `/inch-prune-anki`.
- One new Python script: `scripts/anki-export.py` (uv run with PEP 723).
- Updated `TABLES.md` and `CLAUDE.md`.

**Out of scope:**
- UI for editing vocab items in the DB (user edits via sqlite3 directly if needed).
- Resurrecting pruned items (no skill for reversing a prune).
- Card scheduling / SRS tuning inside Inch 3 (Anki owns this entirely).
- Syncing Anki review data back into Inch 3 (one-way push only).
- Importing Anki cards that originated elsewhere.

## 3. Data model

### 3.1 New table: `anki_config`

Singleton, mirrors `telegram_config`. One row exists once the user has ever touched the connect flow.

```sql
CREATE TABLE anki_config (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    host TEXT NOT NULL DEFAULT '127.0.0.1',
    port INTEGER NOT NULL DEFAULT 8765,
    api_key TEXT,
    is_active BOOLEAN DEFAULT 0,
    configured_at DATETIME,
    last_verified_at DATETIME
);
```

| Column | Notes |
|---|---|
| `id` | Always 1. |
| `host` | AnkiConnect host. Default `127.0.0.1`. |
| `port` | AnkiConnect port. Default `8765`. |
| `api_key` | NULL unless the user has configured AnkiConnect with `apiKey`. Stored directly in the DB (same model as `tts_api_key`). Never logged. |
| `is_active` | `1` only after a successful probe. All export/prune skills refuse to run if `0`. |
| `configured_at` | Timestamp of first successful configuration. Preserved across re-verifications. |
| `last_verified_at` | Updated every time a probe succeeds. |

### 3.2 New table: `anki_vocab_items`

```sql
CREATE TABLE anki_vocab_items (
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

CREATE INDEX idx_anki_vocab_unexported
    ON anki_vocab_items(lang_profile_id, exported_at)
    WHERE exported_at IS NULL AND pruned_at IS NULL;
```

| Column | Notes |
|---|---|
| `expression` | L2 text. In v1 this is always the block's `tts_text` (no free-form parsing). |
| `expression_l1` | L1 translation. In v1 this is always the block's `l1_text`. |
| `source_block_id` | Block being studied when the item was captured. FK is nullable — a block deletion does not cascade to the vocab item. |
| `trigger` | `'translate'` or `'explain'` — which user action created the item. CHECK constraint enforces values. |
| `exported_at` | Set on successful `addNote` response. NULL = queued. |
| `anki_note_id` | Stored for future updates or for `deleteNotes` during pruning. |
| `pruned_at` | Set when the item has been deleted from Anki by `/inch-prune-anki`. The row itself is NOT deleted — it remains as a historical record for regeneration if needed. |

**State diagram for one item:**
```
(inserted)
    │
    ├── exported_at IS NULL, pruned_at IS NULL        ← queued
    │
    ▼ (export succeeds)
    │
    ├── exported_at IS NOT NULL, pruned_at IS NULL    ← live in Anki
    │
    ▼ (prune confirmed)
    │
    └── exported_at IS NOT NULL, pruned_at IS NOT NULL ← retired
```

**Partial index** covers the common query "un-exported, un-pruned items for this language", which runs at every session end and every manual export.

### 3.3 Modified table: `study_sessions`

Add `paused` as a valid value for `study_sessions.status`. No schema migration required — the column is plain TEXT with no CHECK constraint. Only documentation (`TABLES.md`) needs updating.

Valid values: `active`, `completed`, `abandoned`, `paused`.

### 3.4 Migration script

A single SQL file runs the schema changes in one transaction. Ordering:

1. `CREATE TABLE anki_config ...`
2. `CREATE TABLE anki_vocab_items ...` (including `pruned_at`).
3. `CREATE INDEX idx_anki_vocab_unexported ...`
4. `INSERT INTO anki_config (id) VALUES (1) ON CONFLICT DO NOTHING;` — ensures the singleton row exists so the connect flow has something to UPDATE.

The migration lives at `scripts/migrations/0001_anki_tables.sql` and is applied by a one-shot invocation: `sqlite3 data/inch-3.db < scripts/migrations/0001_anki_tables.sql`. A simple migration runner is out of scope; the user runs this SQL once when they first install the feature.

## 4. Capture flow (changes to `/inch-continue`)

### 4.1 New response class: `stop/pause`

Added to the response classifier in the skill's `cluster_familiarity` documentation block:

**Keywords** (case-insensitive, Unicode-normalised): `stop`, `pause`, `break`, `quit`, `bye`, `done`, `停`, `暫停`, `結束`, `到這`.

**Precedence:** Matched before any other intent. If the user says `stop`, that wins even if the word is adjacent to other keywords.

**Behavior:** At every poll point (L0, L1, L2, L3, between-sentence prompt), a `stop` classification short-circuits the ladder and jumps directly to `cluster_session_end` with status `paused`. No advance, no familiarity update for the current block, no further audio.

### 4.2 Capture trigger points

Capture happens on five paths, all of which involve the user asking for meaning. Transcript-only paths never capture.

| Path | Trigger value | When to INSERT |
|---|---|---|
| `L0 compound-translate` | `'translate'` | After L2+L1 text is sent via `tg-send-text`. |
| `L1 translate` | `'translate'` | After L1 is sent. |
| `L0 compound-explain` | `'explain'` | After the LLM explanation is sent. |
| `L1 compound-explain` | `'explain'` | After the LLM explanation is sent. |
| `L2 explain` | `'explain'` | After the LLM explanation is sent. |

### 4.3 Capture SQL

Always use the current block's `tts_text` and `l1_text`. No parsing of the user's message.

```sql
INSERT OR IGNORE INTO anki_vocab_items
  (lang_profile_id, sentence_id, expression, expression_l1,
   source_block_id, trigger, captured_at)
VALUES
  (?active_lang_profile_id?,
   ?current_sentence_id?,
   ?block.tts_text?,
   ?block.l1_text?,
   ?block.id?,
   ?'translate' | 'explain'?,
   CURRENT_TIMESTAMP);
```

`INSERT OR IGNORE` combined with the `UNIQUE(lang_profile_id, sentence_id, expression)` constraint silently dedupes same-sentence repeats (e.g. user triggers both translate and explain on the same block).

### 4.4 Logging and failure handling

- On success: print one line to the Claude Code console (NOT Telegram): `[anki-capture] "<expression>" sentence_id=X trigger=translate`.
- On DB error: log the exception to the console and continue. Capture failures NEVER interrupt the study loop.

### 4.5 Auto-export gate at session end

Added as a new sub-cluster `cluster_anki_auto_export` in `inch-continue.md`, wired between "Print session notes to console" and `SESSION COMPLETE`.

Logic (in order):
1. `SELECT is_active FROM anki_config WHERE id = 1`. If no row or `is_active = 0`, skip silently.
2. `SELECT COUNT(*) FROM anki_vocab_items WHERE lang_profile_id = ? AND exported_at IS NULL AND pruned_at IS NULL`. If 0, skip silently.
3. Print to console: `[anki-auto-export] N items queued, running export...`
4. Invoke: `uv run scripts/anki-export.py --lang-profile-id ?`. Inherit the already-cached environment variables (TTS credentials in `/tmp/inch3-env.sh`).
5. On script exit 0: send `tg-send-text` with the summary line.
6. On non-zero exit: log stderr to console and send `tg-send-text "Anki auto-export failed — run /inch-export-anki-cards manually to retry"`. Never abort session wrap-up.

Fires on all three termination paths: `completed`, `abandoned`, `paused`.

### 4.6 Skill file structure

The existing `inch-continue.md` is a single graphviz `digraph`. Changes:
- Add subgraph `cluster_anki_capture` with two nodes (SQL insert, console log) and edges from each of the five trigger points.
- Add subgraph `cluster_anki_auto_export` with the five-step gate.
- Update the response classification block to include `stop/pause` keywords and behavior.

## 5. Export flow

### 5.1 Skill: `/inch-export-anki-cards`

New file `.claude/commands/inch-export-anki-cards.md`. Thin orchestration wrapper:

1. `bash scripts/backup-db.sh`.
2. Verify active language profile exists. If not, abort with message pointing to `/inch-switch-language-profile`.
3. Verify `anki_config.is_active = 1`. If not, hand off to `/inch-connect-anki` inline, then continue.
4. Probe `http://{host}:{port}` with AnkiConnect `version` action. If no response, abort with message pointing to `/inch-connect-anki`.
5. `SELECT COUNT(*) FROM anki_vocab_items WHERE lang_profile_id = ? AND exported_at IS NULL AND pruned_at IS NULL`. If 0, `tg-send-text "No new vocab items to export."` and exit.
6. Invoke `uv run scripts/anki-export.py --lang-profile-id ?`.
7. On success, relay the script's summary to the console.

### 5.2 Python script: `scripts/anki-export.py`

The export script is the single source of truth for the operation. Both the manual skill and the auto-export gate invoke it.

**Dependencies** (PEP 723 inline block):
```python
# /// script
# dependencies = ["requests>=2.31"]
# ///
```

**TTS invocation:** The script makes HTTP POST calls directly to `INCH_TTS_ENDPOINT` using `requests`, rather than subprocess-calling `scripts/tts-generate.sh`. Rationale: the existing `tts-generate.sh` hardcodes `response_format=opus`, but Anki card compatibility is best with `mp3`. The script reuses the same env-var credentials (`INCH_TTS_ENDPOINT`, `INCH_TTS_MODEL`, `INCH_TTS_VOICE`, `INCH_TTS_API_KEY`, `INCH_TTS_SPEED_NORMAL`) and sends an identical payload but with `response_format='mp3'`.

**CLI:**
```
uv run scripts/anki-export.py --lang-profile-id <int> [--dry-run]
```

**Environment variables expected** (inherited from the parent shell):
- `INCH_TTS_ENDPOINT`, `INCH_TTS_MODEL`, `INCH_TTS_VOICE`, `INCH_TTS_API_KEY`, `INCH_TTS_SPEED_NORMAL` — for TTS generation.
- No Telegram vars needed; the script writes to stdout, and the caller relays to Telegram.

**Steps:**

1. Open the database at `data/inch-3.db` (read-write).
2. Read `anki_config` row → build `base_url = f"http://{host}:{port}"`, set `api_key` for the request body if non-null.
3. Query un-exported items:
   ```sql
   SELECT av.id, av.sentence_id, av.expression, av.expression_l1,
          s.l2_text, lp.lang_code
   FROM anki_vocab_items av
   JOIN sentences s ON s.id = av.sentence_id
   JOIN language_profiles lp ON lp.id = av.lang_profile_id
   WHERE av.lang_profile_id = ?
     AND av.exported_at IS NULL
     AND av.pruned_at IS NULL
   ORDER BY av.captured_at ASC;
   ```
4. Print count: `[anki-export] {N} items to export for lang={lang_code}`. If `--dry-run`, print each item and exit.
5. Ensure deck exists: AnkiConnect `createDeck` with `deck = f"Inch 3 - {lang_code}"`. Idempotent.
6. Ensure note type exists: AnkiConnect `modelNames`. If `Inch 3 Vocab` is missing, create it with `createModel` (see Section 7 for field list and templates). First-run only.
7. Per-item loop:
   a. Determine filenames:
      - Sentence: `inch3_{lang_code}_s{sentence_id}_sentence.mp3`
      - Expression: `inch3_{lang_code}_v{item_id}_expr.mp3`
      - Combo: `inch3_{lang_code}_v{item_id}_combo.mp3`
   b. Sentence cache lookup: if `data/anki-media/sentences/{sentence_filename}` exists locally, reuse it. Otherwise generate via the script's internal `tts_generate()` function at `speed = INCH_TTS_SPEED_NORMAL` and write to the cache path.
   c. Generate expression audio via `tts_generate()` to a temp file in `data/anki-media/tmp/`.
   d. Run ffmpeg to produce the combo file:
      ```
      ffmpeg -y -hide_banner -loglevel error \
        -i {sentence_path} \
        -i {expression_path} \
        -filter_complex "[0:a]apad=pad_dur=2[a0];[a0][1:a]concat=n=2:v=0:a=1" \
        {combo_path}
      ```
      `apad=pad_dur=2` appends 2 seconds of silence to the sentence audio in the sentence's native sample rate, then `concat` joins it with the expression audio. No separate silence generator needed; no sample-rate mismatch risk.
   e. Push all three files to Anki via `storeMediaFile` (base64-encoded `data` field). `storeMediaFile` is idempotent by filename — overwrites cleanly.
   f. `addNote` with:
      - `deckName`: `"Inch 3 - {lang_code}"`
      - `modelName`: `"Inch 3 Vocab"`
      - `fields`: see Section 7.2.
      - `tags`: `["inch3", f"lang:{lang_code}"]`.
      - `options`: `{"allowDuplicate": true}` (dedup is enforced in the DB, not Anki).
   g. If `addNote` returns an integer note ID: `UPDATE anki_vocab_items SET exported_at = CURRENT_TIMESTAMP, anki_note_id = ? WHERE id = ?`.
   h. If `addNote` returns an error, log it, increment failure counter, continue to the next item.
8. Print summary to stdout: `[anki-export] {success_count} exported, {failure_count} failed`.
9. Exit 0 on any success; exit 1 only if ALL items failed (to signal a systemic problem to the caller).

**Error handling:**
- Connection errors to AnkiConnect → exit 1 immediately.
- Per-item TTS failures → log and skip that item.
- Per-item ffmpeg failures → log and skip that item.
- Partial success is fine; the unexported items remain queued for the next run.

**Credential safety:** never log `INCH_TTS_API_KEY` or `api_key`. The script prints only counts, filenames, and error messages with credential fields redacted.

### 5.3 Media file layout

```
data/
├── inch-3.db
└── anki-media/
    ├── sentences/
    │   ├── inch3_spa_s4521_sentence.mp3
    │   ├── inch3_spa_s4522_sentence.mp3
    │   └── ...
    └── tmp/                            ← expr.mp3 and combo.mp3 during export only
```

- `data/anki-media/sentences/` is the long-lived sentence-audio cache. Only sentence files live here — not expression or combo files — because only sentences are shared across multiple vocab items.
- `data/anki-media/tmp/` is cleaned at the start and end of every `anki-export.py` run.
- Both paths are under `data/`, which is gitignored.
- `.gitignore` already excludes `data/`; no new rule needed.

## 6. Connect flow

### 6.1 Skill: `/inch-connect-anki`

New file `.claude/commands/inch-connect-anki.md`, mirroring `/inch-connect-telegram`.

**Entry points:**
1. User explicitly runs `/inch-connect-anki`.
2. `/inch-export-anki-cards` when `anki_config.is_active != 1` or the probe fails — hands off to this flow, then resumes export after success.

**Flow:**

1. Check for `ffmpeg`: `command -v ffmpeg`. If missing, print install hint (`apt install ffmpeg` on Debian/Ubuntu) and abort.
2. `SELECT * FROM anki_config WHERE id = 1`. If no row (should not happen post-migration, but belt-and-braces): `INSERT INTO anki_config (id) VALUES (1)`.
3. Ask the user (in the Claude Code console):
   - (a) Anki runs on this same machine → keep `host=127.0.0.1`, `port=8765`.
   - (b) Anki runs elsewhere → prompt for host and optional port.
   - (c) Re-verify existing config.
4. Probe:
   ```
   POST http://{host}:{port}
   Content-Type: application/json
   {"action": "version", "version": 6, "key": "{api_key or null}"}
   ```
5. Classify response:
   - **Success** (result ≥ 6, error null): also call `deckNames` to confirm the full RPC path works. On success:
     ```sql
     UPDATE anki_config
     SET host = ?, port = ?, api_key = ?, is_active = 1,
         configured_at = COALESCE(configured_at, CURRENT_TIMESTAMP),
         last_verified_at = CURRENT_TIMESTAMP
     WHERE id = 1;
     ```
     Send `tg-send-text "Anki is connected. Ready to export vocab cards."` and return control to the caller.
   - **Connection refused / timeout:** print the setup instructions below, leave `is_active = 0`, abort.
   - **HTTP 403 or auth error:** AnkiConnect is configured with an `apiKey`. Prompt for it, update `anki_config.api_key`, retry probe once.
   - **Unexpected response shape** (e.g. HTML): print "Something is listening at {host}:{port} but it isn't AnkiConnect." Abort.

**Setup instructions message (printed to console on connection refused):**
```
AnkiConnect is not reachable at http://{host}:{port}.

To set up AnkiConnect:
  1. Install Anki desktop: https://apps.ankiweb.net
  2. In Anki: Tools → Add-ons → Get Add-ons…
  3. Enter code: 2055492159  (AnkiConnect)
  4. Restart Anki.
  5. Keep Anki running, then re-run /inch-connect-anki.

If Anki runs on a different machine than Claude Code, you may also need
to edit the AnkiConnect config to allow remote origins.
See: https://foosoft.net/projects/anki-connect/
```

**Credential hygiene:** `api_key` is never echoed after entry. Console prints the configured host/port but never the key.

## 7. Anki note model and card templates

### 7.1 Model creation (first export only)

AnkiConnect `createModel` payload:
```json
{
  "modelName": "Inch 3 Vocab",
  "inOrderFields": [
    "SentenceL2",
    "SentenceAudio",
    "ComboAudio",
    "Expression",
    "ExpressionAudio",
    "ExpressionL1"
  ],
  "css": "<see Section 7.3>",
  "cardTemplates": [
    { "Name": "Card A — L1 → L2 audio",
      "Front": "<see Section 7.2 A>",
      "Back":  "<see Section 7.2 A>" },
    { "Name": "Card B — L2 audio + L1 → L2 audio",
      "Front": "<see Section 7.2 B>",
      "Back":  "<see Section 7.2 B>" }
  ]
}
```

### 7.2 Fields (per note)

| Field | Content for an example item |
|---|---|
| `SentenceL2` | `Me da igual, vamos cuando quieras.` |
| `SentenceAudio` | `[sound:inch3_spa_s4521_sentence.mp3]` |
| `ComboAudio` | `[sound:inch3_spa_v128_combo.mp3]` |
| `Expression` | `me da igual` |
| `ExpressionAudio` | `[sound:inch3_spa_v128_expr.mp3]` |
| `ExpressionL1` | `無所謂` |

### 7.3 Card templates

**Card A — Production (L1 translation → recall L2 expression from combined audio)**

Front:
```html
{{ComboAudio}}
```
Back:
```html
{{FrontSide}}
<hr id=answer>
<div class="expr-l1">{{ExpressionL1}}</div>
<div class="expr-l2">{{Expression}}</div>
<div class="sentence-l2">{{SentenceL2}}</div>
```

Card A front plays a single audio file (`ComboAudio`) that already contains sentence + 2-second silence + expression, pre-merged by ffmpeg. No reliance on Anki's natural gap between consecutive `[sound:]` tags.

**Card B — Recognition (L2 audio + L1 → recall L2 expression audio)**

Front:
```html
{{SentenceAudio}}
<br>
<div class="expr-l1">{{ExpressionL1}}</div>
```
Back:
```html
{{FrontSide}}
<hr id=answer>
{{ExpressionAudio}}
<div class="expr-l2">{{Expression}}</div>
```

### 7.4 Shared CSS

```css
.card {
  font-family: -apple-system, "Segoe UI", sans-serif;
  font-size: 20px;
  text-align: center;
  color: #222;
  background: #fafafa;
}
.expr-l2 {
  font-size: 28px;
  font-weight: 600;
  margin: 16px 0 8px;
}
.expr-l1 {
  font-size: 22px;
  color: #555;
  margin: 12px 0;
}
.sentence-l2 {
  font-size: 16px;
  color: #888;
  margin-top: 20px;
}
```

## 8. Prune flow

### 8.1 Skill: `/inch-prune-anki`

New file `.claude/commands/inch-prune-anki.md`. Manual-only — never auto-triggered.

**Flow:**

1. Pre-flight: active language profile + `anki_config.is_active = 1`. Abort with guidance otherwise.
2. `lang_code = ...` (from active profile).
3. AnkiConnect call chain:
   - `findCards` with query `deck:"Inch 3 - {lang_code}"` → list of card IDs.
   - `cardsInfo` on all card IDs → extract `interval`, `reps`, `lapses`, `factor`, `queue`, `note` fields.
4. Group cards by `note` (each note has two cards: Card A and Card B).
5. Filter to prune-eligible notes. A note is eligible only if **every card in the note** satisfies:
   - `interval >= 548` (days, 1.5 years minimum).
   - `reps >= 5`.
   - `queue == 2` (in the regular review queue — not learning, relearning, suspended, or buried).
   - `factor >= 2000` (AnkiConnect's `cardsInfo` returns ease as `factor`, stored as 1000× — default 2500; 2000 means the card has taken some penalties but is still in a functional state).
   - `lapses / max(reps, 1) < 0.3` (fewer than 30% of reviews have been failures, protecting against cards the user has been dragging through long intervals without actually retaining them).
6. Cross-reference with DB:
   ```sql
   SELECT id, expression, sentence_id FROM anki_vocab_items
   WHERE anki_note_id IN (?, ?, ...);
   ```
   The intersection is the prunable set.
7. Compute stats:
   - Eligible note count.
   - Estimated media freed: `count * 320 KB` (a rough constant — combo ≈ 270 KB + expr ≈ 48 KB). Sentence files are shared, so they are NOT counted per-note; shared sentence files are freed separately at step 10c.
   - Oldest eligible `captured_at` (from the DB side).
8. Print summary to console:
   ```
   Deck: Inch 3 - spa
     Total notes in deck: 2,134
     Eligible for pruning: 412
       (interval ≥ 548d, reps ≥ 5, queue = review, factor ≥ 2000, lapse ratio < 0.3)
     Estimated media freed: ~130 MB (not counting shared sentence files)
     Oldest eligible capture: 2025-08-03
   ```
9. Prompt the user (in the Claude Code console):
   - (a) Prune now.
   - (b) Show the list (print all eligible items with expression and sentence_l2 excerpt), then re-prompt.
   - (c) Cancel — no changes.
10. On confirmation:
   a. AnkiConnect `deleteNotes` with the list of `anki_note_id`s.
   b. For each note, AnkiConnect `deleteMediaFile` on `combo.mp3` and `expr.mp3`. Do NOT delete `sentence.mp3` yet.
   c. Sentence cleanup pass: for each distinct `sentence_id` among the pruned items, check whether any un-pruned, un-exported-later item from the same `lang_profile_id` still references it. If none, `deleteMediaFile` on the sentence file AND delete the local cache file at `data/anki-media/sentences/inch3_{lang_code}_s{sentence_id}_sentence.mp3`.
   d. `UPDATE anki_vocab_items SET pruned_at = CURRENT_TIMESTAMP WHERE id IN (...)`. Do NOT delete the row.
   e. Send `tg-send-text "Pruned 412 cards from Inch 3 - spa. Freed ~130 MB."`

### 8.2 Dry-run mode

`/inch-prune-anki --dry-run` stops after step 8. No AnkiConnect writes, no DB writes, no file deletions.

### 8.3 Anti-footgun rules

- Never skip the confirmation prompt.
- Never prune a note whose `exported_at IS NULL` (impossible by construction, but the query defensively filters `WHERE exported_at IS NOT NULL AND pruned_at IS NULL`).
- Never delete a local cache file without confirming the AnkiConnect `deleteMediaFile` call succeeded first.
- `pruned_at` is the single authoritative marker — future `/inch-export-anki-cards` runs skip anything with `pruned_at IS NOT NULL`.

## 9. Documentation updates

### 9.1 `TABLES.md`
- Add `anki_config` section with column table and notes.
- Add `anki_vocab_items` section with column table, state diagram, notes on the partial index.
- Update `study_sessions.status` description to list `paused` as a fourth valid value.
- Update the ER summary diagram to show the two new tables and their FK to `language_profiles` and `sentences`.

### 9.2 `CLAUDE.md`
- Add the three new skill commands to the commands table.
- Add a short note in the "Key Rules" section: `/inch-prune-anki` is destructive and never auto-triggers.
- Add one line to the directory structure listing `scripts/anki-export.py` and `scripts/migrations/0001_anki_tables.sql`.

### 9.3 `.gitignore`
No change needed — `data/` is already excluded, which covers both the DB and `data/anki-media/`.

## 10. File manifest

**New files:**
- `scripts/migrations/0001_anki_tables.sql`
- `scripts/anki-export.py`
- `.claude/commands/inch-connect-anki.md`
- `.claude/commands/inch-export-anki-cards.md`
- `.claude/commands/inch-prune-anki.md`
- `docs/superpowers/specs/2026-04-11-anki-export-design.md` (this file)

**Modified files:**
- `.claude/commands/inch-continue.md` (capture cluster, auto-export cluster, stop/pause response class)
- `TABLES.md` (new tables, new status value)
- `CLAUDE.md` (new skill commands in table)

**Unchanged:**
- `scripts/backup-db.sh`
- `scripts/tts-generate.sh`
- `scripts/tg-send-audio.sh`, `tg-send-text.sh`, `tg-poll-response.sh`
- All other existing skills.

## 11. Rules

Absolute rules (never violated):

1. **Credentials are never logged or printed.** `tts_api_key`, `bot_token`, and `anki_config.api_key` are read from the DB at session start, cached in env vars, and never written to stdout, logs, or Telegram.
2. **Capture failures never interrupt study.** A DB error during `INSERT OR IGNORE` logs to console and the session continues.
3. **Auto-export never forces setup.** If `anki_config.is_active = 0`, auto-export silently skips. The user must explicitly run `/inch-connect-anki` to opt in.
4. **Auto-export never blocks session wrap-up.** A failing export logs to console and sends one Telegram notice, then continues to `SESSION COMPLETE`.
5. **Pruning requires explicit user confirmation.** Never destructive without a prompt.
6. **DB is the source of truth for what's been exported.** `exported_at IS NOT NULL` means Anki has a copy; do not re-export such rows. `pruned_at IS NOT NULL` means the user retired the card; never resurrect automatically.
7. **The UNIQUE constraint on `(lang_profile_id, sentence_id, expression)` is the dedup mechanism.** Inch 3 does not rely on Anki's first-field duplicate check (which would misfire across multiple expressions from the same sentence).

## 12. Out-of-scope / future work

- **Resurrecting pruned items.** A `/inch-unprune-anki` skill could re-export rows where `pruned_at IS NOT NULL`. Not needed in v1.
- **Bidirectional sync.** Pulling review stats back into Inch 3 would let the study loop adjust block familiarity based on Anki retention. Interesting but non-trivial; out of scope.
- **Custom card templates per language.** Some languages might benefit from furigana, pinyin, transliteration, etc. The v1 template is language-agnostic text + audio; per-language customisation can be added later by branching the model by `lang_code`.
- **Incremental export during the session** (pushing items to Anki as they are captured, not only at session end). Trades complexity for real-time feel; not worth it for v1.
- **GUI for editing vocab items before export.** For now, the user edits via `sqlite3` if a correction is needed.
