"""Adding biscuits: duplicate-name checks, photos (upload / Open Food Facts / URL) and photo dedupe."""
from io import BytesIO

import pytest

from app import db as brtdb
from app import images
from app.similarity import find_matches, normalise

from .conftest import JPG, PNG, count

OFF_URL = "https://images.openfoodfacts.org/images/products/500/front_en.400.jpg"


def names(app):
    with app.app_context():
        return [r["name"] for r in brtdb.get_db().execute("SELECT name FROM biscuits ORDER BY id")]


# --- similarity (pure) ------------------------------------------------------------------

@pytest.mark.parametrize("a, b", [
    ("Custard Creams", "custard cream"),
    ("McVitie's Hobnobs", "mcvities hobnob"),
    ("Jaffa Cakes", "Jaffa cake"),
    ("Rich Tea Biscuits", "rich tea"),
])
def test_normalise_treats_these_as_identical(a, b):
    assert normalise(a) == normalise(b)


def test_find_matches_tiers():
    rows = [{"id": 1, "name": "Hobnob", "brand": "McVitie's"},
            {"id": 2, "name": "Bourbon", "brand": ""},
            {"id": 3, "name": "Fig Roll", "brand": ""}]
    exact = find_matches("Hobnobs", "", rows)
    assert exact[0].id == 1 and exact[0].exact
    near = find_matches("Chocolate Hobnob", "", rows)
    assert [m.id for m in near] == [1] and not near[0].exact
    typo = find_matches("Bourbonn", "", rows)
    assert typo and typo[0].id == 2
    assert find_matches("Garibaldi", "", rows) == []
    # Same name, clearly different brand: a different specimen, so confirm rather than block.
    own_brand = find_matches("Hobnob", "Tesco", rows)
    assert own_brand and not own_brand[0].exact


# --- add flow ---------------------------------------------------------------------------

def test_exact_duplicate_is_blocked(app, client, agent_token, biscuit_id):
    resp = client.post("/add", data={"name": "HOBNOBS", "confirm_new": "1"})
    assert resp.status_code == 409
    assert names(app) == ["Hobnob"]


def test_similar_name_needs_confirmation(app, client, agent_token, biscuit_id):
    resp = client.post("/add", data={"name": "Chocolate Hobnob"})
    assert b"Already on file?" in resp.data
    assert names(app) == ["Hobnob"]

    client.post("/add", data={"name": "Chocolate Hobnob", "confirm_new": "1"})
    assert names(app) == ["Hobnob", "Chocolate Hobnob"]


def test_similar_api(client, agent_token, biscuit_id):
    data = client.get("/api/similar?name=hobnobs").get_json()
    assert data["matches"][0]["name"] == "Hobnob" and data["matches"][0]["exact"]
    assert client.get("/api/similar?name=xyzzy").get_json() == {"matches": []}


def test_upload_checks_magic_bytes_not_extension(app, client, agent_token):
    client.post("/add", data={"name": "Fake", "photo": (BytesIO(b"<svg onload=alert(1)>"), "fake.jpg")},
                content_type="multipart/form-data")
    assert names(app) == []
    client.post("/add", data={"name": "Real", "photo": (BytesIO(PNG), "whatever.bin")},
                content_type="multipart/form-data")
    assert names(app) == ["Real"]
    with app.app_context():
        b = brtdb.get_db().execute("SELECT image, image_hash, image_source FROM biscuits").fetchone()
    assert b["image"].endswith(".png") and b["image_source"] == "upload" and len(b["image_hash"]) == 64


def test_same_photo_twice_is_rejected(app, client, agent_token):
    client.post("/add", data={"name": "Bourbon", "photo": (BytesIO(PNG), "a.png")}, content_type="multipart/form-data")
    resp = client.post("/add", data={"name": "Garibaldi", "photo": (BytesIO(PNG), "b.png")},
                       content_type="multipart/form-data")
    assert "already on file for “Bourbon”" in resp.data.decode()
    assert names(app) == ["Bourbon"]


