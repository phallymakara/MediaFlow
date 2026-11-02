import hashlib
import time
import urllib.parse
from app.core.errors import ExtractError

MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29,
    28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25,
    54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]
_DROP = set("!'()*")


def _mixin(raw: str) -> str:
    return "".join(raw[i] for i in MIXIN_TAB)[:32]


async def _keys(client) -> tuple[str, str]:
    r = await client.get("https://api.bilibili.com/x/web-interface/nav")
    data = r.json().get("data", {})
    wbi = data.get("wbi_img") or {}
    img = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    if not img or not sub:
        raise ExtractError("wbi keys unavailable (nav blocked)")
    return img, sub


async def sign(client, params: dict) -> dict:
    img, sub = await _keys(client)
    mixin = _mixin(img + sub)
    params = {k: v for k, v in params.items() if v is not None}
    params["wts"] = int(time.time())
    items = sorted(params.items())
    clean = {k: "".join(c for c in str(v) if c not in _DROP) for k, v in items}
    query = urllib.parse.urlencode(clean)
    params["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return params

