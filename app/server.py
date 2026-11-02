import asyncio
import logging
import os
import pathlib
import re
import uuid
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.core.errors import DRMProtected, ExtractError, LoginRequired
from app.downloader import direct, hls, remux
from app.extractors import bilibili, douyin, dramabox, kuaishou, reelshort, shortmax
from app.store import put as put_cookies

logger = logging.getLogger(__name__)

app = FastAPI(title="vd-backend")

out_dir = pathlib.Path(settings.OUT_DIR)
out_dir.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(out_dir)), name="files")

ROUTES = {
    "douyin": douyin.extract,
    "kuaishou": kuaishou.extract,
    "bilibili": bilibili.extract,
    "dramabox": dramabox.extract,
    "reelshort": reelshort.extract,
    "shortmax": shortmax.extract,
}


class Req(BaseModel):
    url: str
    quality: int | None = None
    audio: bool = False
    all_episodes: bool = False


def site_of(url: str) -> str:
    for s, host in (
        ("douyin", "douyin.com"),
        ("kuaishou", "kuaishou.com"),
        ("bilibili", "bilibili."),
        ("dramabox", "dramabox"),
        ("reelshort", "reelshort.com"),
        ("shortmax", "shortmax.com"),
    ):
        if host in url:
            return s
    raise HTTPException(400, "unsupported host")


@app.post("/api/resolve")
async def resolve(req: Req):
    site = site_of(req.url)
    try:
        info = await (
            ROUTES[site](req.url, req.quality)
            if site == "bilibili"
            else ROUTES[site](req.url)
        )
    except LoginRequired as e:
        raise HTTPException(401, str(e))
    except DRMProtected as e:
        raise HTTPException(415, f"DRM: {e}")
    except ExtractError as e:
        raise HTTPException(422, str(e))
    return info


@app.post("/api/download")
async def download(req: Req, bg: BackgroundTasks):
    site = site_of(req.url)
    try:
        info = await (
            ROUTES[site](req.url, req.quality)
            if site == "bilibili"
            else ROUTES[site](req.url)
        )
    except ExtractError as e:
        raise HTTPException(422, str(e))

    job = uuid.uuid4().hex
    out = pathlib.Path(settings.OUT_DIR) / job
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-. ]", "_", info.title)[:80] or job

    # Check if continuous download across all drama episodes is requested
    episodes_to_download = (
        info.extra.get("episodes")
        if (req.all_episodes and info.extra.get("episodes"))
        else None
    )

    async def run():
        if episodes_to_download:
            # Continuous download of all episodes in sequence
            for ep in episodes_to_download:
                ep_num = ep.get("episode_number", 1)
                ep_title = ep.get("title", f"Episode_{ep_num}")
                ep_safe = re.sub(r"[^\w\-. ]", "_", ep_title)[:80]
                ep_url = ep.get("url")
                if not ep_url:
                    continue
                try:
                    if ".m3u8" in ep_url:
                        raw = await hls.download(
                            ep_url,
                            out / f"{ep_safe}.ts",
                            {"Referer": f"https://www.{site}.com/"},
                        )
                        await remux.to_mp4(raw, out / f"{ep_safe}.mp4")
                    elif "youtube.com" in ep_url or "youtu.be" in ep_url:
                        import yt_dlp

                        ydl_opts = {
                            "outtmpl": str(out / f"{ep_safe}.%(ext)s"),
                            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                            "quiet": True,
                        }
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([ep_url])
                        )
                    else:
                        await direct.download(
                            ep_url,
                            out / f"{ep_safe}.mp4",
                            {"Referer": f"https://www.{site}.com/"},
                        )
                except Exception as err:
                    logger.error("Episode %s download failed: %s", ep_title, err)
                    (out / f"{ep_safe}_error.txt").write_text(repr(err))
            return

        # Single video / variant download
        if not info.variants:
            (out / "error.txt").write_text("No playable variants found")
            return
        v = info.variants[0]
        try:
            if info.is_hls or ".m3u8" in v.url:
                raw = await hls.download(v.url, out / f"{safe}.ts", v.headers)
            elif "youtube.com" in v.url or "youtu.be" in v.url:
                import yt_dlp

                ydl_opts = {
                    "outtmpl": str(out / f"{safe}.%(ext)s"),
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "quiet": True,
                }
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([v.url])
                )
                return
            else:
                raw = await direct.download(v.url, out / f"{safe}.mp4", v.headers)
            if raw.suffix == ".ts":
                aud = None
                if req.audio and info.extra.get("audio"):
                    a = info.extra["audio"][0]
                    aud = str(
                        await direct.download(
                            a["url"],
                            out / "a.m4a",
                            {"Referer": "https://www.bilibili.com/"},
                        )
                    )
                await remux.to_mp4(raw, out / f"{safe}.mp4", aud)
        except Exception as e:
            (out / "error.txt").write_text(repr(e))

    bg.add_task(run)
    if episodes_to_download:
        return {
            "job": job,
            "title": info.title,
            "episodes_count": len(episodes_to_download),
            "folder": f"/files/{job}",
            "mode": "all_episodes",
        }
    return {"job": job, "title": info.title, "file": f"/files/{job}/{safe}.mp4"}


@app.post("/api/cookies/{site}")
async def set_cookies(site: str, jar: dict[str, str]):
    put_cookies(site, jar)
    return {"ok": True, "count": len(jar)}


@app.get("/api/health")
async def health():
    return {"ok": True}
