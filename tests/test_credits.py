"""Working on it page: suggestions are cited by #id in roadmap.json (public repo) and credited
to their author by name only at render time, from the local DB."""
import re

from app import db as brtdb
from app.views import ROADMAP_FILE, credited

AUTHORS = {7: {"name": "Jack", "avatar": "🍩"}, 1: {"name": "Jack", "avatar": "🍩"}}


def test_credited_strips_the_refs_and_names_the_author():
    c = credited("Fix its name from the specimen page (#7)", AUTHORS)
    assert c["text"] == "Fix its name from the specimen page"
    assert c["credits"] == [{"id": 7, "name": "Jack", "avatar": "🍩"}]


def test_credited_handles_several_refs_a_full_stop_and_missing_ones():
    c = credited("Tags and origin, with a flag (#1, #3).", AUTHORS)
    assert c["text"] == "Tags and origin, with a flag"
    assert [x["id"] for x in c["credits"]] == [1, 3] and c["credits"][1]["name"] is None


def test_roadmap_file_never_names_anyone(app):
    """The guard behind D14: names live in the DB, the repo only has #ids."""
    text = ROADMAP_FILE.read_text(encoding="utf-8")
    assert not re.search(r"Agent [A-Z]", text)  # "Agent dossiers" is a feature, "Agent Jack" a person
    assert "suggested by" not in text.lower()


def test_page_credits_the_author(app, client, agent_token):
    with app.app_context():
        me = brtdb.member_by_token(agent_token)["id"]
        for i in range(1, 10):  # ids 1..9 exist so the roadmap's refs resolve
            brtdb.add_suggestion(me, "idea", f"Suggestion number {i}")
    page = client.get("/working-on-it").data.decode()
    assert "💡 #7 · 🧪 Agent Tester" in page
    assert "(#7)" not in page
