import asyncio
import concurrent.futures
import json
import re
import uuid
from app.core.http import make_client, get
from app.core.errors import ExtractError
from app.config import settings
from app.store import get as cookies_for
from .base import BaseExtractor, MediaInfo, Variant
from app.core.media import MediaInfo as CoreMediaInfo

_ID_RE = re.compile(r"(?:short-video|photo)/([A-Za-z0-9_-]{8,32})")


def _parse(url: str) -> str:
    m = _ID_RE.search(url)
    if not m:
        raise ExtractError("no kuaishou photo id")
    return m.group(1)


async def _bootstrap() -> dict:
    jar = dict(cookies_for("kuaishou"))
    jar.setdefault("did", "web_" + uuid.uuid4().hex)
    return jar


async def extract(url: str) -> MediaInfo:
    pid = _parse(url)
    jar = await _bootstrap()

    # Mobile JSON endpoint — leaks mainMvUrls unsigned
    api = f"https://v.m.chenzhongtech.com/fw/photo/{pid}?cc=share_copylink&fid=0&kpn=KUAISHOU"
    async with make_client(settings.UA_MOBILE, cookies=jar,
                           referer="https://www.kuaishou.com/") as c:
        r = await get(c, api)
        try:
            data = r.json()
        except json.JSONDecodeError:
            data = {}

    photo = data.get("photo") or {}
    if not photo:
        photo = await _graphql(pid, jar)

    urls = [u.get("url") for u in (photo.get("mainMvUrls") or []) if u.get("url")]
    manifest = (photo.get("manifest") or {}).get("adaptationSet") or []
    for a in manifest:
        for rep in a.get("representation") or []:
            if rep.get("url"):
                urls.append(rep["url"])

    if not urls:
        raise ExtractError("no kuaishou play address")
    variants = [Variant(u, headers={"Referer": "https://www.kuaishou.com/"}) for u in urls]
    return MediaInfo("kuaishou", pid, (photo.get("caption") or "kuaishou")[:120], variants)


async def _graphql(pid: str, jar: dict) -> dict:
    payload = {
        "operationName": "visionVideoDetail",
        "variables": {"photoId": pid, "page": "detail"},
        "query": "query visionVideoDetail($photoId:String,$page:String){"
                 "visionVideoDetail(photoId:$photoId,page:$page){photo{"
                 "caption manifest{adaptationSet{representation{url}}}}}}",
    }
    headers = {"Content-Type": "application/json",
               "Origin": "https://www.kuaishou.com"}
    async with make_client(settings.UA_PC, cookies=jar,
                           referer=f"https://www.kuaishou.com/short-video/{pid}") as c:
        r = await c.post("https://www.kuaishou.com/graphql", json=payload, headers=headers)
        r.raise_for_status()
        return ((r.json().get("data") or {}).get("visionVideoDetail") or {}).get("photo") or {}


class KuaishouExtractor(BaseExtractor):
    """MediaFlow desktop adapter for Kuaishou extractor."""

    @property
    def platform_name(self) -> str:
        return "Kuaishou"

    def can_handle(self, url: str) -> bool:
        if not url or not url.strip():
            return False
        clean = url.strip().lower()
        return "kuaishou.com" in clean or "chenzhongtech.com" in clean

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

