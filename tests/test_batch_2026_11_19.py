"""2026-11-19 batch: inbox newest first (#5), removed specimens stop counting (#11)."""
from app import db as brtdb

from .conftest import scores


def test_new_idea_lands_at_the_top_of_the_inbox(app, client, agent_token):
    """#5: a voted-on older idea must not push a brand-new one (0 votes) below it."""
    client.post("/suggestions", data={"kind": "idea", "body": "Older idea with a vote"})
    client.post("/suggestions/1/vote")
    client.post("/suggestions", data={"kind": "idea", "body": "Brand new idea"})
    page = client.get("/suggestions").data.decode()
    assert page.index("Brand new idea") < page.index("Older idea with a vote")


def test_non_inbox_still_ranked_by_votes(app, client, agent_token):
    client.post("/suggestions", data={"kind": "idea", "body": "Popular plan"})
    client.post("/suggestions", data={"kind": "idea", "body": "Quiet plan"})
    client.post("/suggestions/1/vote")
    for sid in (1, 2):
        client.post(f"/admin/suggestions/{sid}", data={"status": "planned", "response": ""})
    with app.app_context():
        bodies = [s["body"] for s in brtdb.list_suggestions(None, ("planned",))]
    assert bodies == ["Popular plan", "Quiet plan"]


def test_removed_specimen_stops_counting(app, client, agent_token, biscuit_id):
    """#11: a report on a removed specimen drops out of totals and points, and comes back
    if the specimen is restored (D6: nothing is deleted)."""
    with app.app_context():
        other = brtdb.add_member("Other", "🦊")
    c2 = app.test_client()
    c2.get(f"/join/{other}")
    client.post(f"/b/{biscuit_id}/rate", data={**scores(4), "comment": "Structurally sound, emotionally devastating"})
    c2.post(f"/b/{biscuit_id}/rate", data={**scores(3), "comment": "ok"})
    with app.app_context():
        mine = brtdb.get_db().execute(
            "SELECT r.id FROM ratings r JOIN members m ON m.id = r.member_id WHERE m.name = 'Tester'").fetchone()[0]
    c2.post(f"/reports/{mine}/thumb")

    def tester():
        with app.app_context():
            act = next(r for r in brtdb.points_activity() if r["name"] == "Tester")
            stat = next(r for r in brtdb.agent_stats() if r["name"] == "Tester")
            return act["reports"], act["notes"], act["thumbs"], stat["n"]

    assert tester() == (1, 1, 1, 1)
    with app.app_context():
        brtdb.toggle_biscuit(biscuit_id)          # admin removes the specimen
    assert tester() == (0, 0, 0, 0)
    with app.app_context():
        assert brtdb.get_db().execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 2  # kept
        brtdb.toggle_biscuit(biscuit_id)          # and restores it
    assert tester() == (1, 1, 1, 1)
