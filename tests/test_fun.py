"""Biscuit of the Day, horoscopes and the Dunk-O-Meter."""
from datetime import date

from app import db as brtdb
from app import fun

from .conftest import count


def test_daily_picks_are_stable_and_change():
    specimens = [{"id": i, "name": f"B{i}"} for i in range(1, 30)]
    d1, d2 = date(2026, 11, 5), date(2026, 11, 6)
    assert fun.biscuit_of_the_day(specimens, d1) == fun.biscuit_of_the_day(list(reversed(specimens)), d1)
    picks = {fun.biscuit_of_the_day(specimens, date(2026, 11, day))[0]["id"] for day in range(1, 29)}
    assert len(picks) > 5                                   # it does move around
    assert fun.biscuit_of_the_day([], d1) == (None, None)
    assert fun.horoscope(1, d1) == fun.horoscope(1, d1)
    assert len({fun.horoscope(1, date(2026, 11, d)) for d in range(1, 29)}) > 5
    assert "{n}" not in fun.horoscope(7, d2)


def test_dashboard_shows_botd_and_horoscope(client, agent_token, biscuit_id):
    page = client.get("/dashboard").data.decode()
    assert "Biscuit of the Day" in page and "Hobnob" in page and "horoscope" in page


def test_dunk_logging_and_guards(app, client, agent_token, biscuit_id):
    client.post("/dunk", data={"biscuit_id": biscuit_id, "seconds": "12.34", "drink": "tea"})
    client.post("/dunk", data={"biscuit_id": biscuit_id, "seconds": "0.1", "drink": "tea"})     # too fast
    client.post("/dunk", data={"biscuit_id": biscuit_id, "seconds": "5000", "drink": "tea"})    # wandered off
    client.post("/dunk", data={"biscuit_id": 999, "seconds": "5", "drink": "tea"})
    client.post("/dunk", data={"biscuit_id": biscuit_id, "seconds": "5", "drink": "gin"})
    assert count(app, "SELECT COUNT(*) FROM dunks") == 1
    client.post("/dunk", data={"biscuit_id": biscuit_id, "seconds": ["", "7.5"], "drink": "coffee"})  # no-JS form
    assert count(app, "SELECT COUNT(*) FROM dunks") == 2
    client.get("/dunk")
    page = client.get("/dunk").data.decode()
    assert "12.3s" in page and "Hall of Fame" in page
    with app.app_context():
        assert brtdb.dunk_by_biscuit()[0]["best_s"] == 12.34
