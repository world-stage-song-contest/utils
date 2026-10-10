"""World Stage song-metadata API client."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import common


SONG_API_URL = "https://world-stage.org/api/song"
MEDIA_URL = "https://media.world-stage.org"
HTTP_HEADERS = {"User-Agent": "World Stage recap maker"}


def media_url(filename: str) -> str:
    """Return the public CDN URL for one uploaded World Stage artifact."""
    return f"{MEDIA_URL}/{filename}"


def _error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace")
        value = json.loads(body)
        description = value.get("error", {}).get("description")
        if isinstance(description, str) and description:
            return description
    except (AttributeError, json.JSONDecodeError, OSError):
        pass
    return str(exc)


def update_song_links(
    token: str,
    *,
    song_id: int | None,
    year: str,
    country: str,
    video_link: str,
    poster_link: str | None = None,
    entry_code: str | None = None,
    original_link: str | None = None,
) -> None:
    """Set the public media links for one country/year entry through the song API."""
    if not token.strip():
        raise ValueError("A World Stage song API token is required to update media links")
    if song_id is None:
        raise ValueError(
            f"Song API update requires an id for {country.upper()} {year}"
            + (f" entry {entry_code}" if entry_code is not None else ""),
        )
    if song_id <= 0:
        raise ValueError(f"Song API id must be positive, got {song_id!r}")
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"Song API year must be four digits, got {year!r}")
    if not re.fullmatch(r"[a-z]{2}", country, flags=re.IGNORECASE):
        raise ValueError(f"Song API country must be a two-letter code, got {country!r}")

    payload: dict[str, str] = {"video_link": video_link}
    if poster_link is not None:
        payload["poster_link"] = poster_link
    if original_link is not None:
        payload["original_link"] = original_link
    request = Request(
        f"{SONG_API_URL}/{song_id}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **HTTP_HEADERS,
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PATCH",
    )
    try:
        with urlopen(request, timeout=60):
            pass
    except (HTTPError, URLError) as exc:
        entry = f" entry {entry_code}" if entry_code is not None else ""
        detail = _error_detail(exc) if isinstance(exc, HTTPError) else str(exc)
        message = f"Could not update World Stage song links for {country.upper()} {year}{entry}: {detail}"
        print(message, file=common.ERR_HANDLE)
        raise RuntimeError(message) from exc
