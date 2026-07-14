"""World Stage song-metadata API client."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import common


SONG_API_URL = "https://world-stage.org/api/song"
MEDIA_URL = "https://media.world-stage.org"


def media_url(filename: str) -> str:
    """Return the public CDN URL for one uploaded World Stage artifact."""
    return f"{MEDIA_URL}/{filename}"


def update_song_links(
    token: str,
    *,
    year: str,
    country: str,
    video_link: str,
    poster_link: str | None = None,
) -> None:
    """Set the public media links for one country/year through the song API."""
    if not token.strip():
        raise ValueError("A World Stage song API token is required to update media links")
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"Song API year must be four digits, got {year!r}")
    if not re.fullmatch(r"[a-z]{2}", country, flags=re.IGNORECASE):
        raise ValueError(f"Song API country must be a two-letter code, got {country!r}")

    payload: dict[str, str] = {
        "year": year,
        "country": country.lower(),
        "video_link": video_link,
    }
    if poster_link is not None:
        payload["poster_link"] = poster_link
    request = Request(
        SONG_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60):
            pass
    except (HTTPError, URLError) as exc:
        message = f"Could not update World Stage song links for {country.upper()} {year}: {exc}"
        print(message, file=common.ERR_HANDLE)
        raise RuntimeError(message) from exc
