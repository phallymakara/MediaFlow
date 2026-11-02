"""Drama Catalog Service for discovering, inspecting, and previewing short dramas."""

from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".mediaflow" / "cover_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TIKTOK_CACHE_FILE = Path.home() / ".mediaflow" / "tiktok_dramas_cache.json"
TIKTOK_SEED_FILE = Path(__file__).resolve().parent.parent / "resources" / "tiktok_dramas.json"


def scrape_tiktok_shortdrama_live(max_scrolls: int = 6) -> List[Dict[str, Any]]:
    """Scrape live short dramas from https://www.tiktok.com/shortdrama using Playwright."""
    dramas: Dict[str, Dict[str, Any]] = {}
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            page = browser.new_page()

            def on_resp(resp):
                if "api/drama/theme/drama_list" in resp.url:
                    try:
                        data = resp.json()
                        for d in data.get("dramaList", []):
                            did = str(d.get("dramaID") or "")
                            if did and did not in dramas:
                                covers = (
                                    d.get("cover", {}).get("urlList", [])
                                    if isinstance(d.get("cover"), dict)
                                    else []
                                )
                                cover_url = covers[0] if covers else ""
                                if not cover_url and isinstance(d.get("zoomCover"), dict):
                                    cover_url = (
                                        d["zoomCover"].get("480")
                                        or d["zoomCover"].get("720")
                                        or ""
                                    )

                                themes = []
                                for t in d.get("themes", []):
                                    if isinstance(t, dict) and t.get("tagVal"):
                                        themes.append(t["tagVal"])

                                dramas[did] = {
                                    "id": did,
                                    "title": d.get("dramaName", f"Drama {did}"),
                                    "cover": cover_url,
                                    "desc": d.get("description", ""),
                                    "episodes": int(d.get("numVideos") or 40),
                                    "author": (
                                        d.get("author", {}).get("uniqueId", "tiktok_drama")
                                        if isinstance(d.get("author"), dict)
                                        else "tiktok_drama"
                                    ),
                                    "tags": themes or ["TikTok", "Short Drama"],
                                    "views": str(d.get("numWatched") or ""),
                                }
                    except Exception:
                        pass

            page.on("response", on_resp)
            page.goto("https://www.tiktok.com/shortdrama", wait_until="networkidle", timeout=25000)

            for _ in range(max_scrolls):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1200)

            browser.close()

        result = list(dramas.values())
        if result:
            TIKTOK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            TIKTOK_CACHE_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result
    except Exception as exc:
        logger.warning("Live TikTok shortdrama scraping failed: %s", exc)
        return []


@dataclass
class DramaEpisodeItem:
    """Episode metadata in a drama series."""

    episode_number: int
    title: str
    url: str
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
    is_locked: bool = False


@dataclass
class DramaCatalogItem:
    """Catalog presentation model for a drama series."""

    id: str
    title: str
    platform: str  # "TikTok", "DramaBox", "ReelShort"
    url: str
    cover_url: str
    episodes_count: int
    description: str
    tags: List[str] = field(default_factory=list)
    views_display: str = ""
    author: str = ""
    first_chapter_id: str = ""
    preview_video_url: Optional[str] = None
    episodes: List[DramaEpisodeItem] = field(default_factory=list)


