"""E-STOP / work-mode button: present on every page, fed by static/img/work/."""
from app import util


def test_estop_on_every_page_kind(client, agent_token, biscuit_id):
    for path in ("/", f"/b/{biscuit_id}", "/leaderboard", "/add", "/admin/"):
        page = client.get(path).data.decode()
        assert "data-estop" in page and "E-STOP" in page and "WORK MODE" in page, path


def test_estop_on_denied_page_too(client):
    assert b"data-estop" in client.get("/").data


def test_list_images_filters_and_sorts(tmp_path):
    for name in ("b.png", "a.JPG", "notes.txt", "evil.svg"):
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in util.list_images(tmp_path)] == ["a.JPG", "b.png"]
    assert util.list_images(tmp_path / "missing") == []
