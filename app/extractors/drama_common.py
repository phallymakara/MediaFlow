import asyncio
from playwright.async_api import async_playwright
from app.core.errors import ExtractError, DRMProtected
from .base import MediaInfo, Variant

_M3U8_HINTS = (".m3u8", "playlist", "/hls/")


async def sniff(page_url: str, wait_ms: int = 25000,
                headless: bool = True) -> MediaInfo:
    found: list[str] = []
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=headless, args=["--mute-audio"])
        ctx = await b.new_context(
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.5 Mobile/15E148 Safari/604.1"),
            viewport={"width": 430, "height": 932},
            is_mobile=True, has_touch=True,
        )
        page = await ctx.new_page()

        def on_req(req):
            u = req.url
            if any(h in u for h in _M3U8_HINTS) and u not in found:
                found.append(u)

        page.on("request", on_req)
        await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)
        # nudge lazy player
        try:
            await page.mouse.click(215, 466)
        except Exception:
            pass
        for _ in range(wait_ms // 500):
            if found:
                break
            await page.wait_for_timeout(500)

        drm = await page.evaluate(
            "() => !!document.querySelector('video') && "
            "!!navigator.requestMediaKeySystemAccess"
        )
        title = await page.title()
        await ctx.close()
        await b.close()

    if not found:
        if drm:
            raise DRMProtected("no plain m3u8 — likely Widevine/EME")
        raise ExtractError("no m3u8 captured; increase wait or run headed")

    uniq = [u for i, u in enumerate(found) if u not in found[:i]]
    return MediaInfo(page_url.split("//")[-1].split("/")[0], "", title,
                     [Variant(u) for u in uniq], is_hls=True)

