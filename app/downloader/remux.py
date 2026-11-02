import asyncio
import pathlib
from app.config import settings


async def to_mp4(src: pathlib.Path, dst: pathlib.Path, audio: str | None = None) -> pathlib.Path:
    cmd = [settings.FFMPEG, "-y", "-loglevel", "error", "-i", str(src)]
    if audio:
        cmd += ["-i", audio, "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-c", "copy", "-movflags", "+faststart", str(dst)]
    p = await asyncio.create_subprocess_exec(*cmd)
    await p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({p.returncode})")
    src.unlink(missing_ok=True)
    return dst

