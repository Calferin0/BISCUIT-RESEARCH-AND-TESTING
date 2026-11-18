"""Agent profiles (#8): look, rank, activity and collection, with blind rating (D10) intact."""
from app import db as brtdb

from .conftest import scores


def _agent(app, name):
    with app.app_context():
        token = brtdb.add_member(name, "🦊")
        return token, brtdb.member_by_token(token)["id"]


def _report(app, member_id, biscuit_id, comment):
    with app.app_context():
        brtdb.upsert_rating(member_id, biscuit_id, {k: int(v) for k, v in scores(5).items()}, comment, [])


def test_profile_shows_activity_and_rank(app, client, agent_token, biscuit_id):
    _, dee = _agent(app, "Dee")
    _report(app, dee, biscuit_id, "Dee's verdict")
    page = client.get(f"/agent/{dee}").data.decode()
    assert "Agent Dee" in page and "Rank:" in page and "field reports" in page
    assert "Hobnob" in page


def test_sealed_reports_hide_score_and_notes(app, client, agent_token, biscuit_id):
    _, dee = _agent(app, "Dee")
    _report(app, dee, biscuit_id, "SECRET-NOTES about this biscuit")
    page = client.get(f"/agent/{dee}").data.decode()           # Tester hasn't filed: sealed
    assert "SECRET-NOTES" not in page and "5.0" not in page and "sealed until you file" in page

    client.post(f"/b/{biscuit_id}/rate", data=scores(3))       # now Tester has filed
    page = client.get(f"/agent/{dee}").data.decode()
    assert "SECRET-NOTES" in page and "5.0" in page


def test_balance_stays_private(app, client, agent_token):
    _, dee = _agent(app, "Dee")
    page = client.get(f"/agent/{dee}").data.decode()
    assert "🪙" not in page.split("<main", 1)[1]                # the header pill is mine, not theirs


def test_names_link_to_profiles(app, client, agent_token, biscuit_id):
    _, dee = _agent(app, "Dee")
    _report(app, dee, biscuit_id, "Linked up")
    client.post(f"/b/{biscuit_id}/rate", data=scores(3))
    assert f'href="/agent/{dee}"' in client.get(f"/b/{biscuit_id}").data.decode()
    assert f'href="/agent/{dee}"' in client.get("/leaderboard").data.decode()


def test_unknown_or_retired_agent_is_404(app, client, agent_token):
    assert client.get("/agent/9999").status_code == 404


def test_profiles_need_an_agent(app, client):
    assert client.get("/agent/1").status_code == 403
