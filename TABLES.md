# Inch 3 — Database Tables Reference

All tables live in `data/inch-3.db` (SQLite, WAL mode). The `data/` directory is never committed to git.

---

## Table of Contents

1. [app_settings](#1-app_settings)
2. [telegram_config](#2-telegram_config)
3. [language_profiles](#3-language_profiles)
4. [books](#4-books)
5. [chapters](#5-chapters)
6. [sentences](#6-sentences)
7. [sentence_blocks](#7-sentence_blocks)
8. [user_knowledge_items](#8-user_knowledge_items)
9. [study_sessions](#9-study_sessions)
10. [sentence_study_records](#10-sentence_study_records)
11. [anki_config](#11-anki_config)
12. [anki_vocab_items](#12-anki_vocab_items)

---

## 1. `app_settings`

Global key-value configuration store. Used for settings that apply across all language profiles.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `key`  | TEXT | PRIMARY KEY | Setting name |
| `value` | TEXT | | Setting value (always stored as text) |

**Known keys:**

Currently no keys are in active use. The active language profile is tracked via `language_profiles.is_active`.

---

## 2. `telegram_config`

Singleton table holding the Telegram bot connection. The `CHECK(id=1)` constraint enforces that only one row can ever exist.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY, CHECK(id=1) | Always 1. Enforces singleton. |
| `bot_token` | TEXT | | The full HTTP API token issued by BotFather (e.g. `123456789:ABCdef…`). Stored directly in the local DB — never committed to git. |
| `chat_id` | INTEGER | | The Telegram chat ID of the user. 64-bit signed integer — do **not** store as TEXT or cast to 32-bit. Detected automatically during `/inch-connect-telegram` setup. |
| `bot_username` | TEXT | | The bot's `@username` as returned by `getMe` (e.g. `inch3_bot`). For display and logging only. |
| `is_active` | BOOLEAN | DEFAULT 0 | Set to `1` only after a test message is successfully delivered. Scripts refuse to run if `is_active = 0`. |
| `configured_at` | DATETIME | | Timestamp of initial configuration. ISO 8601 format (`YYYY-MM-DD HH:MM:SS`). |
| `last_verified_at` | DATETIME | | Timestamp of the last successful delivery test. Updated by `/inch-connect-telegram` on reconfiguration. |

**Notes:**
- All three Telegram scripts (`tg-send-audio.sh`, `tg-send-text.sh`, `tg-poll-response.sh`) read `bot_token` and `chat_id` from this table at runtime.
- The `INCH_BOT_TOKEN` environment variable overrides the DB value (useful for testing).

---

## 3. `language_profiles`

One row per target language. Stores all TTS configuration, speed settings, and study resume pointers for that language. Multiple profiles can exist; only one is active at a time (tracked in `app_settings`).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `lang_code` | TEXT | UNIQUE, NOT NULL | ISO 639-3 three-letter language code (e.g. `jpn`, `rus`, `ara`, `deu`). Used as the foreign key throughout the system. |
| `lang_name` | TEXT | | Human-readable language name in English (e.g. `Japanese`, `Russian`). |
| `l1_code` | TEXT | DEFAULT `'zht'` | ISO 639-3 code for the user's native language (L1). Default is `zht` (Traditional Chinese). |
| `l1_name` | TEXT | DEFAULT `'繁體中文'` | Display name for the L1 language. |
| `tts_endpoint` | TEXT | | Full URL of the OpenAI-compatible TTS endpoint, including path (e.g. `https://api.openai.com/v1/audio/speech`). Must accept `POST` with JSON body `{model, input, voice, speed}`. |
| `tts_model` | TEXT | | TTS model name passed in the API request body (e.g. `tts-1`, `tts-1-hd`, `kokoro`). |
| `tts_voice` | TEXT | | Voice ID or name passed to the TTS API (e.g. `alloy`, `nova`, `af_sky`). Voice availability depends on the endpoint. |
| `tts_api_key` | TEXT | | The API key sent as `Authorization: Bearer <key>` to the TTS endpoint. Stored directly in the local DB — never committed to git. |
| `tts_speed_normal` | REAL | DEFAULT 0.85 | Playback speed for normal delivery. Range: `0.5`–`1.0`. Applied to all blocks unless the user responds "slower". |
| `tts_speed_slow` | REAL | DEFAULT 0.7 | Playback speed when the user requests a replay at reduced speed. Range: `0.5`–`1.0`. |
| `last_sentence_id` | INTEGER | FK → `sentences.id` | ID of the last sentence studied in this language profile. Used by `/inch-continue` to resume from the correct position. `NULL` if no sessions have been run. |
| `last_block_order` | INTEGER | | Block order index (0-based) within `last_sentence_id` where the previous session ended. `NULL` if the sentence was fully completed. |
| `skip_threshold` | REAL | DEFAULT 0.8 | Familiarity score above which a block is skipped during a session (not re-presented). Blocks with `familiarity >= skip_threshold` are collapsed/skipped. |
| `is_active` | BOOLEAN | DEFAULT 1 | Whether this profile is currently selected. Exactly one profile has `is_active = 1` at a time. Toggled by `/inch-switch-language-profile` (old→0, new→1) and `/inch-setup-new-language-profile` (all others→0, new→1). This is the **single source of truth** for active language. |
| `created_at` | DATETIME | | Profile creation timestamp. |
| `updated_at` | DATETIME | | Last modification timestamp. Updated on any profile field change. |

**Notes:**
- Created and populated by `/inch-setup-new-language-profile`.
- `tts_endpoint`, `tts_model`, `tts_voice`, and `tts_api_key` are tested together before being saved — the endpoint must return valid audio for a target-language test phrase.
- `last_sentence_id` and `last_block_order` are written by `/inch-continue` at the end of every session.

---

## 4. `books`

One row per imported source text. A book belongs to a single language profile and contains one or more chapters.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `code` | TEXT | UNIQUE, NOT NULL | Short identifier for the book (e.g. `jpn-kokoro`). Used as a stable reference across sessions. |
| `lang_profile_id` | INTEGER | FK → `language_profiles.id` | The language profile this book belongs to. |
| `title` | TEXT | | Full title of the work. |
| `author` | TEXT | | Author name. |
| `publish_year` | TEXT | | Year of publication. Stored as TEXT to accommodate partial dates (e.g. `c.1890`). |
| `format` | TEXT | | Source file format at import time: `epub`, `pdf`, `txt`, `md`, or `jpg-folder`. |
| `import_path` | TEXT | | Absolute path to the original source file at the time of import. For reference only — the file may have moved since. |
| `created_at` | DATETIME | | Import timestamp. |

---

## 5. `chapters`

One row per chapter within a book. Chapters are numbered sequentially within a book.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `book_id` | INTEGER | FK → `books.id`, NOT NULL | The book this chapter belongs to. |
| `chapter_num` | INTEGER | NOT NULL | Display order within the book (1-based). |
| `chapter_title` | TEXT | | Chapter heading or title as extracted from the source file. May be `NULL` for untitled chapters. |
| `review_flag` | BOOLEAN | DEFAULT 0 | Set to `1` by the importer when the sentence count looks anomalous (e.g. suspiciously low), flagging the chapter for manual review. |
| `created_at` | DATETIME | | Import timestamp. |

---

## 6. `sentences`

One row per sentence extracted from a chapter. Sentences are the primary unit of study — each `/inch-continue` session works through 10 sentences.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `chapter_id` | INTEGER | FK → `chapters.id` | The chapter this sentence belongs to. |
| `book_id` | INTEGER | FK → `books.id` | Denormalized book reference (avoids a join when querying sentences by book). |
| `lang_profile_id` | INTEGER | FK → `language_profiles.id` | The language profile this sentence was imported under. |
| `l2_text` | TEXT | NOT NULL | The full sentence text in the target language (L2), exactly as it appears in the source. |
| `char_count` | INTEGER | | Character count of `l2_text`. Used for session statistics and import reporting. |
| `study_status` | TEXT | DEFAULT `'unstudied'` | Progress state. One of: `unstudied` (never seen), `in_progress` (partially studied — session interrupted), `completed` (all blocks presented and session ended normally). |
| `created_at` | DATETIME | | Import timestamp. |
| `updated_at` | DATETIME | | Last status change timestamp. |

---

## 7. `sentence_blocks`

One row per NP/VP chunk within a sentence. Blocks are the atomic unit of TTS delivery — each block is spoken once and the user responds before the next one is played.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `sentence_id` | INTEGER | FK → `sentences.id`, NOT NULL | The sentence this block belongs to. |
| `block_order` | INTEGER | NOT NULL | 0-based position of this block within its sentence. Blocks are always presented in ascending `block_order`. |
| `tts_text` | TEXT | NOT NULL | The text string sent to the TTS API. May differ from `l2_display` — for example, readings may be provided for rare kanji, or punctuation stripped for cleaner audio. |
| `l2_display` | TEXT | NOT NULL | The written form of the block shown to the user on screen after the audio plays. Always the canonical orthographic form. |
| `l1_text` | TEXT | | Translation of this block into the user's L1 language. Shown after the block is presented, or on demand. |
| `role` | TEXT | NOT NULL | Grammatical role of the block. One of the canonical pattern names defined in `knowledge/chunking-strategy.md`: `NP-A`, `NP-B(a)`, `NP-B(b)`, `Compound`, `VP-A`, `VP-B`, `VP-C`, `VP-D`, `VP-E`, `VP-F`, `VP-G`, `VP-H`, `VP-I`. |
| `created_at` | DATETIME | | Generation timestamp (set when blocks are generated by `/inch-continue`). |

**Notes:**
- Blocks are generated lazily by `/inch-continue` when a sentence is first studied. The full block list for a sentence is stored permanently.
- **Block collapsing is always presentation-time.** When `familiarity >= skip_threshold` for a block's `tts_text`, that block is collapsed into the adjacent block during delivery — but the DB record is never modified. The stored block list is always the full, uncollapsed set.
- The `tts_text` value is also used as the lookup key in `user_knowledge_items`.

---

## 8. `user_knowledge_items`

Tracks the user's familiarity with individual expressions (keyed by `tts_text`). One row per unique expression per language profile. Updated after every block interaction.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `lang_profile_id` | INTEGER | FK → `language_profiles.id` | The language profile this knowledge item belongs to. |
| `tts_text` | TEXT | NOT NULL | The expression this row tracks. Matches `sentence_blocks.tts_text`. The same expression appearing in multiple sentences shares one row. |
| `times_seen` | INTEGER | DEFAULT 0 | Total number of times this expression has been presented via audio in a session. |
| `times_confused` | INTEGER | DEFAULT 0 | Number of times the user responded with a "confused" signal (e.g. `?`, `what`, `don't understand`). Each confused response is a strong negative signal. |
| `times_slower` | INTEGER | DEFAULT 0 | Number of times the user asked for a slower replay (`slower`, `again slow`). Moderate negative signal. |
| `times_explained` | INTEGER | DEFAULT 0 | Number of times the user asked for an explanation (`explain`, `why`). Moderate negative signal. |
| `familiarity` | REAL | DEFAULT 0.1667 | Laplace-smoothed familiarity score in range `(0, 1)`. Higher = more familiar. See formula below. |
| `last_seen_at` | DATETIME | | Timestamp of the most recent presentation. |
| `created_at` | DATETIME | | Row creation timestamp (first time this expression was seen). |
| `updated_at` | DATETIME | | Last update timestamp. |

**Familiarity formula:**

```
familiarity = (times_seen + 1)
              ─────────────────────────────────────────────────────────
              (times_seen + 1) + (times_confused × 3) + (times_slower × 2) + (times_explained × 2) + 5
```

| Scenario | Approximate familiarity |
|----------|------------------------|
| Fresh expression (never seen) | ≈ 0.17 (1/6) |
| Seen 5 times, no issues | ≈ 0.55 (6/11) |
| Seen 10 times, no issues | ≈ 0.69 (11/16) |
| Seen 20 times, no issues | ≈ 0.81 — crosses default skip threshold of 0.8 |
| Seen 10 times, confused twice | ≈ 0.44 (11/25) |

A block is skipped during delivery when `familiarity >= language_profiles.skip_threshold` (default `0.8`).

---

## 9. `study_sessions`

One row per `/inch-continue` invocation. Records the overall status and sentence count for each session.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `lang_profile_id` | INTEGER | FK → `language_profiles.id` | The active language profile during this session. |
| `status` | TEXT | DEFAULT `'active'` | Session state: `active` (in progress), `completed` (10 sentences finished normally), `abandoned` (user quit or timeout), `paused` (user said stop/pause; `ended_at` is set). |
| `sentences_studied` | INTEGER | DEFAULT 0 | Count of sentences fully completed in this session. Updated incrementally as each sentence finishes. |
| `started_at` | DATETIME | | Timestamp when `/inch-continue` began the session. |
| `ended_at` | DATETIME | | Timestamp when the session ended (status changed to `completed` or `abandoned`). `NULL` while active. |
| `created_at` | DATETIME | | Row creation timestamp. |

---

## 10. `sentence_study_records`

One row per sentence within a session. Tracks the delivery progress within a single sentence — how many blocks have been presented and whether the sentence was fully completed.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY | Auto-increment row ID. |
| `session_id` | INTEGER | FK → `study_sessions.id` | The session this record belongs to. |
| `sentence_id` | INTEGER | FK → `sentences.id` | The sentence being studied. |
| `blocks_presented` | INTEGER | DEFAULT 0 | Number of blocks from this sentence that have been delivered so far in this session. |
| `current_block_order` | INTEGER | | The `block_order` of the block currently being presented (or the next one to be presented if the session was interrupted). |
| `total_blocks` | INTEGER | | Total number of blocks in this sentence (after familiarity-based collapsing is applied for this session). May be less than the count of rows in `sentence_blocks` if some blocks were collapsed. |
| `is_completed` | BOOLEAN | DEFAULT 0 | Set to `1` when all blocks in this sentence have been presented and the user's final response recorded. |
| `completed_at` | DATETIME | | Timestamp when `is_completed` was set to `1`. `NULL` until completed. |
| `created_at` | DATETIME | | Row creation timestamp. |

---

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
- Rows are exported by `scripts/anki-export.py`, invoked only via `/inch-export-anki-cards` (user-initiated; no auto-export at session end).
- Rows are pruned (soft-deleted, `pruned_at` set) in two cases:
  - Automatically by `scripts/anki-export.py` when `word_count(expression) >= 6` — such items are considered too long to serve as atomic Anki cards and are skipped on export.
  - Manually by `/inch-prune-anki` once the underlying Anki cards have been mastered.

---

## Indexes

Beyond primary keys and UNIQUE constraints, the following indexes exist:

| Index | Table | Columns | Purpose |
|-------|-------|---------|---------|
| `idx_sentences_study` | `sentences` | `(lang_profile_id, study_status, book_id, chapter_id, id)` | Covers the "next unstudied sentence" query used by `/inch-generate-blocks` and `/inch-continue`. |
| `idx_sentence_blocks_sentence` | `sentence_blocks` | `(sentence_id)` | Covers block lookups by sentence and the anti-join pattern (sentences with no blocks). |
| `idx_uki_profile_text` | `user_knowledge_items` | `(lang_profile_id, tts_text)` UNIQUE | Enables UPSERT via `ON CONFLICT(lang_profile_id, tts_text)` and enforces one row per expression per language. |
| `idx_anki_vocab_unexported` | `anki_vocab_items` | `(lang_profile_id, exported_at)` partial `WHERE exported_at IS NULL AND pruned_at IS NULL` | Covers the "pending export" query used by `scripts/anki-export.py` (invoked via `/inch-export-anki-cards`). |

---

## Entity Relationship Summary

```
app_settings                          (global config, no FK)

telegram_config                       (singleton, no FK)

language_profiles
  └─< books (lang_profile_id)
        └─< chapters (book_id)
              └─< sentences (chapter_id, book_id, lang_profile_id)
                    └─< sentence_blocks (sentence_id)

language_profiles
  └─< user_knowledge_items (lang_profile_id)

language_profiles
  └─< anki_vocab_items (lang_profile_id)
        └── sentences (sentence_id)
        └── sentence_blocks (source_block_id)

language_profiles
  └─< study_sessions (lang_profile_id)
        └─< sentence_study_records (session_id)
              └── sentences (sentence_id)

anki_config                           (singleton, no FK)
```
