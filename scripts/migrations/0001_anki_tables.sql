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
