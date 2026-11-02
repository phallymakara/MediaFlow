import pytest
from app import store


def test_store_crud(tmp_path, monkeypatch):
    test_file = tmp_path / "cookies.json"
    monkeypatch.setattr(store, "_P", test_file)

    # Initially empty
    assert store.load() == {}
    assert store.get("bilibili") == {}

    # Put cookies
    store.put("bilibili", {"SESSDATA": "secret_session_token"})
    assert store.get("bilibili") == {"SESSDATA": "secret_session_token"}

    # Update cookies
    store.put("bilibili", {"bili_jct": "csrf_token"})
    bili_cookies = store.get("bilibili")
    assert bili_cookies["SESSDATA"] == "secret_session_token"
    assert bili_cookies["bili_jct"] == "csrf_token"

    # Add second site
    store.put("kuaishou", {"did": "web_123456"})
    assert store.get("kuaishou") == {"did": "web_123456"}
    assert store.get("bilibili")["SESSDATA"] == "secret_session_token"

