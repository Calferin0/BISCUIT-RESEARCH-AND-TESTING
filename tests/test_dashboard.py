"""Dashboard: drop validation and timeline, add/edit flow, tastings, scouting (Open Food Facts mocked)."""
import random
from datetime import date

import pytest

from app import db as brtdb
from app import drops, images, recommend

from .conftest import count, scores

TODAY = date(2026, 11, 5)
OFF_IMG = "https://images.openfoodfacts.org/images/products/1/front_en.400.jpg"


def drop(name, starts=None, ends=None, kind="limited"):
    return {"id": 1, "name": name, "brand": "", "kind": kind, "starts_on": starts, "ends_on": ends}


# --- pure: validation + timeline -------------------------------------------------------

def test_timeline_buckets():
    t = drops.timeline([
        drop("Past", "2026-10-01", "2026-10-31"),
        drop("Soon", "2026-12-01"),
        drop("Rumour"),
        drop("Ending", "2026-10-20", "2026-11-12"),
        drop("Open-ended", "2026-10-20"),
        drop("Ends far off", None, "2027-01-31"),
    ], TODAY)
    names = {k: [d["name"] for d in v] for k, v in t.items()}
    assert names == {"gone": ["Past"], "soon": ["Soon"], "tbc": ["Rumour"],
                     "last_chance": ["Ending"], "now": ["Open-ended", "Ends far off"]}


@pytest.mark.parametrize("starts, ends, expected", [
    ("2026-11-06", None, "lands tomorrow"),
    ("2026-11-15", None, "lands in 10 days"),
    (None, "2026-11-05", "last day today!"),
    (None, "2026-11-08", "3 days left"),
    ("2026-10-01", "2026-11-04", "gone 1 day ago"),
    ("2026-11-05", None, "out now"),
    (None, None, "date TBC"),
])
def test_countdown(starts, ends, expected):
    assert drops.countdown(drop("x", starts, ends), TODAY) == expected


@pytest.mark.parametrize("form, message", [
    ({"name": ""}, "needs a biscuit name"),
    ({"name": "X", "starts_on": "2026-13-01"}, "isn't a valid date"),
    ({"name": "X", "starts_on": "2026-12-01", "ends_on": "2026-11-01"}, "before the start"),
    ({"name": "X", "source_url": "javascript:alert(1)"}, "http"),
])
def test_clean_rejects(form, message):
    with pytest.raises(drops.DropError, match=message):
        drops.clean(form)


def test_clean_normalises():
    v = drops.clean({"name": " Gingerbread Digestive ", "kind": "nonsense", "starts_on": "2026-11-01"})
    assert v["name"] == "Gingerbread Digestive" and v["kind"] == "limited" and v["ends_on"] is None


# --- pure: recommendations -------------------------------------------------------------

def test_next_tastings_prefers_liked_brand_and_skips_rated():
    biscuits = [{"id": 1, "name": "Hobnob", "brand": "McVitie's", "n": 1},
                {"id": 2, "name": "Digestive", "brand": "McVitie's", "n": 0},
                {"id": 3, "name": "Bourbon", "brand": "Tesco", "n": 0}]
    seen = {recommend.next_tastings(biscuits, {1: 5.0}, random.Random(i), k=1)[0]["id"] for i in range(40)}
    assert 1 not in seen and seen <= {2, 3}
    picks = recommend.next_tastings(biscuits, {1: 5.0}, random.Random(0), k=3)
    assert {p["id"] for p in picks} == {2, 3}
    assert next(p for p in picks if p["id"] == 2)["reason"] == "You've liked McVitie's before"


def test_brand_tags_are_query_safe():
    assert recommend.brand_tags("McVitie's") == ["mcvitie-s", "mcvities"]
    assert recommend.brand_tags('Evil" OR x') == ["evil-or-x"]


def test_team_brands_cold_start():
    assert recommend.team_brands([]) == list(recommend.DEFAULT_BRANDS[:3])


def test_scouting_skips_logged_and_duplicates(monkeypatch):
    recommend.clear_cache()
    hits = [{"product_name": "Hobnobs", "brands": ["McVitie's"], "image_front_url": OFF_IMG},
            {"product_name": "Ginger Nuts", "brands": ["McVitie's"], "image_front_url": OFF_IMG},
            {"product_name": "Ginger nuts", "brands": ["McVitie's"], "image_front_url": OFF_IMG},
            {"product_name": "No photo", "brands": [], "image_front_url": "http://evil.example/x.jpg"}]
    monkeypatch.setattr(images, "get_json", lambda url: {"hits": hits})
    logged = [{"id": 1, "name": "Hobnob", "brand": "McVitie's"}]
    got = recommend.scouting(["McVitie's"], logged, random.Random(1))
    assert [g["name"] for g in got] == ["Ginger Nuts"]


