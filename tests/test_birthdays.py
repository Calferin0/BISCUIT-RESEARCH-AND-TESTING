"""R&D birthday tracker and the top-bar feature strip. Fake names only: real birthdays live in the DB."""
from datetime import date

import pytest

from app import birthdays as b
from app import db as brtdb

from .conftest import count


@pytest.mark.parametrize("text,want", [
    ("19/11", "11-19"), ("1/02", "02-01"), ("9/01", "01-09"), ("09-03", "03-09"), (" 29/2 ", "02-29"),
    ("31/04", None), ("30/02", None), ("13/13", None), ("nope", None), ("", None), ("19/11/1990", None),
])
def test_parse_is_day_first_and_rejects_nonsense(text, want):
    assert b.parse(text) == want


def test_countdown_wraps_the_year_and_leap_days():
    today = date(2026, 11, 23)
    assert b.days_until("11-23", today) == 0 and b.is_today("11-23", today)
    assert b.days_until("11-19", today) == (date(2027, 11, 19) - today).days   # just missed: next year
    assert b.days_until("01-03", today) == (date(2027, 1, 3) - today).days
    assert b.is_today("02-29", date(2027, 2, 28))                              # no 29th: party on the 28th
    assert b.label("02-01") == "1 Feb" and b.form_value("11-19") == "19/11"
    rows = [{"name": "Zed", "birthday": "12-01"}, {"name": "Amy", "birthday": "11-24"}, {"name": "Nob", "birthday": None}]
    assert [r["name"] for r in b.upcoming(rows, today)] == ["Amy", "Zed"]


def _today_mmdd():
    return date.today().strftime("%m-%d")


def test_set_own_birthday_and_page(app, client, agent_token):
    client.post("/birthdays", data={"birthday": "nonsense"})
    assert count(app, "SELECT COUNT(*) FROM members WHERE birthday IS NOT NULL") == 0
    client.post("/birthdays", data={"birthday": "25/12"})
    assert count(app, "SELECT COUNT(*) FROM members WHERE birthday = '12-25'") == 1
    page = client.get("/birthdays").data.decode()
    assert "25 Dec" in page and 'value="25/12"' in page
    client.post("/birthdays", data={"birthday": ""})                            # blank = remove
    assert count(app, "SELECT COUNT(*) FROM members WHERE birthday IS NOT NULL") == 0


def test_birthday_day_banner_cake_and_one_gift_a_year(app, client, agent_token):
    with app.app_context():
        brtdb.set_birthday(1, _today_mmdd())
    page = client.get("/dashboard").data.decode()
    assert "Happy birthday, Agent Tester" in page and "birthday-banner" in page
    client.get("/dashboard")
    assert count(app, f"SELECT SUM(delta) FROM ledger WHERE ref = 'birthday:{date.today().year}'") == b.GIFT
    assert "🎂" in client.get("/agents").data.decode()


def test_others_see_the_banner_but_get_no_gift(app, client, agent_token):
    with app.app_context():
        other = brtdb.add_member("Other", "🦊")
        brtdb.set_birthday(1, _today_mmdd())
    c2 = app.test_client()
    c2.get(f"/join/{other}")
    page = c2.get("/dashboard").data.decode()
    assert "Agent Tester</strong>&#39;s birthday today" in page or "Agent Tester</strong>'s birthday today" in page
    assert count(app, "SELECT COUNT(*) FROM ledger") == 0


def test_admin_sets_birthday_and_switch_turns_it_off(app, client, agent_token):
    client.post("/admin/members/1/edit", data={"name": "Tester", "avatar": "🧪", "birthday": "3/01"})
    assert count(app, "SELECT COUNT(*) FROM members WHERE birthday = '01-03'") == 1
    client.post("/admin/members/1/edit", data={"name": "Tester", "avatar": "🧪", "birthday": "40/40"})
    assert count(app, "SELECT COUNT(*) FROM members WHERE birthday = '01-03'") == 1   # bad date: kept
    from app import features
    client.post("/admin/features", data={"on": [k for k in features.FEATURES if k != "birthdays"]})
    with app.app_context():
        brtdb.set_birthday(1, _today_mmdd())
    assert "birthday-banner" not in client.get("/dashboard").data.decode()
    assert count(app, "SELECT COUNT(*) FROM ledger") == 0


def test_feature_strip_puts_the_specials_in_the_top_bar(client, agent_token):
    page = client.get("/dashboard").data.decode()
    strip = page.split('class="feature-strip"')[1].split("</nav>")[0]
    for label in ("Commandments", "Who Said That?", "Birthdays", "Mystery Tins"):
        assert label in strip


def test_birthdays_need_an_agent(client):
    assert client.get("/birthdays").status_code == 403
