import pathlib
import urllib.parse
try:
    from mini_racer import Context
except ImportError:
    from py_mini_racer import MiniRacer as Context
from app.config import settings

_JS = (pathlib.Path(__file__).parent / "js" / "douyin_abogus.js").read_text(encoding="utf-8")
_ctx = Context()
_ctx.eval(_JS)

def a_bogus(query: str, ua: str | None = None) -> str:
    return _ctx.call("getABogus", query, ua or settings.UA_PC)

def signed_query(params: dict, ua: str | None = None) -> str:
    q = urllib.parse.urlencode(params)
    return f"{q}&a_bogus={a_bogus(q, ua)}"

