"""Central cookie resolution, caching, and export service for MediaFlow."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_COOKIE_CACHE_PATH = Path.home() / ".mediaflow" / "browser_cookies_cache.txt"
_EXPORT_LOCK = threading.Lock()


class CookieService:
    """Manages browser cookie extraction and Netscape cookie caching."""

    @staticmethod
    def parse_browser_spec(browser_spec: str) -> Tuple[str, ...]:
        """Convert a browser specification string into a tuple for yt-dlp.

        Examples:
            "chrome" -> ("chrome",)
            "chrome:Profile 9" -> ("chrome", "Profile 9")
            "brave:Default" -> ("brave", "Default")
        """
        if not browser_spec or not browser_spec.strip():
            return ()
        clean = browser_spec.strip()
        if ":" in clean:
            parts = clean.split(":", 1)
            return (parts[0].strip(), parts[1].strip())
        return (clean,)

    @staticmethod
    def export_browser_cookies(
        browser_spec: str,
        dest_path: Optional[Path] = None,
        timeout: int = 30,
    ) -> bool:
        """Export cookies from the specified browser into a Netscape cookie file.

        Args:
            browser_spec: Browser spec string (e.g. 'chrome:Profile 9' or 'chrome').
            dest_path: Optional target path. Defaults to ~/.mediaflow/browser_cookies_cache.txt.
            timeout: Subprocess timeout in seconds if CLI fallback is needed.

        Returns:
            True if cookies were successfully exported, False otherwise.
        """
        if not browser_spec or not browser_spec.strip():
            return False

        dest = dest_path or DEFAULT_COOKIE_CACHE_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        spec_tuple = CookieService.parse_browser_spec(browser_spec)

        with _EXPORT_LOCK:
            logger.info("Exporting browser cookies from '%s' to %s...", browser_spec, dest)
            try:
                import yt_dlp

                ydl_opts: dict[str, Any] = {
                    "cookiesfrombrowser": spec_tuple,
                    "cookiefile": str(dest),
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.cookiejar.save(filename=str(dest), ignore_discard=True, ignore_expires=True)

                if dest.exists() and dest.stat().st_size > 50:
                    logger.info("Successfully exported browser cookies (%d bytes) to %s", dest.stat().st_size, dest)
                    return True
            except Exception as exc:
                logger.warning("yt-dlp direct cookie export failed for '%s': %s", browser_spec, exc)

            # Fallback via CLI invocation if direct Python import hit issue
            try:
                import subprocess
                import sys

                cmd = [
                    sys.executable,
                    "-m",
                    "yt_dlp",
                    "--cookies-from-browser",
                    browser_spec,
                    "--cookies",
                    str(dest),
                    "--skip-download",
                    "https://www.tiktok.com/@tiktok",
                ]
                subprocess.run(cmd, capture_output=True, timeout=timeout)
                if dest.exists() and dest.stat().st_size > 50:
                    logger.info("CLI cookie export succeeded (%d bytes) to %s", dest.stat().st_size, dest)
                    return True
            except Exception as cli_exc:
                logger.warning("CLI cookie export fallback failed: %s", cli_exc)

            return dest.exists() and dest.stat().st_size > 50

    @staticmethod
    def resolve_effective_cookies_file(
        repo: Optional[Any] = None,
        force_refresh: bool = False,
        cache_max_age_seconds: int = 7200,
    ) -> Optional[str]:
        """Resolve the path to the best available Netscape cookies file.

        Priority order:
        1. Explicitly configured cookies file in Settings repository or MEDIAFLOW_COOKIES_FILE.
        2. Cached browser cookies file if fresh or after successfully exporting from cookies_browser.
        3. Local fallback cookie files (cookies.txt, ~/.mediaflow/cookies.txt).

        Args:
            repo: Optional SettingsRepository or DownloadRepository to read settings from.
            force_refresh: If True, forces re-export from browser even if cache exists.
            cache_max_age_seconds: Max age of cached browser cookies before refreshing (default 2h).

        Returns:
            String path to an existing cookie file, or None if none available.
        """
        # 1. Explicitly configured cookies file
        saved_file = ""
        saved_browser = ""
        if repo and hasattr(repo, "get") and callable(repo.get):
            try:
                saved_file = repo.get("cookies_file") or ""
                saved_browser = repo.get("cookies_browser") or ""
            except Exception:
                pass

        if not saved_file and not saved_browser:
            try:
                from app.database.database import DatabaseManager
                from app.database.repository import SettingsRepository

                db_mgr = getattr(repo, "db", None) or DatabaseManager()
                settings_repo = SettingsRepository(db_mgr)
                saved_file = settings_repo.get("cookies_file") or ""
                saved_browser = settings_repo.get("cookies_browser") or ""
            except Exception:
                pass

        if not saved_file:
            saved_file = os.environ.get("MEDIAFLOW_COOKIES_FILE") or ""

        if saved_file and os.path.exists(saved_file) and os.path.getsize(saved_file) > 10:
            return str(Path(saved_file).resolve())

        # 2. Browser cookies auto-detection and caching
        browser_spec = saved_browser or os.environ.get("MEDIAFLOW_COOKIES_BROWSER") or ""
        cache_path = DEFAULT_COOKIE_CACHE_PATH

        if browser_spec:
            cache_valid = False
            if cache_path.exists() and cache_path.stat().st_size > 50:
                cache_age = time.time() - cache_path.stat().st_mtime
                if cache_age < 60:
                    # If refreshed within the last 60 seconds, reuse to prevent concurrent worker spam
                    return str(cache_path.resolve())
                if cache_age < cache_max_age_seconds and not force_refresh:
                    cache_valid = True

            if cache_valid:
                return str(cache_path.resolve())

            # Needs refresh/export
            exported = CookieService.export_browser_cookies(browser_spec, dest_path=cache_path)
            if exported and cache_path.exists():
                return str(cache_path.resolve())

            # If export failed but existing cache file is present, still return it
            if cache_path.exists() and cache_path.stat().st_size > 50:
                logger.warning("Browser export failed, falling back to existing cached cookie file.")
                return str(cache_path.resolve())

        # 3. Known fallback locations
        fallbacks = [
            cache_path,
            Path("cookies.txt"),
            Path.home() / ".mediaflow" / "cookies.txt",
        ]
        for fb in fallbacks:
            if fb.exists() and fb.stat().st_size > 50:
                return str(fb.resolve())

        return None
