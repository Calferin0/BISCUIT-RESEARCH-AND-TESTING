import sqlite3

from app import create_app
from app import db as brtdb
from app.scoring import CATEGORIES, CATEGORY_KEYS, verdict

from .conftest import count, scores


def test_ten_categories_in_requested_order():
    assert [c.label for c in CATEGORIES] == [
        "Mouthfeel", "Moreishness", "Taste", "Presentation", "Snap", "Excitement / Anticipation",
        "Dunkability 1: Better with dunk?", "Dunkability 2: Dunk time / resistance",
        "Affordability", "Sniff test",
    ]


def test_unknown_visitor_is_denied(client):
    resp = client.get("/")
    assert resp.status_code == 403
    assert b"not cleared for biscuits" in resp.data


def test_bad_join_token_is_404(client):
    assert client.get("/join/not-a-real-token").status_code == 404


def test_join_link_signs_agent_in(client, agent_token):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Agent Tester" in resp.data


def test_one_rating_per_member(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data={**scores(2), "comment": "meh"})
    client.post(f"/b/{biscuit_id}/rate", data={**scores(5), "comment": "changed my mind"})

    assert count(app, "SELECT COUNT(*) FROM ratings") == 1
    assert count(app, "SELECT COUNT(*) FROM scores") == len(CATEGORY_KEYS)
    assert count(app, "SELECT COUNT(*) FROM scores WHERE value = 5") == len(CATEGORY_KEYS)
    with app.app_context():
        mine = brtdb.get_rating(1, biscuit_id)
    assert mine["comment"] == "changed my mind"
    assert mine["scores"] == {k: 5 for k in CATEGORY_KEYS}


def test_biscuit_page_shows_all_categories(client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data=scores(4))
    page = client.get(f"/b/{biscuit_id}").data.decode()
    for c in CATEGORIES:
        assert c.label in page


def test_out_of_range_score_is_rejected(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data={**scores(3), CATEGORY_KEYS[0]: "6"})
    assert count(app, "SELECT COUNT(*) FROM ratings") == 0


def test_missing_category_is_rejected(app, client, agent_token, biscuit_id):
    partial = scores(3)
    del partial[CATEGORY_KEYS[-1]]
    client.post(f"/b/{biscuit_id}/rate", data=partial)
    assert count(app, "SELECT COUNT(*) FROM ratings") == 0


def test_retired_member_is_locked_out(app, client, agent_token):
    with app.app_context():
        brtdb.toggle_member(brtdb.member_by_token(agent_token)["id"])
    assert client.get("/").status_code == 403


def test_leaderboard_ranks_by_overall(app, client, agent_token, biscuit_id):
    with app.app_context():
        other = brtdb.add_biscuit("Rich Tea", "", None, None)
    client.post(f"/b/{biscuit_id}/rate", data=scores(4))
    client.post(f"/b/{other}/rate", data=scores(2))
    with app.app_context():
        assert [r["name"] for r in brtdb.leaderboard()] == ["Hobnob", "Rich Tea"]
    page = client.get("/leaderboard").data.decode()
    assert "Biscuit leaderboard" in page and "Agent leaderboard" in page


def test_verdict_boundaries():
    assert verdict(None) is None
    assert verdict(5.0).tone == "good"
    assert verdict(3.5).tone == "good"
    assert verdict(3.49).tone == "meh"
    assert verdict(1.0).tone == "bad"


V1_SCHEMA = """
CREATE TABLE members (id INTEGER PRIMARY KEY, name TEXT NOT NULL, avatar TEXT NOT NULL DEFAULT '🍪',
    token TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE biscuits (id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL DEFAULT '', image TEXT,
    added_by INTEGER REFERENCES members(id), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE ratings (id INTEGER PRIMARY KEY, member_id INTEGER NOT NULL, biscuit_id INTEGER NOT NULL,
    dunk INTEGER NOT NULL, crunch INTEGER NOT NULL, flavour INTEGER NOT NULL, crumb INTEGER NOT NULL, client INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE (member_id, biscuit_id));
INSERT INTO members (name, token) VALUES ('Old', 'oldtoken');
INSERT INTO biscuits (name) VALUES ('Legacy Bourbon');
INSERT INTO ratings (member_id, biscuit_id, dunk, crunch, flavour, crumb, client) VALUES (1, 1, 5, 4, 3, 2, 1);
PRAGMA user_version = 1;
"""


def test_v1_database_migrates_without_losing_data(tmp_path):
    db_path = tmp_path / "brt.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(V1_SCHEMA)
    conn.close()

    app = create_app({"DATA_DIR": tmp_path})

    assert (tmp_path / "brt.v1-backup.sqlite3").exists()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == brtdb.SCHEMA_VERSION
        assert conn.execute("SELECT dunk FROM ratings_v1").fetchone()[0] == 5  # parked, not deleted
        assert conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 0
    finally:
        conn.close()

    # Members and biscuits carry over and the app works on the migrated file.
    client = app.test_client()
    client.get("/join/oldtoken")
    assert b"Legacy Bourbon" in client.get("/").data
    client.post("/b/1/rate", data=scores(4))
    assert count(app, "SELECT COUNT(*) FROM ratings") == 1
