"""Case lifecycle (public after a week, closed cases, reopen requests) and field-note thumbs-up."""
from datetime import date

import pytest

from app import cases
from app import db as brtdb

from .conftest import count, scores


@pytest.fixture
def other(app):
    """A second agent on their own client."""
    with app.app_context():
        token = brtdb.add_member("Other", "🦊")
    c = app.test_client()
    c.get(f"/join/{token}")
    return c


def age_biscuit(app, biscuit_id, days):
    with app.app_context():
        conn = brtdb.get_db()
        conn.execute("UPDATE biscuits SET created_at = datetime('now', ?) WHERE id = ?", (f"-{days} days", biscuit_id))
        conn.commit()


def rating_id(app, member_name):
    with app.app_context():
        return brtdb.get_db().execute(
            "SELECT r.id FROM ratings r JOIN members m ON m.id = r.member_id WHERE m.name = ?", (member_name,)
        ).fetchone()[0]


# --- pure ------------------------------------------------------------------------------

def test_public_after_a_week_or_when_closed():
    b = {"created_at": "2026-11-01 09:00:00", "case_status": "open"}
    assert cases.unseals_on(b) == date(2026, 11, 8)
    assert not cases.is_public(b, date(2026, 11, 7))
    assert cases.is_public(b, date(2026, 11, 8))
    assert cases.is_public({**b, "case_status": "closed"}, date(2026, 11, 2))
    assert cases.can_see(b, True, date(2026, 11, 2))


# --- public after a week ---------------------------------------------------------------

def test_case_unseals_for_everyone_after_a_week(app, client, agent_token, biscuit_id, other):
    other.post(f"/b/{biscuit_id}/rate", data={**scores(5), "comment": "WEEK-OLD-NOTE"})
    page = client.get(f"/b/{biscuit_id}").data.decode()
    assert "WEEK-OLD-NOTE" not in page and "goes public for everyone on" in page

    age_biscuit(app, biscuit_id, 8)
    page = client.get(f"/b/{biscuit_id}").data.decode()
    assert "WEEK-OLD-NOTE" in page and "Results stay sealed" not in page
    assert "?.?" not in client.get("/leaderboard").data.decode()


# --- closed cases + reopen requests ----------------------------------------------------

def test_closed_case_stops_reports_and_goes_public(app, client, agent_token, biscuit_id, other):
    other.post(f"/b/{biscuit_id}/rate", data={**scores(4), "comment": "BEFORE-CLOSE"})
    client.post(f"/admin/biscuits/{biscuit_id}/case", data={"action": "close"})

    page = client.get(f"/b/{biscuit_id}").data.decode()
    assert "This case is closed" in page and "BEFORE-CLOSE" in page and "data-rate-form" not in page
    client.post(f"/b/{biscuit_id}/rate", data=scores(1))
    assert count(app, "SELECT COUNT(*) FROM ratings") == 1          # blocked
    assert "Case closed" in client.get("/").data.decode()


def test_reopen_request_flow(app, client, agent_token, biscuit_id):
    client.post(f"/admin/biscuits/{biscuit_id}/case", data={"action": "close"})
    client.post(f"/b/{biscuit_id}/reopen", data={"note": "Back at Tesco"})
    client.post(f"/b/{biscuit_id}/reopen", data={"note": "again"})  # duplicate ignored
    assert count(app, "SELECT COUNT(*) FROM reopen_requests WHERE status = 'pending'") == 1
    assert "Back at Tesco" in client.get("/admin/").data.decode()

    client.post(f"/admin/biscuits/{biscuit_id}/case", data={"action": "reopen"})
    assert count(app, "SELECT COUNT(*) FROM reopen_requests WHERE status = 'approved'") == 1
    assert count(app, "SELECT COUNT(*) FROM biscuits WHERE case_status = 'open' AND closed_at IS NULL") == 1
    client.post(f"/b/{biscuit_id}/rate", data=scores(3))
    assert count(app, "SELECT COUNT(*) FROM ratings") == 1          # reports work again


def test_decline_reopen_and_admin_only(app, client, agent_token, biscuit_id):
    client.post(f"/admin/biscuits/{biscuit_id}/case", data={"action": "close"})
    client.post(f"/b/{biscuit_id}/reopen", data={"note": ""})
    client.post("/admin/reopen-requests/1/decline")
    assert count(app, "SELECT COUNT(*) FROM reopen_requests WHERE status = 'declined'") == 1
    lan = {"REMOTE_ADDR": "192.168.1.50"}
    assert client.post(f"/admin/biscuits/{biscuit_id}/case", data={"action": "reopen"}, environ_base=lan).status_code == 403


# --- thumbs-up on field notes ----------------------------------------------------------

def test_thumbs_up_others_not_your_own(app, client, agent_token, biscuit_id, other):
    other.post(f"/b/{biscuit_id}/rate", data={**scores(4), "comment": "Crunchy as a gravel drive"})
    theirs = rating_id(app, "Other")

    assert client.post(f"/reports/{theirs}/thumb").status_code == 403   # sealed: can't see it yet
    client.post(f"/b/{biscuit_id}/rate", data=scores(3))
    client.post(f"/reports/{theirs}/thumb")
    assert count(app, "SELECT COUNT(*) FROM report_votes") == 1
    client.post(f"/reports/{theirs}/thumb")                              # toggle off
    assert count(app, "SELECT COUNT(*) FROM report_votes") == 0

    mine = rating_id(app, "Tester")
    client.post(f"/reports/{mine}/thumb")
    assert count(app, "SELECT COUNT(*) FROM report_votes") == 0          # own report refused
    assert client.post("/reports/999/thumb").status_code == 404


def test_v4_database_gets_case_columns(tmp_path):
    import sqlite3
    from app import create_app
    db_path = tmp_path / "brt.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE members (id INTEGER PRIMARY KEY, name TEXT NOT NULL, avatar TEXT NOT NULL DEFAULT 'x',
            token TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE biscuits (id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL DEFAULT '', image TEXT,
            image_hash TEXT, image_source TEXT, added_by INTEGER, active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO biscuits (name) VALUES ('Old Bourbon');
        PRAGMA user_version = 4;
    """)
    conn.close()
    create_app({"DATA_DIR": tmp_path})
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT case_status, closed_at FROM biscuits").fetchone() == ("open", None)
        assert (tmp_path / "brt.v4-backup.sqlite3").exists()
    finally:
        conn.close()
    create_app({"DATA_DIR": tmp_path})  # idempotent: a second start doesn't try to re-add columns
