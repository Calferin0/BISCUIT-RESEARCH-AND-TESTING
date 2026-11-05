import pytest

from app import create_app
from app import db as brtdb
from app.scoring import CATEGORY_KEYS

# Smallest byte strings that pass the magic-byte check. The tail makes each one unique (unique hash).
PNG = b"\x89PNG\r\n\x1a\n" + b"brt-test-png"
JPG = b"\xff\xd8\xff\xe0" + b"brt-test-jpg"


@pytest.fixture
def app(tmp_path):
    # Each test gets its own throwaway data dir, so it never touches the real DB.
    return create_app({"DATA_DIR": tmp_path, "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def agent_token(app, client):
    """A member who has followed their join link (the client now carries the cookie)."""
    with app.app_context():
        token = brtdb.add_member("Tester", "🧪")
    client.get(f"/join/{token}")
    return token


@pytest.fixture
def biscuit_id(app):
    with app.app_context():
        return brtdb.add_biscuit("Hobnob", "McVitie's", None, None)


def scores(value: int) -> dict[str, str]:
    return {k: str(value) for k in CATEGORY_KEYS}


def count(app, sql: str, *args) -> int:
    with app.app_context():
        return brtdb.get_db().execute(sql, args).fetchone()[0]
