import pytest

from app import create_app
from app import db as brtdb

from .conftest import scores

LAN_PHONE = {"REMOTE_ADDR": "192.168.1.50"}


def test_admin_allowed_from_loopback(client):
    # Flask's test client defaults REMOTE_ADDR to 127.0.0.1.
    assert client.get("/admin/").status_code == 200


def test_admin_forbidden_from_lan(client):
    assert client.get("/admin/", environ_base=LAN_PHONE).status_code == 403
    assert client.post("/admin/members", data={"name": "Mallory"}, environ_base=LAN_PHONE).status_code == 403


def test_spoofed_forwarded_header_is_ignored(client):
    headers = {"X-Forwarded-For": "127.0.0.1"}
    assert client.get("/admin/", environ_base=LAN_PHONE, headers=headers).status_code == 403


def test_recruit_member_and_join(app, client):
    client.post("/admin/members", data={"name": "Ada", "avatar": "🦉"})
    client.post("/admin/members", data={"name": "ada"})  # duplicate, ignored
    with app.app_context():
        members = brtdb.list_members()
    assert [m["name"] for m in members] == ["Ada"]
    assert members[0]["avatar"] == "🦉"

    page = client.get("/admin/").data.decode()
    assert f"/join/{members[0]['token']}" in page
    assert "data:image/svg+xml" in page  # QR code rendered


def test_rotate_token_kills_old_link(app, client):
    with app.app_context():
        old = brtdb.add_member("Brunel", "🎬")
        member_id = brtdb.member_by_token(old)["id"]
    client.post(f"/admin/members/{member_id}/rotate")
    assert client.get(f"/join/{old}").status_code == 404


def test_export_csv_neutralises_formulas(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data={**scores(3), "comment": "=HYPERLINK(\"http://x\")"})
    resp = client.get("/admin/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    body = resp.data.decode("utf-8-sig")
    assert "'=HYPERLINK" in body
    assert "Tester" in body and "Hobnob" in body


def test_refuses_onedrive_data_dir(tmp_path):
    with pytest.raises(RuntimeError, match="OneDrive"):
        create_app({"DATA_DIR": tmp_path / "OneDrive - Motion Impossible" / "BRT"})
