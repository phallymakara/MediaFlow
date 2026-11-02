#!/usr/bin/env python3
"""ReelShort drama downloader tool with tiered m3u8 stream resolution.

Tiers:
  Tier 1: Direct CDN stream extraction via __NEXT_DATA__ (free episodes).
  Tier 2: Algorithmic CDN m3u8 playlist probing via cover hash (/vtt-m3u8/).
  Tier 3: Browser sniffer using persistent Playwright session profile for authenticated/VIP titles.

Usage:
  # Download free/probed episodes:
  uv run python tools/reelshort.py "https://www.reelshort.com/movie/reborn-for-the-lycan-king-693b8f146a2054699d00944d"

  # Download using logged-in Playwright browser profile:
  uv run python tools/reelshort.py "https://www.reelshort.com/movie/reborn-for-the-lycan-king-693b8f146a2054699d00944d" --profile ~/.reelshort-profile
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple
import urllib.parse
import httpx

BASE = "https://www.reelshort.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Referer": BASE + "/",
    "Accept-Language": "en-US,en;q=0.9",
}

# Tier 2: CDN hosts and filename variations
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


def _next_data(html: str) -> dict:
    """Extract and parse __NEXT_DATA__ JSON from HTML."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        raise RuntimeError("No __NEXT_DATA__ found (layout changed or bot-walled)")
    return json.loads(m.group(1))


def normalize_url(url: str) -> str:
    """Ensure URL points to movie or full-episodes page for complete enumeration."""
    url = url.strip()
    # If episode URL is passed, extract slug and book_id
    m_ep = re.search(r"/episodes/episode-\d+-(.+?)-([a-f0-9]{24})", url, re.IGNORECASE)
    if m_ep:
        return f"{BASE}/full-episodes/{m_ep.group(1)}-{m_ep.group(2)}"
    return url


def enumerate_episodes(movie_url: str) -> Tuple[str, str, int, List[dict]]:
    """Enumerate all episodes from movie or full-episodes page.

    Returns:
        (book_title, book_id, paid_start, episodes_list)
    """
    movie_url = normalize_url(movie_url)
    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        r = client.get(movie_url)
        r.raise_for_status()
        d = _next_data(r.text)["props"]["pageProps"]["data"]

        # Support both 'online_base' and 'chapter_list' payloads
        raw_list = d.get("online_base") or d.get("chapter_list") or []

        # If full-episodes pagination is present, collect additional pages
        total_pages = int(d.get("totalPage", 1))
        if total_pages > 1:
            for p in range(2, min(total_pages + 1, 15)):
                try:
                    p_resp = client.get(f"{movie_url}/{p}")
                    if p_resp.status_code == 200:
                        p_data = _next_data(p_resp.text)["props"]["pageProps"]["data"]
                        raw_list.extend(p_data.get("chapter_list") or p_data.get("online_base") or [])
                except Exception as e:
                    print(f"Warning: Failed to fetch page {p}: {e}", file=sys.stderr)

    seen = set()
    eps = []
    for c in raw_list:
        sn = c.get("serial_number", 0)
        cid = c.get("chapter_id", "")
        if sn > 0 and sn not in seen:
            seen.add(sn)
            eps.append({
                "serial": sn,
                "chapter_id": cid,
                "video_pic": c.get("video_pic", ""),
                "video_url": c.get("video_url") or c.get("playUrl") or "",
                "duration": c.get("duration", 0),
            })

    eps.sort(key=lambda e: e["serial"])
    book_title = d.get("book_title", "ReelShort_Drama")
    book_id = d.get("book_id", "")
    paid_start = int(d.get("paid_start") or 0)
    return book_title, book_id, paid_start, eps


def probe_m3u8(video_pic: str) -> Optional[str]:
    """Tier 2: Derive candidate m3u8 playlist URL from cover image hash."""
    if not video_pic:
        return None
    m = re.search(r"/vtt-m3u8/(\d+)/([0-9a-f]{32})/", video_pic)
    if not m:
        return None
    book, h = m.groups()
    with httpx.Client(headers=HEADERS, timeout=5.0, follow_redirects=True) as client:
        for host in M3U8_HOSTS:
            for name in M3U8_NAMES:
                candidate = f"{host}/vtt-m3u8/{book}/{h}/{name.format(hash=h)}"
                try:
                    r = client.get(candidate)
                    if r.status_code == 200 and "#EXTM3U" in r.text[:200]:
                        return candidate
                except httpx.RequestError:
                    continue
    return None