# --- routes ----------------------------------------------------------------------------

def test_add_and_edit_drop(app, client, agent_token):
    client.post("/drops/new", data={"name": "Gingerbread Digestive", "brand": "McVitie's", "kind": "seasonal",
                                    "starts_on": "2020-11-01", "ends_on": "2099-01-05", "shops": "Tesco"})
    assert count(app, "SELECT COUNT(*) FROM drops WHERE kind = 'seasonal'") == 1
    page = client.get("/dashboard").data.decode()
    assert "Gingerbread Digestive" in page and "On shelves now" in page and "Tesco" in page
    client.post("/drops/1/edit", data={"name": "Gingerbread Digestive", "kind": "seasonal", "shops": "Asda"})
    with app.app_context():
        assert brtdb.get_drop(1)["shops"] == "Asda"


def test_bad_drop_is_rerendered_not_saved(app, client, agent_token):
    resp = client.post("/drops/new", data={"name": "X", "source_url": "javascript:alert(1)"})
    assert resp.status_code == 400 and count(app, "SELECT COUNT(*) FROM drops") == 0


def test_logged_drop_is_a_chip_not_a_duplicate_card(app, client, agent_token, biscuit_id):
    client.post("/drops/new", data={"name": "Hobnobs", "brand": "McVitie's"})
    client.get("/dashboard")  # consume the flash
    page = client.get("/dashboard").data.decode()
    assert "already in your case files" in page and f'href="/b/{biscuit_id}"' in page
    assert 'class="drop-card' not in page                      # no separate drop card


def test_auto_link_by_contained_words(app, client, agent_token):
    with app.app_context():
        bid = brtdb.add_biscuit("Gingerbread Digestive", "", None, None)
        brtdb.add_biscuit("Digestive", "", None, None)              # one word: must not swallow drops
    client.post("/drops/new", data={"name": "Gingerbread Flavour Milk Chocolate Digestives", "brand": "McVitie's"})
    client.post("/drops/new", data={"name": "Digestives Jaffa Cakes flavour", "brand": "McVitie's"})
    client.get("/dashboard")
    page = client.get("/dashboard").data.decode()
    assert f'href="/b/{bid}"' in page                              # gingerbread linked, shown as chip
    assert "Digestives Jaffa Cakes flavour" in page                # jaffa stays a normal drop card


def test_explicit_link_and_shelf_badge(app, client, agent_token, biscuit_id):
    client.post("/drops/new", data={"name": "Totally Different Name", "biscuit_id": str(biscuit_id),
                                    "starts_on": "2020-01-01"})
    client.get("/")
    assert "on shelves now" in client.get("/").data.decode()
    resp = client.post("/drops/new", data={"name": "X", "biscuit_id": "999"})
    assert resp.status_code == 400


def test_dashboard_shows_tastings_without_scores(app, client, agent_token, biscuit_id):
    with app.app_context():
        other = brtdb.add_member("Other", "🦊")
    c2 = app.test_client()
    c2.get(f"/join/{other}")
    c2.post(f"/b/{biscuit_id}/rate", data={**scores(5), "comment": "SECRET-NOTE"})
    page = client.get("/dashboard").data.decode()
    assert "Your next tasting" in page and "Hobnob" in page
    assert "SECRET-NOTE" not in page and "5.0" not in page


def test_hidden_drop_disappears(app, client, agent_token):
    client.post("/drops/new", data={"name": "Mystery Bar"})
    client.post("/admin/drops/1/toggle")
    assert "Mystery Bar" not in client.get("/dashboard").data.decode()
    assert client.get("/drops/1/edit").status_code == 404


def test_scouting_api(app, client, agent_token, monkeypatch):
    monkeypatch.setattr(recommend, "scouting", lambda brands, logged, rng: [
        {"name": "Ginger Nuts", "brand": "McVitie's", "image": OFF_IMG, "thumb": OFF_IMG, "reason": "x"}])
    item = client.get("/api/scouting").get_json()["items"][0]
    assert item["thumb_url"].startswith("/thumb?u=") and "name=Ginger" in item["log_url"]

    def offline(*a):
        raise images.PhotoError("offline")
    monkeypatch.setattr(recommend, "scouting", offline)
    resp = client.get("/api/scouting")
    assert resp.status_code == 502 and resp.get_json()["items"] == []


def test_add_form_prefills_from_query(client, agent_token):
    page = client.get("/add?name=Ginger+Nuts&brand=McVitie%27s").data.decode()
    assert 'value="Ginger Nuts"' in page and "McVitie&#39;s" in page