class DramaCatalogService:
    """Service to fetch, inspect, and cache short drama catalogs from online sources."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client or httpx.Client(
            headers=DEFAULT_HEADERS,
            timeout=12.0,
            follow_redirects=True,
        )

    @staticmethod
    def get_cached_cover_path(url: str) -> Optional[Path]:
        """Return Path to local cached cover image if exists."""
        if not url:
            return None
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        ext = ".jpg"
        if ".png" in url.lower():
            ext = ".png"
        cached_file = CACHE_DIR / f"{h}{ext}"
        return cached_file if cached_file.is_file() and cached_file.stat().st_size > 0 else None

    @staticmethod
    def save_cached_cover(url: str, data: bytes) -> Optional[Path]:
        """Save cover image bytes to local cache."""
        if not url or not data:
            return None
        try:
            h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
            ext = ".jpg"
            if ".png" in url.lower():
                ext = ".png"
            dest = CACHE_DIR / f"{h}{ext}"
            dest.write_bytes(data)
            return dest
        except Exception:
            return None

    def fetch_all(
        self,
        platform_filter: str = "All",
        batch_callback: Optional[Callable[[List[DramaCatalogItem]], None]] = None,
    ) -> List[DramaCatalogItem]:
        """Fetch unified online catalog from all supported sources with progressive realtime updates."""
        results: List[DramaCatalogItem] = []
        seen_keys = set()

        def add_items(new_items: List[DramaCatalogItem]) -> None:
            added = False
            for it in new_items:
                key = (it.platform, it.id)
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append(it)
                    added = True
            if added and batch_callback:
                batch_callback(list(results))

        if platform_filter in ("All", "TikTok"):
            add_items(self.fetch_tiktok_catalog())

        if platform_filter in ("All", "DramaBox"):
            add_items(self.fetch_dramabox_catalog())

        if platform_filter in ("All", "ReelShort"):
            add_items(self.fetch_reelshort_catalog())

        return results

    def fetch_dramabox_catalog(self) -> List[DramaCatalogItem]:
        """Fetch all featured, trending, and category dramas from DramaBox."""
        items: List[DramaCatalogItem] = []
        seen_ids = set()

        def parse_items_list(raw_list: list, default_tag: str = "DramaBox"):
            for it in raw_list:
                bid = str(it.get("bookId") or "")
                if not bid or bid in seen_ids:
                    continue
                seen_ids.add(bid)
                title = it.get("bookName") or it.get("name", "DramaBox Drama")
                fcid = str(it.get("firstChapterId") or "")
                clean_slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
                ep_url = (
                    f"https://www.dramaboxdb.com/ep/{bid}_{clean_slug}/{fcid}_Episode-1"
                    if fcid
                    else f"https://dramaboxdb.com/watch/{bid}"
                )

                tags = [t for t in (it.get("typeOneName"), it.get("typeTwoName"), default_tag) if t]
                items.append(
                    DramaCatalogItem(
                        id=bid,
                        title=title,
                        platform="DramaBox",
                        url=ep_url,
                        cover_url=it.get("cover") or "",
                        episodes_count=int(it.get("chapterCount") or 45),
                        description=it.get("introduction", "Popular short drama series."),
                        tags=tags[:3],
                        views_display=it.get("viewCountDisplay", ""),
                        author=it.get("author", "DramaBox"),
                        first_chapter_id=fcid,
                    )
                )

        # 1. Homepage Featured and Categories
        try:
            resp = self._client.get("https://www.dramaboxdb.com/")
            if resp.status_code == 200:
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
                if m:
                    data = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
                    parse_items_list(data.get("bigList", []), "Featured")
                    for sec in data.get("smallData", []):
                        sec_name = sec.get("name") or sec.get("classifyTitle", "Popular")
                        parse_items_list(sec.get("items", []) or sec.get("list", []), sec_name)
        except Exception as exc:
            logger.debug("DramaBox homepage fetch: %s", exc)

        # 2. Trending, Must-Sees, and Hidden Gems Channels
        channels = [
            ("/channel/trending", "Trending"),
            ("/channel/must-sees", "Must See"),
            ("/channel/hidden-gems", "Hidden Gem"),
            ("/genres/258", "Romance"),
        ]
        for ch_path, ch_tag in channels:
            try:
                ch_resp = self._client.get(f"https://www.dramaboxdb.com{ch_path}")
                if ch_resp.status_code == 200:
                    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', ch_resp.text, re.DOTALL)
                    if m:
                        d = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
                        more_items = d.get("moreData", {}).get("items", []) or d.get("bookList", [])
                        parse_items_list(more_items, ch_tag)
            except Exception:
                pass

        return items

    def fetch_reelshort_catalog(self) -> List[DramaCatalogItem]:
        """Fetch all series discoverable across the ReelShort platform."""
        items: List[DramaCatalogItem] = []
        seen_ids = set()

        # 1. Scrape all series linked on ReelShort homepage
        try:
            resp = self._client.get("https://www.reelshort.com/")
            if resp.status_code == 200:
                pattern = re.compile(r'/episodes/episode-\d+-(.+?)-([a-f0-9]{24})-([a-z0-9]+)')
                for match in pattern.finditer(resp.text):
                    slug, bid, cid = match.groups()
                    if bid in seen_ids:
                        continue
                    seen_ids.add(bid)
                    clean_title = slug.replace("-", " ").title()
                    ep_url = f"https://www.reelshort.com/episodes/episode-1-{slug}-{bid}-{cid}"
                    movie_url = f"https://www.reelshort.com/movie/{slug}-{bid}"
                    cover_candidate = f"https://v-mps.crazymaplestudios.com/vtt-m3u8/{bid}/cover.jpg"

                    items.append(
                        DramaCatalogItem(
                            id=bid,
                            title=clean_title,
                            platform="ReelShort",
                            url=movie_url,
                            cover_url=cover_candidate,
                            episodes_count=50,
                            description=f"Popular short drama '{clean_title}' on ReelShort.",
                            tags=["ReelShort", "Short Drama"],
                            author="ReelShort",
                        )
                    )
        except Exception as exc:
            logger.debug("ReelShort homepage scrape: %s", exc)

        return items

    def fetch_tiktok_catalog(self, force_refresh: bool = False) -> List[DramaCatalogItem]:
        """Fetch comprehensive TikTok short drama catalog from persistent cache and live crawl."""
        raw_items: List[Dict[str, Any]] = []

        if not force_refresh and TIKTOK_CACHE_FILE.is_file():
            try:
                raw_items = json.loads(TIKTOK_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                raw_items = []

        if not raw_items and TIKTOK_SEED_FILE.is_file():
            try:
                raw_items = json.loads(TIKTOK_SEED_FILE.read_text(encoding="utf-8"))
            except Exception:
                raw_items = []

        if not raw_items or force_refresh:
            scraped = scrape_tiktok_shortdrama_live(max_scrolls=6)
            if scraped:
                raw_items = scraped

        items: List[DramaCatalogItem] = []
        for feat in raw_items:
            did = str(feat.get("id") or "")
            if not did:
                continue
            author = feat.get("author", "tiktok_drama")
            ep_url = f"https://www.tiktok.com/shortdrama/episode/{did}"
            items.append(
                DramaCatalogItem(
                    id=did,
                    title=feat.get("title", f"TikTok Drama {did}"),
                    platform="TikTok",
                    url=ep_url,
                    cover_url=feat.get("cover", ""),
                    episodes_count=int(feat.get("episodes") or 40),
                    description=feat.get("desc", "TikTok Short Drama series."),
                    tags=feat.get("tags", ["TikTok", "Drama"]),
                    author=author,
                    views_display=feat.get("views", ""),
                )
            )

        return items

    def populate_episodes_and_preview(self, item: DramaCatalogItem) -> DramaCatalogItem:
        """Fetch episode list and preview stream URL for a given drama."""
        if item.platform == "DramaBox":
            self._populate_dramabox_episodes(item)
        elif item.platform == "TikTok":
            self._populate_tiktok_episodes(item)
        elif item.platform == "ReelShort":
            self._populate_reelshort_episodes(item)
        return item

    def _populate_dramabox_episodes(self, item: DramaCatalogItem) -> None:
        try:
            resp = self._client.get(item.url, timeout=12.0)
            if resp.status_code == 200:
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
                if m:
                    data = json.loads(m.group(1))
                    props = data.get("props", {}).get("pageProps", {})
                    ch_list = props.get("chapterList", [])
                    episodes: List[DramaEpisodeItem] = []
                    for ep in ch_list:
                        idx = int(ep.get("index", len(episodes))) + 1
                        is_unlocked = bool(ep.get("unlock", True))
                        vurl = ep.get("mp4") or ep.get("m3u8Url") or ""
                        dur = int(ep.get("duration") // 1000) if ep.get("duration") else None
                        ep_item = DramaEpisodeItem(
                            episode_number=idx,
                            title=ep.get("name") or f"Episode {idx}",
                            url=vurl or item.url,
                            duration_seconds=dur,
                            thumbnail_url=ep.get("cover") or item.cover_url,
                            is_locked=not is_unlocked,
                        )
                        episodes.append(ep_item)
                        if not item.preview_video_url and vurl and is_unlocked:
                            item.preview_video_url = vurl
                    if episodes:
                        item.episodes = episodes
                        item.episodes_count = len(episodes)
        except Exception as exc:
            logger.warning("Failed populating DramaBox episodes: %s", exc)

    def _populate_tiktok_episodes(self, item: DramaCatalogItem) -> None:
        try:
            endpoint = "https://www.tiktok.com/api/drama/episode/item_list/"
            resp = self._client.get(
                endpoint,
                params={"dramaID": item.id, "cursor": "0", "count": "50", "aid": "1988", "language": "en"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                items_list = resp.json().get("itemList", [])
                episodes: List[DramaEpisodeItem] = []
                for it in items_list:
                    d_data = it.get("dramaInfo", {}).get("DramaVideoData", {})
                    ep_num = d_data.get("EpisodeNumber") or len(episodes) + 1
                    author = it.get("author", {}).get("uniqueId") or item.author or "tiktok"
                    vid = str(it.get("id") or "")
                    ep_url = f"https://www.tiktok.com/@{author}/video/{vid}" if vid else f"https://www.tiktok.com/shortdrama/episode/{item.id}/{ep_num}"
                    ep_item = DramaEpisodeItem(
                        episode_number=ep_num,
                        title=it.get("desc") or f"Episode {ep_num}",
                        url=ep_url,
                        duration_seconds=it.get("video", {}).get("duration"),
                        thumbnail_url=item.cover_url,
                        is_locked=False,  # TikTok short drama episodes are 100% free with no VIP/locked tier
                    )
                    episodes.append(ep_item)
                if episodes:
                    item.episodes = episodes
                    item.episodes_count = len(episodes)
        except Exception as exc:
            logger.warning("Failed populating TikTok episodes: %s", exc)
        except Exception as exc:
            logger.warning("Failed populating TikTok episodes: %s", exc)

    def _populate_reelshort_episodes(self, item: DramaCatalogItem) -> None:
        try:
            resp = self._client.get(item.url, timeout=12.0)
            if resp.status_code == 200:
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
                if m:
                    d = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("data", {})
                    chapters = d.get("online_base") or d.get("chapter_list") or []
                    paid_start = int(d.get("paid_start") or 0)
                    if d.get("book_pic"):
                        item.cover_url = d["book_pic"]
                    if d.get("book_title"):
                        item.title = d["book_title"]

                    episodes: List[DramaEpisodeItem] = []
                    for c in chapters:
                        sn = c.get("serial_number", 0)
                        cid = c.get("chapter_id", "")
                        if sn <= 0:
                            continue
                        ep_url = f"https://www.reelshort.com/episodes/episode-{sn}-drama-{item.id}-{cid}"
                        locked = bool(paid_start and sn >= paid_start)
                        episodes.append(
                            DramaEpisodeItem(
                                episode_number=sn,
                                title=f"Episode {sn:02d}",
                                url=ep_url,
                                duration_seconds=c.get("duration"),
                                thumbnail_url=c.get("video_pic") or item.cover_url,
                                is_locked=locked,
                            )
                        )
                    if episodes:
                        item.episodes = episodes
                        item.episodes_count = len(episodes)

                    # Try fetching episode 1 video_url for preview
                    if episodes and not episodes[0].is_locked:
                        try:
                            ep1_resp = self._client.get(episodes[0].url, timeout=8.0)
                            m1 = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', ep1_resp.text, re.DOTALL)
                            if m1:
                                ep1_d = json.loads(m1.group(1)).get("props", {}).get("pageProps", {}).get("data", {})
                                item.preview_video_url = ep1_d.get("video_url") or ep1_d.get("playUrl")
                        except Exception:
                            pass
        except Exception as exc:
            logger.warning("Failed populating ReelShort episodes: %s", exc)


class DramaCatalogWorker(QThread):
    """Background worker for loading the drama catalog without blocking the GUI."""

    catalog_loaded = Signal(list)
    catalog_chunk = Signal(list)
    drama_detailed = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, platform_filter: str = "All", parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.platform_filter = platform_filter
        self.target_item: Optional[DramaCatalogItem] = None
        self._mode = "catalog"
        self._service = DramaCatalogService()

    def set_detail_target(self, item: DramaCatalogItem) -> None:
        """Configure worker to fetch full episodes and preview for a specific drama."""
        self.target_item = item
        self._mode = "detail"

    def run(self) -> None:
        """Execute background fetch task."""
        try:
            if self._mode == "catalog":
                items = self._service.fetch_all(
                    self.platform_filter,
                    batch_callback=lambda current: self.catalog_chunk.emit(list(current)),
                )
                self.catalog_loaded.emit(items)
            elif self._mode == "detail" and self.target_item:
                detailed = self._service.populate_episodes_and_preview(self.target_item)
                self.drama_detailed.emit(detailed)
        except Exception as exc:
            logger.exception("DramaCatalogWorker failed: %s", exc)
            self.error_occurred.emit(str(exc))
