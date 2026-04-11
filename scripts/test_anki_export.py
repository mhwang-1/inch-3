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


def test_sentence_filename():
    assert anki_export.sentence_filename("spa", 4521) == "inch3_spa_s4521_sentence.mp3"
    assert anki_export.sentence_filename("jpn", 17) == "inch3_jpn_s17_sentence.mp3"


def test_expression_filename():
    assert anki_export.expression_filename("spa", 128) == "inch3_spa_v128_expr.mp3"


def test_combo_filename():
    assert anki_export.combo_filename("spa", 128) == "inch3_spa_v128_combo.mp3"


def test_sound_tag():
    assert anki_export.sound_tag("inch3_spa_v128_expr.mp3") == "[sound:inch3_spa_v128_expr.mp3]"


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


_MIGRATION_PATH = Path(__file__).parent / "migrations" / "0001_anki_tables.sql"


@pytest.fixture
def memdb():
    """An in-memory SQLite DB seeded via the real migration script.

    Only FK-target tables (language_profiles, sentences, sentence_blocks) are
    hand-rolled; anki_config and anki_vocab_items come from the actual
    migration so the tests exercise the same schema production runs with.
    """
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
    """)
    conn.executescript(_MIGRATION_PATH.read_text())
    conn.executescript("""
        INSERT INTO language_profiles (id, lang_code, lang_name) VALUES (1, 'spa', 'Spanish');
        INSERT INTO sentences (id, l2_text, lang_profile_id)
            VALUES (10, 'Me da igual, vamos cuando quieras.', 1),
                   (11, 'No tengo ni idea.', 1);
        UPDATE anki_config SET host='127.0.0.1', port=8765, is_active=1 WHERE id=1;
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
