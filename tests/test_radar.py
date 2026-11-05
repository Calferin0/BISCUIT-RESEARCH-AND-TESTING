"""Biscuit Radar: geometry, price parsing, centre config, OSM import, shops and prices (network mocked)."""
import pytest

from app import db as brtdb
from app import radar

from .conftest import count

YATE = (51.545955, -2.433436)


# --- pure --------------------------------------------------------------------------------

def test_distance_and_bearing():
    assert radar.distance_km(51.0, -2.0, 52.0, -2.0) == pytest.approx(111.19, abs=0.05)
    assert radar.bearing_deg(51.0, -2.0, 52.0, -2.0) == pytest.approx(0, abs=0.01)     # due north
    assert radar.bearing_deg(51.0, -2.0, 51.0, -1.9) == pytest.approx(90, abs=0.1)     # due east


def test_radar_xy_north_up_and_clamped():
    assert radar.radar_xy(5, 0) == (0.0, -140.0)        # outer ring, straight up
    assert radar.radar_xy(2.5, 90) == (70.0, 0.0)       # half way, due east
    assert radar.radar_xy(50, 180) == (0.0, 140.0)      # far away clamps to the edge


@pytest.mark.parametrize("raw, pence", [("£1.20", 120), ("1.2", 120), ("120p", 120), ("1", 100), ("0,89", 89)])
def test_parse_price(raw, pence):
    assert radar.parse_price(raw) == pence


@pytest.mark.parametrize("raw", ["", "free", "0", "£250"])
def test_parse_price_rejects(raw):
    with pytest.raises(radar.RadarError):
        radar.parse_price(raw)


def test_postcode_normalising():
    assert radar.normalise_postcode("bs375nh") == "BS37 5NH"
    with pytest.raises(radar.RadarError):
        radar.normalise_postcode("not a postcode")


# --- routes ------------------------------------------------------------------------------

@pytest.fixture
def centred(app, client, monkeypatch):
    monkeypatch.setattr(radar, "postcode_lookup", lambda pc: YATE)
    client.post("/admin/radar/centre", data={"label": "HQ", "postcode": "BS37 5NH"})
    return client


def test_centre_is_saved_in_data_dir_not_repo(app, centred):
    site = radar.load_site(app.config["DATA_DIR"])
    assert site["postcode"] == "BS37 5NH" and site["lat"] == YATE[0]


def test_radar_page_without_centre(client, agent_token):
    assert "hasn't been switched on" in client.get("/radar").data.decode()


def test_osm_import_dedupes(app, centred, monkeypatch):
    shops = [{"osm_ref": "node/1", "name": "Tesco Extra", "brand": "Tesco", "kind": "supermarket",
              "lat": 51.54, "lng": -2.42, "postcode": ""},
             {"osm_ref": "way/2", "name": "One Stop", "brand": "", "kind": "convenience",
              "lat": 51.55, "lng": -2.44, "postcode": ""}]
    monkeypatch.setattr(radar, "overpass_shops", lambda lat, lng: shops)
    centred.post("/admin/radar/import")
    centred.post("/admin/radar/import")   # second import adds nothing
    assert count(app, "SELECT COUNT(*) FROM shops") == 2


def test_add_shop_report_prices_latest_wins(app, centred, agent_token, biscuit_id):
    centred.post("/radar/shop", data={"name": "Corner Shop", "postcode": "BS37 5NH"})
    centred.post("/radar/price", data={"shop_id": 1, "biscuit_id": biscuit_id, "price": "£1.50"})
    centred.post("/radar/price", data={"shop_id": 1, "biscuit_id": biscuit_id, "price": "£1.25", "pack": "300g"})
    assert count(app, "SELECT COUNT(*) FROM prices") == 2                     # history kept
    with app.app_context():
        current = brtdb.current_prices()
    assert [(p["pence"], p["pack"]) for p in current] == [(125, "300g")]     # newest is current

    centred.get("/radar")                    # consume queued flash messages (they mention £1.50)
    page = centred.get("/radar").data.decode()
    assert "Corner Shop" in page and "£1.25" in page and "£1.50" not in page and "Cheapest spotted" in page
    assert "£1.25" in centred.get(f"/b/{biscuit_id}").data.decode()


def test_bad_price_and_hidden_shop(app, centred, agent_token, biscuit_id):
    centred.post("/radar/shop", data={"name": "Corner Shop", "postcode": "BS37 5NH"})
    centred.post("/radar/price", data={"shop_id": 1, "biscuit_id": biscuit_id, "price": "loads"})
    centred.post("/radar/price", data={"shop_id": 1, "biscuit_id": 999, "price": "£1"})
    assert count(app, "SELECT COUNT(*) FROM prices") == 0
    centred.post("/admin/shops/1/toggle")
    page = centred.get("/radar").data.decode()
    assert 'id="shop-1"' not in page         # the shop row is gone (flash text may still name it)


def test_radar_admin_is_loopback_only(client):
    lan = {"REMOTE_ADDR": "192.168.1.50"}
    assert client.post("/admin/radar/import", environ_base=lan).status_code == 403
