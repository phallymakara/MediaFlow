import asyncio
import concurrent.futures
import json
import re
import urllib.parse
from app.core.http import make_client, get
from app.core.errors import ExtractError
from app.signatures.douyin_sign import signed_query
from app.config import settings
from .base import BaseExtractor, MediaInfo, Variant
from app.core.media import MediaInfo as CoreMediaInfo

_ID_RE = re.compile(r"(?:video|note)/(\d{15,25})")


def parse_id(url: str) -> str:
    m = _ID_RE.search(url)
    if m:
        return m.group(1)
    # short link -> resolve later
    return ""


async def _resolve_short(url: str) -> str:
    async with make_client(settings.UA_MOBILE) as c:
        r = await get(c, url)
        return str(r.url)


async def extract(url: str) -> MediaInfo:
    aweme_id = parse_id(url)
    if not aweme_id:
        url = await _resolve_short(url)
        aweme_id = parse_id(url)
    if not aweme_id:
        raise ExtractError("could not resolve aweme_id")

    # --- Path A: share page, no signature required
    share = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
    async with make_client(settings.UA_MOBILE, referer="https://www.douyin.com/") as c:
        html = (await get(c, share)).text

    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\});?\s*</script>", html, re.S)
    if m:
        blob = json.loads(m.group(1))
        item = _find_item(blob)
        if item:
            return _build(item)

    # --- Path B: signed web API
    params = {
        "aweme_id": aweme_id,
        "aid": "6383",
        "device_platform": "webapp",
        "channel": "channel_pc_web",
        "pc_client_type": "1",
        "version_code": "170400",
        "version_name": "17.4.0",
        "cookie_enabled": "true",
        "platform": "PC",
    }
    q = signed_query(params, settings.UA_PC)
    api = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?{q}"
    async with make_client(settings.UA_PC, referer=share) as c:
        data = (await get(c, api)).json()

    item = data.get("aweme_detail") or None
    if not item:
        raise ExtractError("douyin returned no detail (a_bogus may be stale)")
    return _build(item)


def _find_item(blob: dict) -> dict | None:
    ld = blob.get("loaderData") or {}
    for v in ld.values():
        if isinstance(v, dict) and "videoInfoRes" in v:
            lst = v["videoInfoRes"].get("item_list") or []
            if lst:
                return lst[0]
    return None


def _build(item: dict) -> MediaInfo:
    vid = item.get("video") or {}
    variants = []
    for br in vid.get("bit_rate") or []:
        u = (br.get("play_addr") or {}).get("url_list") or []
        if u:
            variants.append(
                Variant(
                    url=u[0],
                    quality=f'{br.get("gear_name","?")}',
                    bitrate=br.get("bit_rate", 0),
                )
            )
    if not variants:
        for key in ("play_addr_h264", "play_addr", "download_addr"):
            u = (vid.get(key) or {}).get("url_list") or []
            if u:
                variants.append(Variant(url=u[0]))
                break
    if not variants:
        raise ExtractError("no playable address")
    # de-watermark: playwm -> play
    for v in variants:
        v.url = v.url.replace("playwm", "play").replace("/play/", "/play/")
        v.headers = {"Referer": "https://www.douyin.com/"}
    variants.sort(key=lambda v: v.bitrate, reverse=True)
    return MediaInfo(
        "douyin",
        str(item.get("aweme_id")),
        (item.get("desc") or "douyin")[:120],
        variants,
        extra={"author": (item.get("author") or {}).get("nickname")},
    )


class DouyinExtractor(BaseExtractor):
    """MediaFlow desktop adapter for Douyin extractor."""

    @property
    def platform_name(self) -> str:
        return "Douyin"

    def can_handle(self, url: str) -> bool:
        if not url or not url.strip():
            return False
        clean = url.strip().lower()
        return "douyin.com" in clean or "iesdouyin.com" in clean

    def extract(self, url: str) -> CoreMediaInfo:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                res = pool.submit(asyncio.run, extract(url)).result()
        else:
            res = asyncio.run(extract(url))
        return res.to_core_media_info()

