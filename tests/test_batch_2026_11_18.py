"""Weekly batch 2026-11-18: suggestions #2 (newest cases first), #6 (take back your own
suggestion) and #7 (rename a case you opened). #4 is CSS only."""
from app import db as brtdb

from .conftest import scores


def _member(app, name):
    """Another agent's member id (add_member hands back their join token)."""
    with app.app_context():
        return brtdb.member_by_token(brtdb.add_member(name, "🧪"))["id"]


def _biscuit(app, name, added_by=None):
    with app.app_context():
        return brtdb.add_biscuit(name, "", None, added_by)


def _me(app, token):
    with app.app_context():
        return brtdb.member_by_token(token)["id"]


# --- #2: newest case first, unfinished ones still at the front --------------------------

def test_cases_newest_first_with_unrated_at_front(app, client, agent_token):
    a = _biscuit(app, "Abernethy")
    z = _biscuit(app, "Zebra Crunch")
    m = _biscuit(app, "Malted Milk")
    client.post(f"/b/{m}/rate", data=scores(4))  # rated by me: goes after the unrated ones
    with app.app_context():
        order = [b["id"] for b in brtdb.list_biscuits(_me(app, agent_token))]
    assert order == [z, a, m]  # unrated newest-first, then mine


# --- #6: take back your own suggestion ---------------------------------------------------

def _suggest(app, member_id, body="A biscuit-of-the-week banner please"):
    with app.app_context():
        return brtdb.add_suggestion(member_id, "idea", body)


def test_author_can_delete_inbox_suggestion(app, client, agent_token):
    sid = _suggest(app, _me(app, agent_token))
    client.post(f"/suggestions/{sid}/vote")
    page = client.get("/suggestions").data.decode()
    assert f"/suggestions/{sid}/delete" in page
    client.post(f"/suggestions/{sid}/delete")
    with app.app_context():
        assert not brtdb.suggestion_exists(sid)


def test_cannot_delete_someone_elses_suggestion(app, client, agent_token):
    other = _suggest(app, _member(app, "Other"))
    assert f"/suggestions/{other}/delete" not in client.get("/suggestions").data.decode()
    client.post(f"/suggestions/{other}/delete")
    with app.app_context():
        assert brtdb.suggestion_exists(other)


def test_cannot_delete_once_planned(app, client, agent_token):
    sid = _suggest(app, _me(app, agent_token))
    with app.app_context():
        brtdb.set_suggestion_status(sid, "planned", "")
    assert f"/suggestions/{sid}/delete" not in client.get("/suggestions").data.decode()
    client.post(f"/suggestions/{sid}/delete")
    with app.app_context():
        assert brtdb.suggestion_exists(sid)  # roadmap.json may already cite its #id


# --- #7: rename a case you opened ---------------------------------------------------------

def test_opener_can_fix_the_name(app, client, agent_token):
    bid = _biscuit(app, "Jammy Dodgers", _me(app, agent_token))
    assert f"/b/{bid}/rename" in client.get(f"/b/{bid}").data.decode()
    client.post(f"/b/{bid}/rename", data={"name": "Jammie Dodgers", "brand": "Burton's"})
    with app.app_context():
        b = brtdb.get_biscuit(bid)
    assert (b["name"], b["brand"]) == ("Jammie Dodgers", "Burton's")


def test_only_the_opener_can_rename(app, client, agent_token):
    bid = _biscuit(app, "Jammy Dodgers", _member(app, "Other"))
    assert f"/b/{bid}/rename" not in client.get(f"/b/{bid}").data.decode()
    assert client.post(f"/b/{bid}/rename", data={"name": "Hacked"}).status_code == 403
    with app.app_context():
        assert brtdb.get_biscuit(bid)["name"] == "Jammy Dodgers"


def test_rename_cannot_duplicate_another_case(app, client, agent_token):
    _biscuit(app, "Bourbon")
    bid = _biscuit(app, "Burbon", _me(app, agent_token))
    client.post(f"/b/{bid}/rename", data={"name": "Bourbon", "brand": ""})
    with app.app_context():
        assert brtdb.get_biscuit(bid)["name"] == "Burbon"


def test_rename_keeps_the_rarity_pin(app, client, agent_token):
    bid = _biscuit(app, "Jammy Dodgers", _me(app, agent_token))
    with app.app_context():
        brtdb.update_biscuit(bid, "Jammy Dodgers", "", "legendary")
    client.post(f"/b/{bid}/rename", data={"name": "Jammie Dodgers", "brand": ""})
    with app.app_context():
        assert brtdb.get_biscuit(bid)["rarity_override"] == "legendary"
