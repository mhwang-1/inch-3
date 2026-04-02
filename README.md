# Inch 3

Personal language learning assistant operated through Claude Code and Telegram. No web UI, no server process — Claude Code skills orchestrate everything: generating TTS audio, delivering it via Telegram, waiting for your response, and recording study state in a local SQLite database.

---

## Table of Contents

- [Design Philosophy](#design-philosophy)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Directory Structure](#directory-structure)
- [Process Flow](#process-flow)
  - [First-Time Setup](#1-first-time-setup)
  - [Importing Reading Material](#2-importing-reading-material)
  - [Study Session](#3-study-session)
  - [Chunking Strategy](#4-chunking-strategy)
  - [Response Handling](#5-response-handling)
  - [Session Timeout and Recovery](#6-session-timeout-and-recovery)
- [Skill Commands Reference](#skill-commands-reference)
- [Multi-Language Support](#multi-language-support)
- [Security Model](#security-model)
- [Database Overview](#database-overview)
- [Portability](#portability)
- [Troubleshooting](#troubleshooting)

---

## Design Philosophy

Inch 3 is built around two ideas:

1. **Reading-based acquisition.** Study material comes from real books — novels, essays, news — not curated vocabulary lists. You bring your own text; Inch 3 breaks it into sentences and teaches it to you incrementally.

2. **Listening-first delivery.** Each chunk of a sentence is delivered as a TTS audio clip before the text is shown. You listen, respond, and only then see the written form. This trains ears before eyes.

Claude Code acts as the session controller. It has no persistent daemon — each `/inch-continue` invocation is a Claude Code process that holds itself open for the duration of a 10-sentence session (typically 30–60 minutes), drives the Telegram API, and closes cleanly when the session ends.

---

## Prerequisites

- **Claude Code** — the session controller.
- **Telegram bot** — for audio delivery and user responses. Create one via [@BotFather](https://t.me/BotFather).
- **TTS API endpoint** — any OpenAI-compatible `/v1/audio/speech` endpoint (e.g. OpenAI, a self-hosted Kokoro server, or similar). One endpoint per language profile.
- **`sqlite3`** — for the database. Usually pre-installed.
- **`curl`** — used by all Telegram scripts.
- **`uv`** — for running Python utility scripts (PEP 723 inline dependencies, no `requirements.txt` needed).

---

## Initial Setup

These steps are done once per machine.

```
1. /inch-connect-telegram          — connect your Telegram bot and detect your chat ID
2. /inch-setup-new-language-profile — configure a language, TTS endpoint, and voice
3. /inch-import-books <path>        — import a book into the database
4. /inch-continue                   — start studying
```

---

## Directory Structure

```
inch-3/
├── CLAUDE.md                          ← Instructions for Claude Code (read every session).
├── README.md                          ← This file.
├── .gitignore                         ← Excludes data/, secrets, OS files.
├── .claude/
│   └── commands/                      ← Skill files (slash commands for Claude Code).
│       ├── inch-import-books.md
│       ├── inch-setup-new-language-profile.md
│       ├── inch-connect-telegram.md
│       ├── inch-continue.md
│       └── inch-switch-language-profile.md
├── knowledge/                         ← Study preferences and language references (committed).
│   ├── preferences.md                 ← Study preferences, TTS speeds, L1 settings.
│   ├── chunking-strategy.md           ← Language-agnostic NP/VP block-generation rules.
│   └── {lang_code}.md                 ← Per-language grammar + chunking guide (one per language).
├── scripts/                           ← Bash utility scripts.
│   ├── backup-db.sh                   ← Daily DB backup; runs at session start.
│   ├── tg-send-audio.sh               ← Send a local audio file to Telegram.
│   ├── tg-poll-response.sh            ← Long-poll Telegram getUpdates for user reply.
│   └── tg-send-text.sh                ← Send a text message to Telegram.
└── data/                              ← Runtime data. NEVER committed to git.
    ├── inch-3.db                      ← SQLite database (all study data and config).
    ├── inch-3.db-wal                  ← SQLite WAL journal.
    ├── inch-3.db-shm                  ← SQLite shared memory.
    └── inch-3_YYYYMMDD_HHmmss.db     ← Rolling daily backups (10-day max).
```

---

## Process Flow

### 1. First-Time Setup

#### Connect Telegram (`/inch-connect-telegram`)

1. You provide the bot token from BotFather.
2. The skill validates the token via the Telegram API.
3. It asks you to send a message to the bot, then detects your `chat_id` from `getUpdates`.
4. The token and `chat_id` are stored directly in the database (`telegram_config` table). The `data/` directory is never committed to git.

#### Configure a Language Profile (`/inch-setup-new-language-profile`)

1. You specify the target language (name + ISO 639-3 code, e.g. `jpn` for Japanese).
2. You provide the TTS endpoint URL, model name, voice ID, normal speed (default 0.85), and slow speed (default 0.7).
3. The skill generates a short test phrase in the target language, calls the TTS API at `speed=1.0`, saves the audio to `/tmp/inch3-tts-test.ogg`, and asks you to confirm the audio sounds correct. Nothing is saved to the DB until this test passes.
4. Once confirmed, the language profile is inserted into `language_profiles` and set as the active profile.
5. A research agent fetches grammar information for the language from authoritative sources. A draft `knowledge/{lang_code}.md` is written with full NP/VP chunking pattern definitions specific to that language.
6. Two review agents run in parallel — one checks grammar accuracy, one challenges the pattern definitions. Findings are consolidated and the file is revised before being committed to git.

### 2. Importing Reading Material (`/inch-import-books`)

Input formats: **epub**, **pdf** (text layer or OCR fallback), **jpg/png folder** (OCR), **txt/md**.

Flow:
1. Metadata is collected first: title, language, author, year. The language must match an existing profile.
2. Text is extracted using the appropriate tool (`pandoc`/`ebooklib` for epub; `tesseract` for images).
3. The text is split into chapters. A preview is shown; you can merge, rename, or reorder before confirming.
4. Sentences are segmented using language-appropriate rules (e.g. `。！？` for Japanese, punctuation heuristics for CJK, tokenizer for Latin scripts).
5. Sentences are written to the DB in batches of 50 within single transactions. Failed batches are logged and skipped; nothing is silently lost.
6. A summary is printed: total chapters, sentences imported, flagged chapters (suspicious sentence counts), and failed batches.

### 3. Study Session (`/inch-continue`)

At session start, Claude Code:
1. Verifies an active language profile and Telegram config exist.
2. Runs `scripts/backup-db.sh` (creates today's backup if one does not yet exist).
3. Checks for an unfinished sentence from a previous session. If found, resumes at the last saved block. Otherwise, picks the next unstudied sentence.

**Per-sentence loop (10 sentences per session):**

For each sentence, Claude Code generates all blocks upfront (see [Chunking Strategy](#4-chunking-strategy) below), then delivers them one by one.

**Per-block delivery:**

```
1. Check familiarity of this block's expression.
   — If familiarity ≥ 0.8 (seen ≥ 5× without confusion), the block may be
     collapsed with an adjacent block at presentation time. Skip to next block.

2. Call TTS API → save audio to /tmp/inch3-block-{N}.ogg

3. Write current state to DB (sentence_study_records: blocks_presented,
   current_block_order; language_profiles: last_sentence_id, last_block_order).
   State is written BEFORE waiting for a response, so a session can always resume.

4. Send audio via: bash scripts/tg-send-audio.sh /tmp/inch3-block-{N}.ogg

5. Poll for user response: bash scripts/tg-poll-response.sh 900
   (15-minute timeout; a warning message is sent to Telegram at 2 minutes remaining)

6. Classify response and act (see Response Handling below).
```

After the last block of a sentence, Claude Code sends the sentence completion prompt and polls again (`tg-poll-response.sh 300`). On confirmation, it advances to the next sentence. After 10 sentences the session ends with a summary.

### 4. Chunking Strategy

Sentences are broken into **progressive chunks** — from a single key word or phrase up to the complete sentence. Each chunk is called a **block** and has a `role` tag drawn from the NP/VP framework:

| Slot | Role |
|---|---|
| NP-A | Core noun phrase (head noun, no modifiers) |
| NP-B(a) | Noun phrase with pre-head modifier |
| NP-B(b) | Noun phrase with post-head modifier (relative clause, etc.) |
| Compound | Fixed or idiomatic expression treated as a single unit |
| VP-A | Single verb, no object or complement |
| VP-B | Verb + direct object |
| VP-C | Verb + prepositional / locative phrase |
| VP-D | Verb + complement (resultative, directional) |
| VP-E | Copula construction |
| VP-F | Modal + verb |
| VP-G | Verb + subordinate clause |
| VP-H | Serial verb / compound predicate |
| VP-I | Full sentence (all slots combined) |

Block generation follows a two-file reference:
- `knowledge/chunking-strategy.md` — language-agnostic framework: phase 0 sentence analysis, slot selection rules, combining phases, familiarity formula, and absolute rules.
- `knowledge/{lang_code}.md` — language-specific: full NP/VP pattern definitions with annotated examples, fixed expression list, combining notes, and L1 translation rules.

The Laplace-smoothed familiarity formula uses a skip threshold of 0.8. Familiarity-based block collapsing is always presentation-time — the full block list is always stored in the DB unchanged.

### 5. Response Handling

During a block poll, the following responses are recognised:

| Response | Action |
|---|---|
| **ok** / **next** / any affirmative | Send block's target-language text; advance to next block. |
| **slower** | Re-call TTS API at `tts_speed_slow` (0.7×); send slow audio; re-poll (900s). |
| **confused** | Send L1 translation of the block; increment `times_confused`; re-deliver same block TTS; re-poll. |
| **explain** / any question | Call LLM for an L1 explanation (context: full sentence + block text); send explanation; increment `times_explained`; re-deliver TTS; re-poll. |
| **unknown / unrecognised** | Send a short reminder of valid commands; re-poll. |

All response events update `user_knowledge_items` (recalculate familiarity) and `sentence_study_records`.

### 6. Session Timeout and Recovery

`scripts/tg-poll-response.sh` uses Telegram long-polling with a configurable default:

- **Default timeout:** 900 seconds (15 minutes). Override via `INCH_POLL_TIMEOUT` env var or first CLI argument.
- **2-minute warning:** When fewer than 120 seconds remain, a Telegram message is sent: *"No response — session times out in ~2 minutes. Reply anything to continue."*
- **First timeout → nudge:** A nudge message is sent and one more poll runs at 180 seconds.
- **Second timeout:** Session is marked abandoned in the DB. Running `/inch-continue` again resumes from the last saved block.

Context-specific timeouts:

| Context | Timeout |
|---|---|
| After audio delivery, `slower`, `explain` | 900 s |
| Nudge re-poll | 180 s |
| Between sentences ("ready for next?") | 300 s |

---

## Skill Commands Reference

| Command | Description |
|---|---|
| `/inch-connect-telegram` | Validate bot token, detect chat ID, store Telegram config in DB. |
| `/inch-setup-new-language-profile` | Configure language, TTS endpoint, voice, and speeds. Tests TTS before saving. Generates `knowledge/{lang_code}.md` via research + review agents. |
| `/inch-import-books <path>` | Import epub/pdf/image-folder/text into DB, split into chapters and sentences. |
| `/inch-continue` | Resume or start a 10-sentence study session. Delivers TTS audio via Telegram; handles `slower`, `ok`, `confused`, `explain` responses. |
| `/inch-switch-language-profile` | Switch the active language profile; shows optional stats; can trigger setup for an unconfigured language. |

---

## Multi-Language Support

Language profiles are independent. Each profile has its own:
- TTS endpoint, model, voice, and speeds
- `knowledge/{lang_code}.md` with language-specific chunking patterns

Language codes follow ISO 639-3 (`jpn`, `rus`, `ara`, etc.). Switch between languages with `/inch-switch-language-profile`. All languages share the same SQLite database, with `lang_profile_id` foreign keys keeping study records separate.

The NP/VP slot framework (NP-A, NP-B, VP-A through VP-I) applies across all language families. SOV languages (Japanese, Korean) and SVO languages (Russian, English) map naturally. VSO languages (Arabic, Hebrew) use VP-initial ordering documented in their `{lang_code}.md`.

If study sessions show persistent confusion (>30% confused rate for 3 or more sessions), regenerate the language reference by re-running `/inch-setup-new-language-profile` and choosing to regenerate the language document.

---

## Security Model

- **API keys are stored in `data/inch-3.db`**, not in any committed file. Both the Telegram bot token (`telegram_config.bot_token`) and TTS API keys (`language_profiles.tts_api_key`) live in the local database only.
- **`data/` is gitignored** and protected by a pre-commit hook that hard-blocks staging any file matching `^data/` or `*.db`.
- **No `.env` files, no OS keychain dependency.** All configuration lives in the DB. The `data/` directory never leaves the machine unless you explicitly copy it.

---

## Database Overview

All persistent state lives in `data/inch-3.db` (SQLite, WAL mode).

Key tables:

| Table | Contents |
|---|---|
| `telegram_config` | Bot token, chat_id, is_active flag. |
| `language_profiles` | One row per language: TTS endpoint, API key, voice, speeds, skip threshold, last study position. |
| `app_settings` | Key-value store for global settings. (Active language is tracked via `language_profiles.is_active`.) |
| `books` | Imported books: title, author, language, year, format. |
| `chapters` | Chapter list with book_id FK and display order. |
| `sentences` | Raw sentence text, chapter FK, study status (`unstudied` / `in_progress` / `completed`). |
| `sentence_blocks` | Generated chunks: tts_text, l2_display, l1_text, role (NP/VP slot), block_order. |
| `user_knowledge_items` | Per-expression familiarity tracking: times_seen, times_confused, familiarity score. |
| `study_sessions` | One row per session: lang_profile_id, sentences_studied, status. |
| `sentence_study_records` | Per-sentence progress: blocks_presented, current_block_order, is_completed. |

Backups are created daily by `scripts/backup-db.sh` (called at session start). A rolling 10-day maximum is enforced — the oldest backup is deleted when a new one is created and the total exceeds 10.

---

## Portability

To move Inch 3 to another machine:

1. `git clone` this repository.
2. Copy `data/inch-3.db` to `data/` on the new machine.
3. Run `/inch-continue` — it will resume from the last saved position.

All credentials (bot token, TTS API keys) travel with the database file. No keychain re-entry required.

No other configuration is needed. The database is self-contained; the `knowledge/` files are in git.

---

## Troubleshooting

**`data/inch-3.db` not found at session start**
The database has not been initialised or was not copied from another machine. Follow the [Initial Setup](#initial-setup) steps, or copy the DB from your other machine.

**TTS audio is silent or in the wrong language**
Re-run `/inch-setup-new-language-profile`. The skill requires a successful TTS test (in the target language, not English) before saving any config.

**Telegram messages stop arriving**
Check that your bot token is still valid and that `telegram_config.is_active = 1` in the DB. Re-run `/inch-connect-telegram` if needed.

**Session times out immediately**
Check that `INCH_POLL_TIMEOUT` is not set to a very small value in your environment. Default is 900 seconds.

**Persistent confusion on blocks (>30% confused rate)**
Re-run `/inch-setup-new-language-profile` and choose to regenerate `knowledge/{lang_code}.md`. This re-dispatches the research and review agents and rewrites the chunking guidance for that language.

**Pre-commit hook blocks a commit**
If you see `BLOCKED: data/ files cannot be committed`, you have accidentally staged a DB or backup file. Run `git reset HEAD data/` to unstage and try again.
