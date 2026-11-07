"""World Stage song-metadata API client."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import common


SONG_API_URL = "https://world-stage.org/api/song"
YEAR_API_URL = "https://world-stage.org/api/year"
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


def _external_link(value: object) -> str | None:
    """Only external web sources can become an entry's original link."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        url = urlsplit(value)
        if url.scheme in {"http", "https"} and url.hostname and url.hostname != "media.world-stage.org":
            return value
    except ValueError:
        pass
    return None


def find_song_id(token: str, *, year: str, country: str, entry_code: str | None = None) -> int:
    """Resolve an exact filename identity without choosing an arbitrary entry."""
    if not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"Song API year must be four digits, got {year!r}")
    if not re.fullmatch(r"[a-z]{2}", country, flags=re.IGNORECASE):
        raise ValueError(f"Song API country must be a two-letter code, got {country!r}")
    code = (entry_code or "").strip().lower()
    label = f"{country.upper()} {year}" + (f" entry {code}" if code else " (no entry code)")
    # The country/year endpoint returns only the first regular-year entry.
    # Fetch the full year so coded entries and ambiguous matches are visible.
    request = Request(
        f"{YEAR_API_URL}/{year}/songs",
        headers={
            **HTTP_HEADERS, "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/json", "Cache-Control": "no-cache",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            body = json.load(response)
    except (HTTPError, URLError) as exc:
        detail = _error_detail(exc) if isinstance(exc, HTTPError) else str(exc)
        raise RuntimeError(f"Could not look up World Stage song for {label}: {detail}") from exc
    rows = body.get("result") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Song lookup returned an unexpected response; no song selected")
    matches = [
        row for row in rows
        if str(row.get("year")) == year
        and str(row.get("country_id", "")).strip().lower() == country.lower()
        and str(row.get("entry_code") or "").strip().lower() == code
    ]
    if not matches:
        raise ValueError(f"No World Stage song matches {label}. Check the year, country and entry code in the filename.")
    if len(matches) != 1:
        raise ValueError(f"Multiple World Stage songs match {label}. The filename must identify exactly one entry.")
    song_id = matches[0].get("id")
    if type(song_id) is not int or song_id <= 0:
        raise ValueError(f"Song lookup returned an invalid song ID for {label}")
    return song_id


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
    vtt_link: str | None = None,
) -> None:
    """Publish media, retaining the live original link across repeated processing.

    ``original_link`` is only a fallback for an empty original field, never an
    instruction to replace it. Read fresh state even for cached/local inputs.
    """
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

    url = f"{SONG_API_URL}/{song_id}"
    headers = {
        **HTTP_HEADERS,
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        with urlopen(Request(url, headers={**headers, "Cache-Control": "no-cache"}), timeout=60) as response:
            body = json.load(response)
        current = body.get("result") if isinstance(body, dict) else None
        if not isinstance(current, dict) or current.get("id") != song_id:
            raise ValueError("Song API returned an unexpected song response; no links updated")
        if str(current.get("year")) != year or str(current.get("country_id", "")).lower() != country.lower():
            raise ValueError(f"Song {song_id} does not match {country.upper()} {year}; no links updated")
        if entry_code is not None and str(current.get("entry_code") or "").lower() != entry_code.lower():
            raise ValueError(f"Song {song_id} does not match entry {entry_code}; no links updated")

        payload: dict[str, str] = {"video_link": video_link}
        if poster_link is not None:
            payload["poster_link"] = poster_link
        if vtt_link is not None:
            payload["vtt_link"] = vtt_link
        # A missing key can mean the token cannot view moderator-only fields.
        # Never treat an inaccessible original as empty, or echo stale values.
        if "original_link" in current and not str(current["original_link"] or "").strip():
            source = _external_link(current.get("video_link")) or _external_link(original_link)
            if source is not None:
                payload["original_link"] = source
        request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PATCH")
        with urlopen(request, timeout=60):
            pass
    except (HTTPError, URLError) as exc:
        entry = f" entry {entry_code}" if entry_code is not None else ""
        detail = _error_detail(exc) if isinstance(exc, HTTPError) else str(exc)
        message = f"Could not update World Stage song links for {country.upper()} {year}{entry}: {detail}"
        print(message, file=common.ERR_HANDLE)
        raise RuntimeError(message) from exc
