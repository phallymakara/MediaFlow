import asyncio
import concurrent.futures
import re
from app.core.http import make_client, get
from app.core.errors import ExtractError, LoginRequired
from app.signatures.bili_wbi import sign
from app.config import settings
from app.store import get as cookies_for
from .base import BaseExtractor, MediaInfo, Variant
from app.core.media import MediaInfo as CoreMediaInfo

_BV = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV = re.compile(r"av(\d+)", re.I)


async def _to_bvid(client, url: str) -> tuple[str, str]:
    m = _BV.search(url)
    if m:
        bvid = m.group(1)
    else:
        a = _AV.search(url)
        if not a:
            raise ExtractError("no BV/av id in url")
        r = await get(client, "https://api.bilibili.com/x/web-interface/view",
                      params={"aid": a.group(1)})
        bvid = r.json()["data"]["bvid"]
    r = await get(client, "https://api.bilibili.com/x/web-interface/view",
                  params={"bvid": bvid})
    j = r.json()
    if j.get("code") != 0:
        raise ExtractError(f"view failed: {j.get('message')}")
    d = j["data"]
    return bvid, d["cid"]


async def extract(url: str, quality: int = 80) -> MediaInfo:
    jar = cookies_for("bilibili")
    async with make_client(settings.UA_PC, cookies=jar,
                           referer="https://www.bilibili.com/") as c:
        bvid, cid = await _to_bvid(c, url)

        params = await sign(c, {
            "bvid": bvid, "cid": cid, "qn": quality,
            "fnval": 4048, "fnver": 0, "fourk": 1,
            "platform": "pc", "otype": "json",
        })
        r = await get(c, "https://api.bilibili.com/x/player/wbi/playurl", params=params)
        j = r.json()
        if j.get("code") != 0:
            raise ExtractError(f"playurl failed: {j.get('message')}")
        d = j["data"]

    variants: list[Variant] = []
    for v in (d.get("dash") or {}).get("video") or []:
        variants.append(Variant(v["baseUrl"], quality=f'{v["id"]}',
                                bitrate=v.get("bandwidth", 0),
                                headers={"Referer": "https://www.bilibili.com/"}))
    if not variants:
        for u in (d.get("durl") or []):
            variants.append(Variant(u["url"], quality=str(d.get("quality")),
                                    headers={"Referer": "https://www.bilibili.com/"}))
    if not variants:
        raise ExtractError("empty dash/durl")

    variants.sort(key=lambda v: v.bitrate, reverse=True)
    return MediaInfo("bilibili", bvid, bvid, variants,
                     extra={"cid": cid, "audio": _audio(d)})


def _audio(d: dict) -> list[dict]:
    out = []
    for a in (d.get("dash") or {}).get("audio") or []:
        out.append({"url": a["baseUrl"], "id": a["id"]})
    out.sort(key=lambda x: x["id"], reverse=True)
    return out


class BilibiliExtractor(BaseExtractor):
    """MediaFlow desktop adapter for Bilibili extractor."""

    @property
    def platform_name(self) -> str:
        return "Bilibili"

    def can_handle(self, url: str) -> bool:
        if not url or not url.strip():
            return False
        clean = url.strip().lower()
        return "bilibili.com" in clean or "b23.tv" in clean

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

