import asyncio
import concurrent.futures
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
from app.core.media import MediaInfo as CoreMediaInfo

_BOOK = re.compile(r"bookId=(\w+)|/book/(\w+)|/drama/(\w+)|seriesId=(\w+)")
API = "https://www.shortmax.com/api/drama/episode/list"


async def extract(url: str) -> MediaInfo:
    jar = cookies_for("shortmax")
    bid = next((g for g in (_BOOK.search(url).groups() if _BOOK.search(url) else ()) if g), "")
    if bid:
        try:
            return await _api(bid, url, jar)
        except Exception:
            pass
    return await drama_common.sniff(url)


async def _api(book_id: str, page_url: str, jar: dict) -> MediaInfo:
    api = f"{API}?bookId={book_id}&pageNo=1&pageSize=200"
    async with make_client(
        settings.UA_MOBILE, cookies=jar, referer="https://www.shortmax.com/"
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
        "shortmax",
        str(target.get("episodeId") or book_id),
        target.get("title", ""),
        [Variant(url)],
        is_hls=".m3u8" in url,
    )


class ShortMaxExtractor(BaseDramaExtractor):
    """MediaFlow desktop extractor for ShortMax platform."""

    canonical_id_patterns: List[str] = [
        r'/(?:drama|watch|book|series)/(\w+)',
    ]
    mirror_templates: List[str] = []

    @property
    def platform_name(self) -> str:
        return "ShortMax"

    def can_handle(self, url: str) -> bool:
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "shortmax.com" in netloc

