"""Blind rating (results sealed until you've filed) and live presence for the control room."""
import pytest

from app import db as brtdb
from app.presence import Presence

from .conftest import scores


@pytest.fixture
def other_agent(app):
    """A second agent, already rated the Hobnob, on their own client (own cookie jar)."""
    with app.app_context():
        token = brtdb.add_member("Other", "🦊")
    c = app.test_client()
    c.get(f"/join/{token}")
    return c


def test_results_sealed_until_you_file(app, client, agent_token, biscuit_id, other_agent):
    other_agent.post(f"/b/{biscuit_id}/rate", data={**scores(5), "comment": "SECRET-NOTE-123"})

    before = client.get(f"/b/{biscuit_id}").data.decode()
    assert "Results stay sealed" in before
    assert "SECRET-NOTE-123" not in before          # not just hidden: never sent
    assert "Locked off" not in before                # verdict line for a 5.0
    assert "🔒 1 report" in client.get("/").data.decode()

    client.post(f"/b/{biscuit_id}/rate", data=scores(1))
    after = client.get(f"/b/{biscuit_id}").data.decode()
    assert "SECRET-NOTE-123" in after and "Results stay sealed" not in after


def test_leaderboard_shows_name_but_seals_score(app, client, agent_token, biscuit_id, other_agent):
    """Case lifecycle rule: names and places are public, scores sealed until you file."""
    other_agent.post(f"/b/{biscuit_id}/rate", data=scores(4))
    sealed = client.get("/leaderboard").data.decode()
    assert "Hobnob" in sealed and "?.?" in sealed and "🔒 sealed" in sealed
    assert "4.0" not in sealed

    open_view = other_agent.get("/leaderboard").data.decode()
    assert "4.0" in open_view and "?.?" not in open_view


def test_other_agents_soulmate_score_sealed_until_you_rate_it(app, client, agent_token, biscuit_id, other_agent):
    other_agent.post(f"/b/{biscuit_id}/rate", data=scores(5))
    page = client.get("/leaderboard").data.decode()
    assert "Soulmate" in page and "Hobnob" in page and "5.0" not in page

    client.post(f"/b/{biscuit_id}/rate", data=scores(2))
    page = client.get("/leaderboard").data.decode()
    assert "5.0" in page


def test_presence_tracks_page_views_and_editing(app, client, agent_token, biscuit_id):
    client.get(f"/b/{biscuit_id}")
    live = client.get("/admin/api/live").get_json()
    assert live["count"] == 1 and live["editing"] == 0
    assert live["agents"][0]["where"] == "Looking at Hobnob"

    client.post("/api/ping", json={"path": f"/b/{biscuit_id}", "editing": True})
    live = client.get("/admin/api/live").get_json()
    assert live["editing"] == 1
    assert client.get("/admin/live-count").data == b"1"


def test_ping_labels_come_from_server_not_client(client, agent_token):
    client.post("/api/ping", json={"path": "<script>alert(1)</script>"})
    assert client.get("/admin/api/live").get_json()["agents"][0]["where"] == "On BRT"


def test_presence_needs_agent_and_admin_needs_loopback(client):
    assert client.post("/api/ping", json={"path": "/"}).status_code == 403
    assert client.get("/admin/api/live", environ_base={"REMOTE_ADDR": "192.168.1.50"}).status_code == 403


def test_presence_expires(monkeypatch):
    import app.presence as presence_mod
    clock = [1000.0]
    monkeypatch.setattr(presence_mod.time, "monotonic", lambda: clock[0])
    p = Presence()
    p.touch({"id": 1, "name": "Ada", "avatar": "🦉"}, "Browsing specimens")
    assert len(p.live()) == 1
    clock[0] += presence_mod.LIVE_WINDOW_S + 1
    assert p.live() == []
