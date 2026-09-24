"""Browser sniffer service for dynamic media stream interception using Playwright."""

import logging
from typing import List, Optional

from app.services.network import redact_url_for_logging, validate_outbound_url

logger = logging.getLogger(__name__)

STREAM_EXTENSIONS = (".m3u8", ".mpd", ".mp4")
STREAM_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "application/dash+xml",
    "video/mp4",
    "video/webm",
)


class BrowserSnifferService:
    """Headless browser sniffer to intercept dynamic video streams and manifests."""

    @staticmethod
    def is_available() -> bool:
        """Check whether the Playwright dependency is available in the current environment.

        Returns:
            True if Playwright can be imported, False otherwise.
        """
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    @classmethod
    def sniff_media_streams(
        cls,
        url: str,
        timeout_ms: int = 15000,
        wait_after_load_ms: int = 3000,
    ) -> List[str]:
        """Load a web page in a headless browser and intercept outgoing video stream requests.

        Args:
            url: Target web page URL.
            timeout_ms: Maximum navigation timeout in milliseconds.
            wait_after_load_ms: Milliseconds to wait after page load for media player scripts.

        Returns:
            List of detected direct stream and playlist URLs.
        """
        try:
            validated_url = validate_outbound_url(url)
        except ValueError as exc:
            logger.warning("Sniffer rejected invalid or unsafe URL: %s", exc)
            return []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.debug("Playwright not installed, skipping browser sniffing.")
            return []

        detected_streams: List[str] = []
        safe_url = redact_url_for_logging(validated_url)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
                )
                try:
                    context = browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"
                        ),
                        viewport={"width": 1280, "height": 720},
                    )
                    page = context.new_page()

                    def on_response(response):
                        try:
                            resp_url = response.url
                            lower_url = resp_url.lower()

                            # Fast check for stream extensions
                            is_stream_ext = any(ext in lower_url for ext in STREAM_EXTENSIONS)
                            content_type = response.headers.get("content-type", "").lower()
                            is_stream_type = any(st in content_type for st in STREAM_CONTENT_TYPES)

                            if (is_stream_ext or is_stream_type) and not lower_url.startswith("data:"):
                                if resp_url not in detected_streams:
                                    detected_streams.append(resp_url)
                        except Exception as resp_err:
                            logger.debug("Error processing network response event: %s", resp_err)

                    page.on("response", on_response)

                    logger.info("Sniffing media streams for %s", safe_url)
                    page.goto(validated_url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(wait_after_load_ms)

                    # Also inspect DOM for static video/source tags
                    try:
                        elements = page.query_selector_all("video, source")
                        for el in elements:
                            src = el.get_attribute("src")
                            if src and src.startswith("http") and src not in detected_streams:
                                lower_src = src.lower()
                                if any(ext in lower_src for ext in STREAM_EXTENSIONS):
                                    detected_streams.append(src)
                    except Exception as dom_err:
                        logger.debug("Failed querying DOM video elements: %s", dom_err)

                finally:
                    browser.close()

        except Exception as exc:
            logger.debug("Browser sniffer encountered an error for %s: %s", safe_url, exc)

        logger.info("Sniffer discovered %d stream(s) for %s", len(detected_streams), safe_url)
        return detected_streams
