import json
import pathlib
from app.config import settings

_P = pathlib.Path(settings.COOKIE_FILE)


def load() -> dict[str, dict[str, str]]:
    if not _P.exists():
        return {}
    return json.loads(_P.read_text())


def save(data: dict[str, dict[str, str]]) -> None:
    _P.write_text(json.dumps(data, indent=2))


def get(site: str) -> dict[str, str]:
    return load().get(site, {})


def put(site: str, cookies: dict[str, str]) -> None:
    d = load()
    d.setdefault(site, {}).update(cookies)
    save(d)

