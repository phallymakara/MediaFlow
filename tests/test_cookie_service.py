"""Unit tests for CookieService."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.cookie_service import CookieService


def test_parse_browser_spec() -> None:
    """Verify browser specification parsing into yt-dlp compatible tuples."""
    assert CookieService.parse_browser_spec("") == ()
    assert CookieService.parse_browser_spec("   ") == ()
    assert CookieService.parse_browser_spec("chrome") == ("chrome",)
    assert CookieService.parse_browser_spec("chrome:Profile 9") == ("chrome", "Profile 9")
    assert CookieService.parse_browser_spec("brave:Default") == ("brave", "Default")
    assert CookieService.parse_browser_spec("firefox:dev-edition") == ("firefox", "dev-edition")


def test_resolve_effective_cookies_file_explicit(tmp_path: Path) -> None:
    """Verify explicit cookies file takes top priority."""
    fake_cookie = tmp_path / "custom_cookies.txt"
    fake_cookie.write_text("# Netscape HTTP Cookie File\n.example.com TRUE / FALSE 0 name val\n")

    mock_repo = MagicMock()
    mock_repo.get.side_effect = lambda key, default="": str(fake_cookie) if key == "cookies_file" else ""

    resolved = CookieService.resolve_effective_cookies_file(repo=mock_repo)
    assert resolved == str(fake_cookie.resolve())


def test_resolve_effective_cookies_file_cached(tmp_path: Path) -> None:
    """Verify cached browser cookies file is returned if fresh."""
    fake_cache = tmp_path / "browser_cookies_cache.txt"
    fake_cache.write_text("# Netscape HTTP Cookie File\n.tiktok.com TRUE / FALSE 0 session test\n" + "x" * 100)

    mock_repo = MagicMock()
    mock_repo.get.side_effect = lambda key, default="": "chrome:Profile 9" if key == "cookies_browser" else ""

    with patch("app.services.cookie_service.DEFAULT_COOKIE_CACHE_PATH", fake_cache):
        resolved = CookieService.resolve_effective_cookies_file(repo=mock_repo, force_refresh=False)
        assert resolved == str(fake_cache.resolve())


def test_export_browser_cookies_mocked(tmp_path: Path) -> None:
    """Verify export_browser_cookies calls yt-dlp and writes cookiefile."""
    dest = tmp_path / "exported.txt"

    with patch("yt_dlp.YoutubeDL") as mock_ydl_class:
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        def fake_save(filename, **kwargs):
            Path(filename).write_text("# Netscape HTTP Cookie File\n" + "cookie_data" * 20)

        mock_ydl.cookiejar.save.side_effect = fake_save

        success = CookieService.export_browser_cookies("chrome:Profile 9", dest_path=dest)
        assert success is True
        assert dest.exists()
        assert dest.stat().st_size > 50
