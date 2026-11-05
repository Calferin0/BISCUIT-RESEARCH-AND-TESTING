"""Suggestion box, +1 votes, admin triage, weekly export, WORKING ON IT page, v2 -> v3 migration."""
import json
import sqlite3

from app import create_app
from app import db as brtdb
from app.views import ROADMAP_FILE

from .conftest import count


def test_post_and_list_with_name(app, client, agent_token):
    client.post("/suggestions", data={"kind": "idea", "body": "Biscuit of the week banner"})
    page = client.get("/suggestions").data.decode()
    assert "Biscuit of the week banner" in page and "Agent Tester" in page
    assert count(app, "SELECT COUNT(*) FROM suggestions WHERE kind = 'idea' AND status = 'new'") == 1


def test_too_short_or_bad_kind(app, client, agent_token):
    client.post("/suggestions", data={"kind": "idea", "body": "hi"})
    assert count(app, "SELECT COUNT(*) FROM suggestions") == 0
    client.post("/suggestions", data={"kind": "<script>", "body": "Valid length body"})
    assert count(app, "SELECT kind = 'other' FROM suggestions") == 1


def test_vote_toggles(app, client, agent_token):
    client.post("/suggestions", data={"kind": "idea", "body": "Dunk timer"})
    client.post("/suggestions/1/vote")
    assert count(app, "SELECT COUNT(*) FROM suggestion_votes") == 1
    client.post("/suggestions/1/vote")
    assert count(app, "SELECT COUNT(*) FROM suggestion_votes") == 0
    assert client.post("/suggestions/99/vote").status_code == 404


def test_suggestions_need_an_agent(client):
    assert client.get("/suggestions").status_code == 403


def test_admin_triage_shows_on_working_page(app, client, agent_token):
    client.post("/suggestions", data={"kind": "idea", "body": "Dunk timer please"})
    client.post("/admin/suggestions/1", data={"status": "building", "response": "On it this week"})
    page = client.get("/working-on-it").data.decode()
    assert "Dunk timer please" in page and "On it this week" in page
    assert client.post("/admin/suggestions/1", data={"status": "nonsense"}).status_code == 400
    assert client.post("/admin/suggestions/1", data={"status": "shipped"},
                       environ_base={"REMOTE_ADDR": "192.168.1.50"}).status_code == 403


def test_working_on_it_renders_roadmap(client, agent_token):
    roadmap = json.loads(ROADMAP_FILE.read_text(encoding="utf-8"))
    page = client.get("/working-on-it").data.decode()
    for item in roadmap["roadmap"]:
        assert item["title"] in page


def test_roadmap_has_no_obvious_names():
    """Public repo: the roadmap must cite suggestions by #id, not by person."""
    import re
    text = ROADMAP_FILE.read_text(encoding="utf-8")
    assert not re.search(r"\bAgent [A-Z][a-z]+", text)   # "Agent Abi" style credits
    assert "@" not in text


def test_export_writes_open_suggestions(app, client, agent_token, tmp_path):
    client.post("/suggestions", data={"kind": "bug", "body": "Photo search slow"})
    client.post("/suggestions", data={"kind": "idea", "body": "Already done thing"})
    client.post("/admin/suggestions/2", data={"status": "shipped", "response": ""})
    result = app.test_cli_runner().invoke(args=["export-suggestions", "--out", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    files = list((tmp_path / "out").glob("*.md"))
    text = files[0].read_text(encoding="utf-8")
    assert "Photo search slow" in text and "From: Tester" in text
    assert "Already done thing" not in text


def test_v2_database_upgrades_to_v3_with_backup(tmp_path):
    db_path = tmp_path / "brt.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(brtdb.SCHEMA.split("-- v3:")[0])  # the v2 tables only
    conn.execute("INSERT INTO members (name, token) VALUES ('Old', 'tok')")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    create_app({"DATA_DIR": tmp_path})
    assert (tmp_path / "brt.v2-backup.sqlite3").exists()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == brtdb.SCHEMA_VERSION
        assert conn.execute("SELECT name FROM members").fetchone()[0] == "Old"
        conn.execute("SELECT COUNT(*) FROM suggestions").fetchone()
    finally:
        conn.close()
