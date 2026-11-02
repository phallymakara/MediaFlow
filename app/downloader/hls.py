import asyncio
import os
import pathlib
import m3u8
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from app.core.http import make_client, get
from app.core.errors import ExtractError
from app.config import settings


async def _pick_variant(client, master_url: str, headers: dict) -> str:
    txt = (await get(client, master_url)).text
    pl = m3u8.loads(txt, uri=master_url)
    if not pl.playlists:
        return master_url
    best = max(pl.playlists, key=lambda p: (p.stream_info.bandwidth if p.stream_info else 0) or 0)
    return best.absolute_uri


async def _key(client, uri: str, headers: dict) -> bytes:
    return (await get(client, uri, headers=headers)).content


async def download(url: str, dest: pathlib.Path, headers: dict | None = None) -> pathlib.Path:
    headers = headers or {}
    async with make_client(cookies=None, referer=headers.get("Referer")) as c:
        media_url = await _pick_variant(c, url, headers)
        pl = m3u8.loads((await get(c, media_url)).text, uri=media_url)

        key_cache: dict[str, bytes] = {}
        seq = pl.media_sequence or 0
        parts: list[bytes] = []

        if pl.segment_map:
            init = pl.segment_map[0]
            parts.append((await get(c, init.absolute_uri, headers=headers)).content)

        for i, seg in enumerate(pl.segments):
            data = None
            for attempt in range(settings.SEGMENT_RETRIES):
                try:
                    data = (await get(c, seg.absolute_uri, headers=headers)).content
                    break
                except Exception:
                    await asyncio.sleep(0.6 * (attempt + 1))
            if data is None:
                raise ExtractError(f"segment {i} failed")

            k = seg.key
            if k and k.method == "AES-128":
                if k.uri not in key_cache:
                    key_cache[k.uri] = await _key(c, k.absolute_uri, headers)
                iv = bytes.fromhex(k.iv[2:]) if (k.iv and k.iv.startswith("0x")) else (bytes.fromhex(k.iv) if k.iv else (seq + i).to_bytes(16, "big"))
                dec = Cipher(algorithms.AES(key_cache[k.uri]), modes.CBC(iv)).decryptor()
                data = dec.update(data) + dec.finalize()
                pad = data[-1]
                if 1 <= pad <= 16:
                    data = data[:-pad]
            parts.append(data)

    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = dest.with_suffix(".ts")
    raw.write_bytes(b"".join(parts))
    return raw

