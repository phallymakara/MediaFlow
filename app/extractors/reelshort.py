import asyncio
import concurrent.futures
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.core.errors import ExtractError
from app.core.http import get, make_client
from app.core.media import MediaEpisode, MediaFormat, MediaInfo as CoreMediaInfo
from app.extractors.drama_base import BaseDramaExtractor
from app.store import get as cookies_for
from . import drama_common
from .base import MediaInfo, Variant

logger = logging.getLogger(__name__)

_EPISODE_RE = re.compile(
    r"/episodes/episode-(\d+)-(.+?)-([a-f0-9]{24})-([a-z0-9]+)", re.IGNORECASE
)
_MOVIE_RE = re.compile(
    r"/(?:movie|full-episodes)/(.+?)-([a-f0-9]{24})", re.IGNORECASE
)
_BOOK_ID_RE = re.compile(r"([a-f0-9]{24})", re.IGNORECASE)
API = "https://www.reelshort.com/api/video/episode/list"

M3U8_NAMES = (
    "index.m3u8",
    "playlist.m3u8",
    "master.m3u8",
    "video.m3u8",
    "{hash}.m3u8",
    "hls.m3u8",
    "sd.m3u8",
    "hd.m3u8",
)
M3U8_HOSTS = (
    "https://v-mps.crazymaplestudios.com",
    "https://v-img.crazymaplestudios.com",
    "https://v-video.crazymaplestudios.com",
)


def get_configured_profile() -> Optional[str]:
    """Return configured Playwright profile directory if present."""
    import os
    env_dir = os.environ.get("REELSHORT_PROFILE_DIR")
    if env_dir and os.path.isdir(os.path.expanduser(env_dir)):
        return os.path.expanduser(env_dir)
    default_dir = os.path.expanduser("~/.reelshort-profile")
    if os.path.isdir(default_dir):
        return default_dir
    return None


async def probe_m3u8_async(video_pic: str, client: httpx.AsyncClient) -> Optional[str]:
    """Derive candidate m3u8 playlist URL from cover image hash."""
    if not video_pic:
        return None
    m = re.search(r"/vtt-m3u8/(\d+)/([0-9a-f]{32})/", video_pic)
    if not m:
        return None
    book, h = m.groups()
    for host in M3U8_HOSTS:
        for name in M3U8_NAMES:
            candidate = f"{host}/vtt-m3u8/{book}/{h}/{name.format(hash=h)}"
            try:
                r = await client.get(candidate, timeout=4.0)
                if r.status_code == 200 and "#EXTM3U" in r.text[:200]:
                    return candidate
            except Exception:
                continue
    return None


