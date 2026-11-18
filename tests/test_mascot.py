"""Tony, the mascot: shown when his files are in static/img/mascot/, and BRT falls back cleanly when not."""
import pytest

from .conftest import PNG


@pytest.fixture
def mascot_dir(app, tmp_path):
    """Point the app at a throwaway static folder, so tests don't depend on the git-ignored files."""
    static = tmp_path / "static"
    folder = static / "img" / "mascot"
    folder.mkdir(parents=True)
    app.static_folder = str(static)
    return folder


def add_tony(folder, *, model=True):
    for name in ("tony.png", "tony-96.png", "tony-favicon.png"):
        (folder / name).write_bytes(PNG)
    if model:
        (folder / "tony.glb").write_bytes(b"glTF")


def test_tony_on_home_page_and_brand(client, agent_token, mascot_dir):
    add_tony(mascot_dir)
    page = client.get("/").data.decode()
    assert "tony-peek" in page and 'href="/tony"' in page
    assert "img/mascot/tony-96.png" in page          # top-bar logo
    assert "img/mascot/tony-favicon.png" in page     # browser tab
    assert "🍪</span>" not in page


def test_tony_page_loads_the_3d_scan(client, agent_token, mascot_dir):
    add_tony(mascot_dir)
    page = client.get("/tony").data.decode()
    assert 'data-model="/static/img/mascot/tony.glb"' in page
    assert "js/tony3d.js" in page
    assert "data-tony-poster" in page  # the photo is always there as the fallback


def test_tony_page_without_model_is_photo_only(client, agent_token, mascot_dir):
    add_tony(mascot_dir, model=False)
    page = client.get("/tony").data.decode()
    assert "data-tony-poster" in page
    assert "data-model" not in page and "tony3d.js" not in page


def test_no_tony_files_falls_back_to_cookie(client, agent_token, mascot_dir):
    page = client.get("/").data.decode()
    assert "🍪</span>" in page and "tony-peek" not in page
    assert client.get("/tony").status_code == 404


def test_tony_page_needs_an_agent(client, mascot_dir):
    add_tony(mascot_dir)
    assert client.get("/tony").status_code == 403
