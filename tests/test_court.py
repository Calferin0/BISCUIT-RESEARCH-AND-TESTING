"""Biscuit Court: objections to field reports, a jury of 3, Judge Tony, and blind rating (D10)."""
from datetime import datetime, timedelta

from app import court
from app import db as brtdb

from .conftest import scores

T0 = datetime(2026, 11, 18, 9, 0, 0)


# --- pure rules ---------------------------------------------------------------------------

def test_open_until_three_votes_or_a_day():
    assert court.rule(1, T0, 1, 1, T0 + timedelta(hours=2)).open
    assert not court.rule(1, T0, 2, 1, T0 + timedelta(hours=2)).open
    assert not court.rule(1, T0, 0, 0, T0 + timedelta(hours=24)).open


def test_majority_sustains_and_ties_go_to_the_report():
    assert court.rule(1, T0, 2, 1, T0).verdict == "sustained"
    assert court.rule(1, T0, 1, 2, T0).verdict == "overruled"
    tie = court.rule(1, T0, 1, 1, T0 + timedelta(days=1))
    assert tie.verdict == "overruled"


def test_empty_jury_is_dismissed():
    r = court.rule(7, T0, 0, 0, T0 + timedelta(days=2))
    assert r.verdict == "overruled" and r.line == court.EMPTY_JURY_LINE


def test_judge_tony_is_consistent_per_case():
    a = court.rule(5, T0, 3, 0, T0).line
    assert a == court.rule(5, T0, 3, 0, T0 + timedelta(days=3)).line and a in court.SUSTAINED_LINES


def test_parties_cannot_serve_and_reasons_need_substance():
    assert not court.can_serve(1, 1, 2) and not court.can_serve(2, 1, 2) and court.can_serve(3, 1, 2)
    assert court.clean_reason("  no  ") is None
    assert court.clean_reason("too   much\nspace here") == "too much space here"
    assert len(court.clean_reason("x" * 500)) == court.REASON_MAX


# --- routes -------------------------------------------------------------------------------

def _agent(app, name):
    with app.app_context():
        token = brtdb.add_member(name, "🧪")
        return token, brtdb.member_by_token(token)["id"]


def _report(app, member_id, biscuit_id, comment="Crunchy and brave"):
    with app.app_context():
        brtdb.upsert_rating(member_id, biscuit_id, {k: int(v) for k, v in scores(5).items()}, comment, [])
        return brtdb.get_rating(member_id, biscuit_id)["id"]


def _as(client, token):
    client.get(f"/join/{token}")
    return client


def test_full_case_sustained_and_stamped(app, client, agent_token, biscuit_id):
    """Tester objects to Dee's report; three jurors sustain it; the report is stamped."""
    _, dee = _agent(app, "Dee")
    rid = _report(app, dee, biscuit_id, "5/5 dunk, held together for ages")
    client.post(f"/b/{biscuit_id}/rate", data=scores(3))         # Tester files, so can see
    r = client.post(f"/reports/{rid}/object", data={"reason": "It fell apart in two seconds"})
    assert r.status_code == 302 and "/court" in r.headers["Location"]
    with app.app_context():
        case_id = brtdb.list_objections(dee)[0]["id"]

    for name in ("J1", "J2", "J3"):
        token, juror = _agent(app, name)
        _report(app, juror, biscuit_id)                            # jurors can see the evidence
        juror_client = app.test_client()
        _as(juror_client, token).post(f"/court/{case_id}/vote", data={"vote": "sustained"})

    page = client.get("/court").data.decode()
    assert "verdict-sustained" in page and "Sustained 3 · Overruled 0" in page
    assert any(line in page for line in court.SUSTAINED_LINES)
    assert "⚖️ CONTESTED" in client.get(f"/b/{biscuit_id}").data.decode()


