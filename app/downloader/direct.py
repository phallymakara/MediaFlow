import pathlib
from app.core.http import make_client
from app.config import settings


async def download(url: str, dest: pathlib.Path, headers: dict | None = None) -> pathlib.Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with make_client(referer=(headers or {}).get("Referer")) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in r.aiter_bytes(1 << 16):
                    f.write(chunk)
    return dest