def sniff_m3u8(episode_url: str, profile_dir: str, wait_ms: int = 9000) -> Optional[str]:
    """Tier 3: Sniff m3u8 playlist requests via Playwright using persistent profile."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run: uv add playwright && uv run playwright install chromium", file=sys.stderr)
        return None

    resolved_profile = os.path.expanduser(profile_dir)
    os.makedirs(resolved_profile, exist_ok=True)
    hits = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            resolved_profile,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_request(req):
            if ".m3u8" in req.url:
                hits.append(req.url)

        page.on("request", on_request)
        try:
            page.goto(episode_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(wait_ms)
        except Exception as e:
            print(f"Browser navigation warning: {e}", file=sys.stderr)
        finally:
            ctx.close()

    return hits[0] if hits else None


def _episode_slugs(book_id: str) -> Dict[str, str]:
    """Fetch all anchor slugs from full-episodes page to map chapter_id -> full URL."""
    res_map = {}
    try:
        with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
            r = client.get(f"{BASE}/full-episodes/{book_id}")
            if r.status_code == 200:
                for path in re.findall(r'href="(/episodes/[^"]+)"', r.text):
                    cid = path.split("-")[-1]
                    res_map[cid] = BASE + path
    except Exception:
        pass
    return res_map


def fetch_episode_stream(ep_url: str) -> Tuple[Optional[str], str]:
    """Fetch episode page to extract direct video_url and video_pic.

    Returns:
        (video_url, video_pic)
    """
    try:
        with httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
            r = client.get(ep_url)
            if r.status_code != 200:
                return None, ""
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if m:
                d = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("data", {})
                vurl = d.get("video_url") or d.get("playUrl")
                vpic = d.get("video_pic") or ""
                return vurl, vpic
    except Exception:
        pass
    return None, ""


def download_stream(url: str, out_file: pathlib.Path, referer: str) -> bool:
    """Download video stream using yt-dlp with AES-128 key handling."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "-q",
        "--add-header", f"Referer:{referer}",
        "--add-header", f"User-Agent:{UA}",
        "-o", str(out_file),
        url,
    ]
    res = subprocess.run(cmd)
    return res.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="ReelShort drama downloader tool with tiered m3u8 stream resolution."
    )
    parser.add_argument("url", help="ReelShort movie, full-episodes, or episode URL.")
    parser.add_argument(
        "-o",
        "--outdir",
        default="./downloads",
        help="Target download folder (default: ./downloads).",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Path to persistent browser profile directory (e.g. ~/.reelshort-profile).",
    )
    parser.add_argument(
        "--episodes",
        default=None,
        help="Optional episode filter (e.g. '1-10', '1,3,5', or 'all').",
    )
    args = parser.parse_args()

    title, book_id, paid_start, eps = enumerate_episodes(args.url)
    safe_title = re.sub(r'[<>:"/\\|?*]', "_", title).strip()
    out_path = pathlib.Path(args.outdir).expanduser().resolve() / safe_title
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"\n=======================================================")
    print(f"Title:      {title}")
    print(f"Book ID:    {book_id}")
    print(f"Episodes:   {len(eps)} total")
    print(f"Free Range: Episodes 1 to {paid_start - 1 if paid_start > 0 else len(eps)}")
    print(f"Output:     {out_path}")
    print(f"=======================================================\n")

    # Filter episodes if specified
    if args.episodes and args.episodes.lower() != "all":
        selected_serials = set()
        for part in args.episodes.split(","):
            if "-" in part:
                start, end = part.split("-", 1)
                selected_serials.update(range(int(start), int(end) + 1))
            else:
                selected_serials.add(int(part))
        eps = [e for e in eps if e["serial"] in selected_serials]

    slug_map = _episode_slugs(book_id)

    success_count = 0
    fail_count = 0

    for e in eps:
        serial = e["serial"]
        dest = out_path / f"Episode_{serial:03d}.mp4"
        if dest.exists() and dest.stat().st_size > 1024:
            print(f"  [ep {serial:03d}] already downloaded -> skipping")
            success_count += 1
            continue

        cid = e["chapter_id"]
        ep_url = slug_map.get(cid) or f"{BASE}/episodes/episode-{serial}-drama-{book_id}-{cid}"
        locked = bool(paid_start and serial >= paid_start)

        stream_url = e.get("video_url")
        pic_url = e.get("video_pic", "")

        # Tier 1: If stream_url missing, fetch individual episode page metadata
        if not stream_url:
            fetched_url, fetched_pic = fetch_episode_stream(ep_url)
            if fetched_url:
                stream_url = fetched_url
            if fetched_pic:
                pic_url = fetched_pic

        resolution_method = "Tier 1: API Direct" if stream_url else None

        # Tier 2: Probe m3u8 via cover image hash
        if not stream_url and pic_url:
            probed = probe_m3u8(pic_url)
            if probed:
                stream_url = probed
                resolution_method = "Tier 2: Cover Hash Probe"

        # Tier 3: Authenticated Playwright Sniffer
        if not stream_url and locked and args.profile:
            print(f"  [ep {serial:03d}] locked -> attempting Tier 3 browser sniff...")
            sniffed = sniff_m3u8(ep_url, args.profile)
            if sniffed:
                stream_url = sniffed
                resolution_method = "Tier 3: Browser Profile Sniff"

        if not stream_url:
            if locked:
                print(f"  [ep {serial:03d}] LOCKED (Paid start is {paid_start}). Use --profile to unlock with paid session.")
            else:
                print(f"  [ep {serial:03d}] FAILED: No playable stream URL discovered.")
            fail_count += 1
            continue

        print(f"  [ep {serial:03d}] downloading via {resolution_method}...")
        ok = download_stream(stream_url, dest, ep_url)
        if ok:
            print(f"  [ep {serial:03d}] OK -> {dest.name}")
            success_count += 1
        else:
            print(f"  [ep {serial:03d}] FAIL download failed")
            fail_count += 1

    print(f"\nFinished. Success: {success_count}, Failed/Skipped: {fail_count}\n")


if __name__ == "__main__":
    main()
