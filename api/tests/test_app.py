from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from silo.app import create_app
from silo.settings import Settings

INDEX_HTML = "<!doctype html><html><head><title>Silo</title></head><body>app</body></html>"


@pytest.fixture
def web_dist(tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML)
    (dist / "assets" / "app.js").write_text("console.log('silo')")
    return dist


@pytest.fixture
def settings(tmp_path: Path, web_dist: Path):
    data = tmp_path / "data"
    games = tmp_path / "games"
    data.mkdir()
    games.mkdir()
    return Settings(data_dir=data, library_dir=games, web_dist_dir=web_dist)


async def test_root_serves_index(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Silo</title>" in response.text


async def test_deep_link_falls_back_to_index(client):
    response = await client.get("/games/some-game-id")
    assert response.status_code == 200
    assert "<title>Silo</title>" in response.text


async def test_static_asset_served(client):
    response = await client.get("/assets/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.text == "console.log('silo')"


async def test_unknown_api_path_stays_json_404(client):
    response = await client.get("/api/v1/nonexistent")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_no_web_dist_root_is_404(tmp_path: Path):
    data = tmp_path / "data"
    games = tmp_path / "games"
    data.mkdir()
    games.mkdir()
    app = create_app(Settings(data_dir=data, library_dir=games))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/")).status_code == 404