def sniff_m3u8_sync(episode_url: str, profile_dir: str, wait_ms: int = 8000) -> Optional[str]:
    """Sniff m3u8 playlist requests via Playwright persistent session."""
    try:
        from playwright.sync_api import sync_playwright
        hits = []
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                profile_dir,
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("request", lambda r: hits.append(r.url) if ".m3u8" in r.url else None)
            try:
                page.goto(episode_url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(wait_ms)
            finally:
                ctx.close()
        return hits[0] if hits else None
    except Exception as e:
        logger.debug("Playwright sniff failed: %s", e)
        return None


def parse_reelshort_url(url: str) -> Optional[Dict[str, Any]]:
    """Parse ReelShort episode or movie URL to retrieve metadata."""
    if not url:
        return None
    m = _EPISODE_RE.search(url)
    if m:
        return {
            "serial_number": int(m.group(1)),
            "slug": m.group(2),
            "book_id": m.group(3),
            "chapter_id": m.group(4),
        }
    m = _MOVIE_RE.search(url)
    if m:
        return {
            "serial_number": 1,
            "slug": m.group(1),
            "book_id": m.group(2),
            "chapter_id": "",
        }
    m = _BOOK_ID_RE.search(url)
    if m:
        return {
            "serial_number": 1,
            "slug": "",
            "book_id": m.group(1),
            "chapter_id": "",
        }
    return None


async def fetch_all_drama_episodes(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Scrape and resolve all available episodes for the target ReelShort drama."""
    parsed = parse_reelshort_url(url)
    if not parsed or not parsed.get("book_id"):
        raise ExtractError("Could not parse ReelShort drama ID from URL")

    book_id = parsed["book_id"]
    slug = parsed.get("slug", "")
    target_sn = parsed.get("serial_number", 1)

    headers = {
        "User-Agent": settings.UA_PC,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.reelshort.com/",
    }

    own_client = client is None
    c = client or httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True)

    try:
        # If slug is missing, fetch page to discover title slug
        if not slug:
            r = await c.get(url)
            m_slug = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text)
            if m_slug:
                d = json.loads(m_slug.group(1)).get("props", {}).get("pageProps", {}).get("data", {})
                title = d.get("book_title", "")
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

        full_ep_url = f"https://www.reelshort.com/full-episodes/{slug}-{book_id}"
        r = await c.get(full_ep_url)
        m_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text)
        if not m_data:
            raise ExtractError("Could not retrieve ReelShort episode list data")

        data = json.loads(m_data.group(1)).get("props", {}).get("pageProps", {})
        d = data.get("data", {})
        book_title = d.get("book_title") or slug.replace("-", " ").title()
        book_pic = d.get("book_pic", "")
        paid_start = int(d.get("paid_start") or 0)
        total_pages = int(d.get("totalPage", 1))
        all_chapters = list(d.get("chapter_list") or d.get("online_base") or [])

        # Fetch remaining chapter pages concurrently
        if total_pages > 1:
            async def get_page(page_idx: int) -> List[dict]:
                try:
                    res = await c.get(f"{full_ep_url}/{page_idx}")
                    m_p = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text)
                    if m_p:
                        p_data = (
                            json.loads(m_p.group(1))
                            .get("props", {})
                            .get("pageProps", {})
                            .get("data", {})
                        )
                        return list(p_data.get("chapter_list") or p_data.get("online_base") or [])
                except Exception as e:
                    logger.debug("Failed fetching page %d: %s", page_idx, e)
                return []

            page_tasks = [get_page(p) for p in range(2, min(total_pages + 1, 10))]
            pages_results = await asyncio.gather(*page_tasks)
            for chs in pages_results:
                all_chapters.extend(chs)

        # Profile directory if configured
        profile_dir = get_configured_profile()

        # Resolve direct video URLs for free chapters concurrently
        sem = asyncio.Semaphore(settings.CONCURRENCY)

        async def fetch_stream(ch: dict) -> Optional[dict]:
            sn = ch.get("serial_number", 0)
            cid = ch.get("chapter_id", "")
            if sn == 0 or not cid:
                return None
            ep_url = f"https://www.reelshort.com/episodes/episode-{sn}-{slug}-{book_id}-{cid}"
            async with sem:
                try:
                    res = await c.get(ep_url)
                    m_ep = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text)
                    if m_ep:
                        vd = json.loads(m_ep.group(1)).get("props", {}).get("pageProps", {}).get("data", {})
                        vurl = vd.get("video_url")
                        vpic = vd.get("video_pic") or ch.get("video_pic") or book_pic

                        # Tier 2: Probe m3u8 via cover hash if direct video_url is absent
                        if not vurl and vpic:
                            vurl = await probe_m3u8_async(vpic, c)

                        # Tier 3: Browser sniff if user has an authenticated profile
                        if not vurl and profile_dir and (paid_start and sn >= paid_start):
                            loop = asyncio.get_running_loop()
                            vurl = await loop.run_in_executor(
                                None, lambda: sniff_m3u8_sync(ep_url, profile_dir)
                            )

                        if vurl:
                            return {
                                "episode_number": sn,
                                "title": f"Episode {sn:02d} - {book_title}",
                                "url": vurl,
                                "web_url": ep_url,
                                "duration": ch.get("duration"),
                                "thumbnail": vpic,
                            }
                except Exception as exc:
                    logger.debug("Episode %d stream fetch failed: %s", sn, exc)
            return None

        # Fetch streams for free chapters and target requested episode
        chapters_to_check = [
            ch
            for ch in all_chapters
            if ch.get("serial_number", 0) > 0
            and (ch.get("serial_number", 0) <= 35 or ch.get("serial_number") == target_sn)
        ]
        stream_tasks = [fetch_stream(ch) for ch in chapters_to_check]
        resolved_eps = [ep for ep in await asyncio.gather(*stream_tasks) if ep]
        resolved_eps.sort(key=lambda x: x["episode_number"])

        # Also search syndication index for complete series compilation
        from app.extractors.drama_base import BaseDramaExtractor
        clean_name = BaseDramaExtractor.clean_drama_title(book_title)
        dummy_drama = ReelShortExtractor()
        compilations = dummy_drama.find_syndicated_compilations(clean_name)
        for comp in compilations:
            resolved_eps.insert(
                0,
                {
                    "episode_number": 0,
                    "title": comp.title,
                    "url": comp.url,
                    "web_url": comp.url,
                    "duration": comp.duration_seconds,
                    "thumbnail": book_pic,
                },
            )

        if not resolved_eps:
            raise ExtractError("No playable episodes discovered for this drama")

        # Pick matching episode variant or first available
        target_variant = next(
            (
                ep["url"]
                for ep in resolved_eps
                if ep["episode_number"] == target_sn
                and not ep["title"].startswith("[Full Series Complete]")
            ),
            resolved_eps[0]["url"],
        )

        return {
            "site": "reelshort",
            "book_id": book_id,
            "book_title": book_title,
            "book_pic": book_pic,
            "target_variant_url": target_variant,
            "episodes": resolved_eps,
            "total_chapters": len(all_chapters),
        }
    finally:
        if own_client:
            await c.aclose()


async def extract(url: str) -> MediaInfo:
    """Async extractor for ReelShort URLs supporting multi-episode resolution."""
    try:
        data = await fetch_all_drama_episodes(url)
        variants = [
            Variant(
                url=data["target_variant_url"],
                headers={"Referer": "https://www.reelshort.com/"},
            )
        ]
        return MediaInfo(
            site="reelshort",
            media_id=data["book_id"],
            title=data["book_title"],
            variants=variants,
            is_hls=".m3u8" in data["target_variant_url"],
            extra={
                "episodes": data["episodes"],
                "book_id": data["book_id"],
                "total_episodes": len(data["episodes"]),
                "thumbnail_url": data["book_pic"],
            },
        )
    except Exception as exc:
        logger.warning("Fast drama episode extraction encountered error: %s. Falling back.", exc)

    # Fallback to single episode API or browser sniffer
    jar = cookies_for("reelshort")
    parsed = parse_reelshort_url(url)
    bid = parsed.get("book_id", "") if parsed else ""
    if bid:
        try:
            return await _api(bid, url, jar)
        except Exception:
            pass
    return await drama_common.sniff(url)


async def _api(book_id: str, page_url: str, jar: dict) -> MediaInfo:
    api = f"{API}?bookId={book_id}&pageNo=1&pageSize=200"
    async with make_client(
        settings.UA_MOBILE, cookies=jar, referer="https://www.reelshort.com/"
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
        "reelshort",
        str(target.get("episodeId") or book_id),
        target.get("title", ""),
        [Variant(url)],
        is_hls=".m3u8" in url,
    )


class ReelShortExtractor(BaseDramaExtractor):
    """MediaFlow desktop extractor for ReelShort platform."""

    canonical_id_patterns: List[str] = [
        r"/episodes/.*-([a-f0-9]{24})-[a-z0-9]+",
        r"/(?:movie|full-episodes)/.*-([a-f0-9]{24})",
        r"/(?:drama|watch|book|series)/([a-f0-9]{24})",
    ]
    mirror_templates: List[str] = []

    @property
    def platform_name(self) -> str:
        return "ReelShort"

    def can_handle(self, url: str) -> bool:
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "reelshort.com" in netloc

    def extract(self, url: str) -> CoreMediaInfo:
        """Extract multi-episode drama metadata for desktop continuous download."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    drama_data = pool.submit(asyncio.run, fetch_all_drama_episodes(url)).result()
            else:
                drama_data = asyncio.run(fetch_all_drama_episodes(url))

            core_episodes = [
                MediaEpisode(
                    episode_number=ep["episode_number"],
                    title=ep["title"],
                    url=ep["url"],
                    duration_seconds=ep.get("duration"),
                )
                for ep in drama_data["episodes"]
            ]

            formats = [
                MediaFormat(
                    format_id="best",
                    resolution="Best Available",
                    extension="mp4",
                    note="Direct HLS/MP4 Stream",
                    has_video=True,
                    has_audio=True,
                )
            ]

            return CoreMediaInfo(
                url=drama_data["target_variant_url"],
                title=drama_data["book_title"],
                platform="ReelShort",
                thumbnail_url=drama_data["book_pic"],
                formats=formats,
                episodes=core_episodes,
                is_playlist=len(core_episodes) > 1,
            )
        except Exception as exc:
            logger.warning("ReelShort multi-episode extraction failed: %s. Using base drama extractor.", exc)
            return super().extract(url)
