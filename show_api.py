"""World Stage show metadata updates."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import song_api

SHOW_API_URL = "https://world-stage.org/api/show"


def validate_show(year: str, show: str) -> None:
    if not re.fullmatch(r"[0-9]{4}", year):
        raise ValueError("Year must be four digits")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", show):
        raise ValueError("Show must contain lowercase letters, numbers or separating hyphens")


def update_metadata(token: str, year: str, show: str, payload: dict[str, object]) -> None:
    """Publish a show's opening and ordered interval JSON links."""
    validate_show(year, show)
    if not token.strip():
        raise ValueError("A World Stage API token is required")
    request = Request(
        f"{SHOW_API_URL}/{year}-{show}/metadata",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **song_api.HTTP_HEADERS,
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
    try:
        with urlopen(request, timeout=60):
            pass
    except (HTTPError, URLError) as exc:
        detail = song_api._error_detail(exc) if isinstance(exc, HTTPError) else str(exc)
        raise RuntimeError(f"Could not update World Stage show {year}-{show}: {detail}") from exc
