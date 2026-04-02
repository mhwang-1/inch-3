# CLAUDE.md — Inch 3

Development and session guidance for Claude Code operating in this repository.

## What is Inch 3?

Inch 3 is a personal language learning assistant operated entirely through Claude Code. There is no web UI and no separate server process. Study sessions run via Telegram (for TTS audio delivery and user responses). Claude Code skills orchestrate the sessions: generating TTS audio, calling the Telegram Bot API, running polling scripts to collect user responses, and writing session state to the SQLite database.

## Directory Structure

```
inch-3/
├── CLAUDE.md                          ← This file. Read at every session start.
├── TABLES.md                          ← Database schema reference. Read before querying DB.
├── README.md                          ← Human-readable overview.
├── .gitignore                         ← Excludes data/, secrets, OS files.
├── .claude/
│   └── commands/                      ← Skill files (slash commands for Claude Code).
│       ├── inch-import-books.md
│       ├── inch-setup-new-language-profile.md
│       ├── inch-connect-telegram.md
│       ├── inch-continue.md
│       └── inch-switch-language-profile.md
├── .claude-memory/                    ← Session notes and scratch space (committed).
├── knowledge/                         ← User learning preferences and language tips.
│   ├── preferences.md                 ← Study preferences, TTS speeds, L1 settings.
│   ├── chunking-strategy.md           ← Canonical block-generation rules (NP/VP patterns).
│   ├── {lang_code}.md                 ← Per-language grammar + chunking reference (one per language).
│   └── tips/                          ← Language-specific resources and grammar notes.
├── scripts/                           ← Bash and Python utility scripts.
│   ├── backup-db.sh                   ← Daily DB backup; called at session start.
│   ├── tts-generate.sh                ← Call TTS API; credentials via env vars.
│   ├── tg-send-audio.sh               ← Send a local audio file to Telegram chat.
│   ├── tg-poll-response.sh            ← Poll Telegram getUpdates for next user message.
│   └── tg-send-text.sh                ← Send a text message to Telegram chat.
└── data/                              ← Runtime data. NEVER committed to git.
    ├── inch-3.db                      ← SQLite database (all study data, API configs).
    ├── inch-3.db-wal                  ← SQLite WAL journal.
    ├── inch-3.db-shm                  ← SQLite shared memory.
    └── inch-3_YYYYMMDD_HHmmss.db     ← Daily backups (rolling 10-day max).
```

## Session Startup Checklist

**At the start of EVERY Claude Code session, perform these steps immediately:**

1. Verify `data/inch-3.db` exists. If missing, inform the user and stop — do not proceed.
2. Run the backup script. If no backup exists for today, it will create one:
   ```bash
   bash scripts/backup-db.sh
   ```
3. Confirm the backup completed successfully before doing anything else.

## Skill Commands

| Command | Description |
|---|---|
| `/inch-import-books` | Import a book (epub/pdf/jpg-folder/text) into the DB, split into chapters and sentences. |
| `/inch-setup-new-language-profile` | Create a language profile with TTS endpoint, API key, and voice. Tests the API before saving. |
| `/inch-connect-telegram` | Guide Telegram bot setup (BotFather), validate the token, detect chat_id, store config. |
| `/inch-generate-blocks` | Pre-generate sentence blocks for the next 10 unstudied sentences. Uses chunking knowledge files. Auto-triggered by `/inch-continue` when blocks are missing. |
| `/inch-continue` | Resume or start a study session. Delivers TTS audio via Telegram, handles user responses (slower/ok/confused/explain), 10 sentences per session. |
| `/inch-switch-language-profile` | Switch active language; show optional stats; trigger setup for unknown languages. |

## Architecture Notes

### How Study Sessions Work

`/inch-continue` is a Claude Code skill. It does NOT run as a background daemon. Instead:
1. Claude Code generates TTS audio by calling the configured TTS API endpoint.
2. Claude Code sends the audio to Telegram using `scripts/tg-send-audio.sh`.
3. Claude Code waits for the user's response by running `scripts/tg-poll-response.sh` (which polls `getUpdates` with a timeout).
4. Claude Code parses the response and continues.
5. After 10 sentences, the session ends. The user must run `/inch-continue` again for a new session.

This means each `/inch-continue` invocation holds a Claude Code session open for the duration (typically 30–60 minutes). This is intentional.

### Python Scripts

All Python scripts use `uv run` with PEP 723 inline script dependencies (`# /// script` block). Do not create `requirements.txt` or `pyproject.toml` for scripts.

### Bash Scripts

All bash scripts start with `set -euo pipefail`.

## Key Rules

- **`data/` is local-only.** Never commit anything under `data/` to git. There is a pre-commit hook enforcing this.
- **Database is authoritative.** All persistent state lives in `data/inch-3.db`.
- **API keys are stored in the database.** Both the Telegram bot token (`telegram_config.bot_token`) and TTS API keys (`language_profiles.tts_api_key`) are stored directly in `data/inch-3.db`. The `data/` directory is local-only and never committed to git. Do not log or print key values.
- **knowledge/ IS committed.** Notes, preferences, and tips are plain text and belong in git.
- **One backup per day.** The backup script is idempotent — skips if today's backup exists.
- **Rolling 10-day backup limit.** The oldest backup is deleted when a new one is created and the total exceeds 10.
- **Block collapsing is always presentation-time.** The full block list is always stored in the DB. Familiarity-based collapsing happens when iterating blocks in the study loop, not when generating blocks.
- **Per-language preference files.** When `/inch-setup-new-language-profile` is run, it generates `knowledge/{lang_code}.md` by dispatching a research agent to study the target language's grammar, then two review agents (grammar accuracy + chunking applicability), then revising. This file is committed to git. `/inch-continue` consults it alongside `knowledge/chunking-strategy.md` when generating blocks. If study sessions show persistent confusion (>30% confused rate for 3+ sessions), re-run `/inch-setup-new-language-profile` and choose to regenerate the language preference doc.
