"""DramaBox platform extractor with API, browser sniffing, and mirror resolution support."""

import json
import re
from typing import List, Optional
from urllib.parse import urlparse

from app.config import settings
from app.core.errors import ExtractError
from app.core.http import get, make_client
from app.extractors.drama_base import BaseDramaExtractor
from app.store import get as cookies_for
from . import drama_common
from .base import MediaInfo, Variant

_BOOK = re.compile(r"bookId=(\w+)|/book/(\w+)")


async def extract(url: str) -> MediaInfo:
    """Async extractor for backend API routing."""
    jar = cookies_for("dramabox")
    bid = next((g for g in (_BOOK.search(url).groups() if _BOOK.search(url) else ()) if g), "")
    if bid:
        try:
            return await _api(bid, url, jar)
        except Exception:
            pass
    return await drama_common.sniff(url)


async def _api(book_id: str, page_url: str, jar: dict) -> MediaInfo:
    api = (
        "https://www.dramaboxdb.com/api/video/episode/list"
        f"?bookId={book_id}&pageNo=1&pageSize=200"
    )
    async with make_client(
        settings.UA_MOBILE, cookies=jar, referer="https://www.dramaboxdb.com/"
    ) as c:
        r = await get(c, api)
        data = r.json()
    eps = (data.get("data") or {}).get("episodeList") or []
    if not eps:
        raise ExtractError("empty episode list")
    free = [e for e in eps if e.get("isFree") or e.get("free")]
    target = (free or eps)[-1]
    url = target.get("videoUrl") or target.get("playUrl")
    if not url:
        raise ExtractError("episode has no direct url (locked)")
    return MediaInfo(
        "dramabox",
        str(target.get("episodeId")),
        target.get("title", ""),
        [Variant(url)],
        is_hls=".m3u8" in url,
    )


class DramaBoxExtractor(BaseDramaExtractor):
    """Custom extractor for DramaBox short drama content with fallback mirror support."""

    canonical_id_patterns: List[str] = [
        r'/(?:drama|watch|movie|book|series)/(\d+)',
    ]
    mirror_templates: List[str] = [
        "https://dramaboxdb.com/watch/{id}",
    ]

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "DramaBox"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to DramaBox or its indexed mirrors."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "dramabox.com" in netloc or "dramaboxdb.com" in netloc

    def extract_drama_id(self, url: str) -> Optional[str]:
        """Extract canonical drama ID (alias for extract_canonical_id)."""
        return self.extract_canonical_id(url)
