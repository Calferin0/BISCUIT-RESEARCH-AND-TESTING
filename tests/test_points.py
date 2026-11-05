"""Biscuit Points: computed from activity, shown in the header, on /points."""
from app import db as brtdb
from app import points

from .conftest import scores


def activity(**kw):
    base = {r.key: 0 for r in points.RULES}
    return {**base, **kw}


def test_total_and_ranks():
    a = activity(reports=3, notes=2, thumbs=4, specimens=1, drops=1, suggestions=2, shipped=1)
    assert points.total(a) == 3 * 10 + 2 * 3 + 4 * 5 + 15 + 5 + 2 * 2 + 10
    assert points.rank(0).endswith("Recruit") and points.rank(50).endswith("Junior Taster")
    assert points.next_rank(40) == ("🍪 Junior Taster", 10)
    assert points.next_rank(10_000) is None


def test_points_from_real_activity(app, client, agent_token, biscuit_id):
    with app.app_context():
        other = brtdb.add_member("Other", "🦊")
    c2 = app.test_client()
    c2.get(f"/join/{other}")
    # Tester: a report with proper notes; Other: a report that Tester thumbs-up.
    client.post(f"/b/{biscuit_id}/rate", data={**scores(4), "comment": "Structurally sound, emotionally devastating"})
    c2.post(f"/b/{biscuit_id}/rate", data={**scores(3), "comment": "ok"})
    with app.app_context():
        other_rating = brtdb.get_db().execute(
            "SELECT r.id FROM ratings r JOIN members m ON m.id = r.member_id WHERE m.name = 'Other'").fetchone()[0]
    client.post(f"/reports/{other_rating}/thumb")
    client.post("/suggestions", data={"kind": "idea", "body": "More biscuits please"})

    with app.app_context():
        rows = {r["name"]: points.total(r) for r in brtdb.points_activity()}
    assert rows["Tester"] == 10 + 3 + 2       # report + notes bonus + suggestion
    assert rows["Other"] == 10 + 5            # report ("ok" too short for notes) + 1 thumbs-up


def test_points_page_and_header(client, agent_token):
    page = client.get("/points").data.decode()
    assert "Biscuit Points" in page and "Points table" in page and "Agent Tester" in client.get("/").data.decode()
    assert "🪙 0" in client.get("/").data.decode()
