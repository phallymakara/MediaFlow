import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient

from app.main import app, site_of
import app.server as server
from app.extractors.base import MediaInfo, Variant
from app.core.errors import ExtractError, LoginRequired


@pytest.fixture
def client():
    return TestClient(app)


def test_site_of():
    assert site_of("https://www.douyin.com/video/1234567890123456789") == "douyin"
    assert site_of("https://v.douyin.com/abcde/") == "douyin"
    assert site_of("https://www.kuaishou.com/short-video/3xabcdef") == "kuaishou"
    assert site_of("https://www.bilibili.com/video/BV1xx411c7mD") == "bilibili"
    assert site_of("https://www.dramaboxdb.com/watch/12345") == "dramabox"
    assert site_of("https://www.dramabox.com/watch/12345") == "dramabox"
    assert site_of("https://www.reelshort.com/drama/12345") == "reelshort"
    assert site_of("https://www.shortmax.com/drama/12345") == "shortmax"

    with pytest.raises(Exception):
        site_of("https://www.unknownwebsite.com/video/123")


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_set_cookies(client, tmp_path, monkeypatch):
    test_cookie_file = tmp_path / "cookies.json"
    from app import store
    monkeypatch.setattr(store, "_P", test_cookie_file)

    resp = client.post("/api/cookies/douyin", json={"sessionid": "xyz123"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "count": 1}

    saved = store.get("douyin")
    assert saved.get("sessionid") == "xyz123"


def test_resolve_success(client, monkeypatch):
    mock_media = MediaInfo(
        site="douyin",
        media_id="1234567890",
        title="Sample Douyin Video",
        variants=[Variant(url="https://example.com/video.mp4", quality="1080p")],
    )

    monkeypatch.setitem(server.ROUTES, "douyin", AsyncMock(return_value=mock_media))
    resp = client.post("/api/resolve", json={"url": "https://www.douyin.com/video/1234567890"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["site"] == "douyin"
    assert data["media_id"] == "1234567890"
    assert data["title"] == "Sample Douyin Video"
    assert len(data["variants"]) == 1
    assert data["variants"][0]["url"] == "https://example.com/video.mp4"


def test_resolve_extract_error(client, monkeypatch):
    monkeypatch.setitem(server.ROUTES, "douyin", AsyncMock(side_effect=ExtractError("Failed to parse")))
    resp = client.post("/api/resolve", json={"url": "https://www.douyin.com/video/1234567890"})
    assert resp.status_code == 422
    assert "Failed to parse" in resp.text


def test_resolve_login_required(client, monkeypatch):
    monkeypatch.setitem(server.ROUTES, "bilibili", AsyncMock(side_effect=LoginRequired("Need SESSDATA")))
    resp = client.post("/api/resolve", json={"url": "https://www.bilibili.com/video/BV1xx411c7mD"})
    assert resp.status_code == 401
    assert "Need SESSDATA" in resp.text


def test_download_endpoint(client, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "OUT_DIR", str(tmp_path))

    mock_media = MediaInfo(
        site="douyin",
        media_id="1234567890",
        title="My_Video",
        variants=[Variant(url="https://example.com/video.mp4", quality="1080p")],
    )

    monkeypatch.setitem(server.ROUTES, "douyin", AsyncMock(return_value=mock_media))
    with monkeypatch.context() as m:
        from unittest.mock import patch
        with patch("app.downloader.direct.download", new=AsyncMock(return_value=tmp_path / "My_Video.mp4")):
            resp = client.post("/api/download", json={"url": "https://www.douyin.com/video/1234567890"})
            assert resp.status_code == 200
            data = resp.json()
            assert "job" in data
            assert data["title"] == "My_Video"
            assert data["file"].endswith("My_Video.mp4")
