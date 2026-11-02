import asyncio
import random
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter
from app.config import settings

_LIMIT = asyncio.Semaphore(settings.CONCURRENCY)


def make_client(
    ua: str | None = None,
    cookies: dict | None = None,
    referer: str | None = None,
    http2: bool = True,
) -> httpx.AsyncClient:
    headers = {
        "User-Agent": ua or settings.UA_PC,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return httpx.AsyncClient(
        headers=headers,
        cookies=cookies or {},
        proxy=settings.PROXY,
        timeout=httpx.Timeout(30.0, read=120.0),
        follow_redirects=True,
        http2=http2,
    )


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=15),
    reraise=True,
)
async def get(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    async with _LIMIT:
        r = await client.get(url, **kw)
    r.raise_for_status()
    return r


async def jitter_sleep(a: float = 0.15, b: float = 0.6) -> None:
    await asyncio.sleep(random.uniform(a, b))

