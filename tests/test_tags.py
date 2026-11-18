"""Biscuit tags and origin: suggestions #1 (tags beyond rarity) and #3 (country with a flag)."""
from app import db as brtdb
from app import tags


# --- pure -------------------------------------------------------------------------------

def test_flag_from_country_code():
    assert tags.flag("FR") == "🇫🇷" and tags.flag("GB") == "🇬🇧"
    assert tags.flag("XX") == "" and tags.flag(None) == ""


def test_foreign_is_derived_from_origin_not_set_by_hand():
    assert [c["key"] for c in tags.chips("JP", [])] == ["origin", "foreign"]
    assert [c["key"] for c in tags.chips("GB", ["seasonal"])] == ["origin", "seasonal"]
    assert [c["key"] for c in tags.chips(None, ["foreign", "limited"])] == ["limited"]  # can't hand-set foreign


def test_cleaning_drops_unknowns_and_keeps_catalogue_order():
    assert tags.clean_tags(["seasonal", "bogus", "limited", "limited"]) == ["limited", "seasonal"]
    assert tags.clean_origin(" fr ") == "FR" and tags.clean_origin("Narnia") is None


def test_country_picker_puts_the_uk_first():
    choices = tags.country_choices()
    assert choices[0] == ("GB", "United Kingdom")
    rest = [n for _, n in choices[1:]]
    assert rest == sorted(rest)


# --- routes -------------------------------------------------------------------------------

def test_log_a_specimen_with_origin_and_tags(app, client, agent_token):
    r = client.post("/add", data={"name": "Speculoos Crunch", "brand": "Lotus", "origin": "BE",
                                  "tags": ["limited", "nonsense"]})
    assert r.status_code == 302
    with app.app_context():
        b = next(x for x in brtdb.list_biscuits(None) if x["name"] == "Speculoos Crunch")
        assert b["origin"] == "BE" and brtdb.biscuit_tags()[b["id"]] == ["limited"]
    card = client.get("/").data.decode()
    assert "🇧🇪" in card and "🌍" in card and "🎟️" in card


def test_any_agent_can_retag_and_clear(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/tags", data={"origin": "GB", "tags": ["seasonal", "own_brand"]})
    page = client.get(f"/b/{biscuit_id}").data.decode()
    assert "🇬🇧 United Kingdom" in page and "🎄 Seasonal" in page and "kind-foreign" not in page

    client.post(f"/b/{biscuit_id}/tags", data={"origin": "", "tags": []})
    with app.app_context():
        assert brtdb.get_biscuit(biscuit_id)["origin"] is None
        assert brtdb.biscuit_tags().get(biscuit_id) is None