def test_cannot_object_to_own_report_or_twice(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data=scores(4))
    with app.app_context():
        me = brtdb.member_by_token(agent_token)["id"]
        own = brtdb.get_rating(me, biscuit_id)["id"]
    client.post(f"/reports/{own}/object", data={"reason": "I was wrong all along"})
    with app.app_context():
        assert brtdb.list_objections(me) == []

    _, dee = _agent(app, "Dee")
    rid = _report(app, dee, biscuit_id)
    client.post(f"/reports/{rid}/object", data={"reason": "Far too generous"})
    client.post(f"/reports/{rid}/object", data={"reason": "Still far too generous"})
    with app.app_context():
        assert len(brtdb.list_objections(me)) == 1


def test_blind_rating_seals_the_evidence(app, client, agent_token, biscuit_id):
    """Someone who hasn't filed on the biscuit can't object, can't read the evidence, can't vote."""
    _, dee = _agent(app, "Dee")
    rid = _report(app, dee, biscuit_id, "SECRET-COMMENT 5/5")
    assert client.post(f"/reports/{rid}/object", data={"reason": "Peeking at sealed results"}).status_code == 403

    ola_token, ola = _agent(app, "Ola")
    _report(app, ola, biscuit_id)
    ola_client = _as(app.test_client(), ola_token)
    ola_client.post(f"/reports/{rid}/object", data={"reason": "SECRET-REASON too generous"})
    with app.app_context():
        case_id = brtdb.list_objections(ola)[0]["id"]

    page = client.get("/court").data.decode()                      # Tester hasn't filed
    assert "SECRET-COMMENT" not in page and "SECRET-REASON" not in page
    assert "Evidence sealed" in page
    assert client.post(f"/court/{case_id}/vote", data={"vote": "overruled"}).status_code == 403


def test_defendant_can_defend_but_not_vote(app, client, agent_token, biscuit_id):
    dee_token, dee = _agent(app, "Dee")
    rid = _report(app, dee, biscuit_id)
    client.post(f"/b/{biscuit_id}/rate", data=scores(2))
    client.post(f"/reports/{rid}/object", data={"reason": "Nobody likes it that much"})
    with app.app_context():
        case_id = brtdb.list_objections(dee)[0]["id"]

    dee_client = _as(app.test_client(), dee_token)
    dee_client.post(f"/court/{case_id}/defence", data={"defence": "It was a brave biscuit."})
    assert dee_client.post(f"/court/{case_id}/vote", data={"vote": "overruled"}).status_code == 403
    assert client.post(f"/court/{case_id}/defence", data={"defence": "hijack"}).status_code == 403
    assert "It was a brave biscuit." in client.get("/court").data.decode()


def test_no_points_change_hands(app, client, agent_token, biscuit_id):
    _, dee = _agent(app, "Dee")
    rid = _report(app, dee, biscuit_id)
    with app.app_context():
        before = [dict(r) for r in brtdb.points_activity()]
    client.post(f"/b/{biscuit_id}/rate", data=scores(2))
    client.post(f"/reports/{rid}/object", data={"reason": "Nobody likes it that much"})
    with app.app_context():
        after = {r["id"]: dict(r) for r in brtdb.points_activity()}
    assert after[dee] == next(r for r in before if r["id"] == dee)


def test_court_switch_closes_everything(app, client, agent_token, biscuit_id):
    with app.app_context():
        brtdb.set_setting("feature.court", "0")
    assert client.get("/court").status_code == 404
    assert "OBJECTION" not in client.get(f"/b/{biscuit_id}").data.decode()


def test_control_room_can_strike_a_case(app, client, agent_token, biscuit_id):
    dee_token, dee = _agent(app, "Dee")
    rid = _report(app, dee, biscuit_id)
    client.post(f"/b/{biscuit_id}/rate", data=scores(2))
    client.post(f"/reports/{rid}/object", data={"reason": "Nobody likes it that much"})
    with app.app_context():
        case_id = brtdb.list_objections(dee)[0]["id"]
    client.post(f"/admin/court/{case_id}/strike")                 # test client is loopback
    with app.app_context():
        assert brtdb.list_objections(dee) == []