def test_open_food_facts_pick(app, client, agent_token, monkeypatch):
    fetched = []
    monkeypatch.setattr(images, "_http_get", lambda url: fetched.append(url) or JPG)
    client.post("/add", data={"name": "Digestive", "web_image": OFF_URL})
    assert fetched == [OFF_URL]
    assert count(app, "SELECT COUNT(*) FROM biscuits WHERE image_source = 'Open Food Facts'") == 1


def test_agents_cannot_make_server_fetch_arbitrary_urls(app, client, agent_token, monkeypatch):
    monkeypatch.setattr(images, "_http_get", lambda url: pytest.fail("must not fetch"))
    client.post("/add", data={"name": "Sneaky", "web_image": "http://192.168.1.1/admin"})
    client.post("/add", data={"name": "Sneaky", "image_url": "http://example.com/x.jpg"})
    assert names(app) == []


def test_image_search_api(client, agent_token, monkeypatch):
    monkeypatch.setattr(images, "search_off", lambda q: [{"name": q, "brand": "", "image": OFF_URL, "thumb": OFF_URL}])
    assert client.get("/api/image-search?q=hobnob").get_json()["results"][0]["name"] == "hobnob"

    def offline(q):
        raise images.PhotoError("Couldn't fetch")
    monkeypatch.setattr(images, "search_off", offline)
    resp = client.get("/api/image-search?q=hobnob")
    assert resp.status_code == 502 and "error" in resp.get_json()


def test_search_off_falls_back_and_parses_both_shapes(monkeypatch):
    new_api = {"hits": [{"product_name": "Hobnobs", "brands": ["McVitie's"], "image_front_url": OFF_URL}]}
    legacy = {"products": [{"product_name": "Hobnobs", "brands": "McVitie's, Pladis", "image_front_url": OFF_URL}]}
    import json

    def flaky_new(url):
        if "search.openfoodfacts.org" in url:
            raise images.PhotoError("busy")
        return json.dumps(legacy).encode()
    monkeypatch.setattr(images, "_http_get", flaky_new)
    assert images.search_off("hobnob")[0]["brand"] == "McVitie's"

    monkeypatch.setattr(images, "_http_get", lambda url: json.dumps(new_api).encode())
    got = images.search_off("hobnob")
    assert got == [{"name": "Hobnobs", "brand": "McVitie's", "image": OFF_URL, "thumb": OFF_URL}]


def test_thumb_relay_only_serves_off_images(client, monkeypatch):
    monkeypatch.setattr(images, "_http_get", lambda url: JPG)
    resp = client.get(f"/thumb?u={OFF_URL}")
    assert resp.status_code == 200 and resp.mimetype == "image/jpeg"
    assert client.get("/thumb?u=http://192.168.1.1/secret").status_code == 404


# --- photo on an existing biscuit -------------------------------------------------------

def test_agent_can_add_missing_photo_but_not_replace(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/photo", data={"photo": (BytesIO(PNG), "a.png")}, content_type="multipart/form-data")
    with app.app_context():
        first = brtdb.get_biscuit(biscuit_id)["image"]
    assert first

    client.post(f"/b/{biscuit_id}/photo", data={"photo": (BytesIO(JPG), "b.jpg")}, content_type="multipart/form-data")
    with app.app_context():
        assert brtdb.get_biscuit(biscuit_id)["image"] == first


def test_admin_can_replace_and_paste_url(app, client, biscuit_id, monkeypatch):
    client.post(f"/admin/biscuits/{biscuit_id}/photo", data={"photo": (BytesIO(PNG), "a.png")},
                content_type="multipart/form-data")
    monkeypatch.setattr(images, "_http_get", lambda url: JPG)
    client.post(f"/admin/biscuits/{biscuit_id}/photo", data={"image_url": "https://example.com/hobnob.jpg"})
    with app.app_context():
        b = brtdb.get_biscuit(biscuit_id)
    assert b["image"].endswith(".jpg") and b["image_source"] == "https://example.com/hobnob.jpg"
    assert client.get(f"/admin/biscuits/{biscuit_id}/photo").status_code == 200
