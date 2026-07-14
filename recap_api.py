"""World Stage recap API client shared by recap and batch workflows."""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from platformdirs import user_cache_path

import app_cache

API_URL = "https://world-stage.org/api/recap"
HTTP_HEADERS = {"User-Agent": "World Stage recap maker"}
API_TYPES = {"year", "show", "country", "submitter"}
SPECIALS = {"false", "true", "only"}

@dataclass(frozen=True)
class ApiQuery:
    type: str
    shows: tuple[str, ...]
    specials: str = "false"
    def __post_init__(self) -> None:
        if self.type not in API_TYPES: raise ValueError(f"Invalid API type: {self.type!r}")
        if self.specials not in SPECIALS: raise ValueError(f"Invalid API specials value: {self.specials!r}")
    def url(self) -> str:
        parameters = [("type", self.type), *(("show", show) for show in self.shows), ("specials", self.specials)]
        return f"{API_URL}?{urlencode(parameters)}"


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the common API-source options to a recap or batch parser."""
    parser.add_argument("--api-type", choices=sorted(API_TYPES), help="Fetch metadata from the World Stage API")
    parser.add_argument("--api-show", action="append", default=[], help="Repeatable API show filter")
    parser.add_argument("--api-specials", choices=sorted(SPECIALS), default="false")


def source_from_cli(args: argparse.Namespace, source_name: str) -> tuple[Path, ApiQuery | None]:
    """Validate exclusive file/API input and build the corresponding API query."""
    source = getattr(args, source_name)
    api_type = args.api_type
    if (source is None) == (api_type is None):
        raise ValueError("Supply either a metadata file or --api-type, but not both")
    if api_type is None:
        if not isinstance(source, Path):
            raise TypeError(f"{source_name} must be a Path")
        return source, None
    return Path("api.json"), ApiQuery(api_type, tuple(args.api_show), args.api_specials)


def fetch_to_cache(query: ApiQuery) -> Path:
    url = query.url()
    app_cache.initialize_database()
    cached = app_cache.cached_api_response(url)
    headers = dict(HTTP_HEADERS)
    if cached is not None and cached[0] and cached[1].exists():
        headers["If-None-Match"] = cached[0]
    try:
        with urlopen(Request(url, headers=headers), timeout=60) as response:
            payload = response.read()
            etag = response.headers.get("ETag")
    except HTTPError as exc:
        if exc.code == 304 and cached is not None and cached[1].exists():
            return cached[1]
        raise RuntimeError(f"Could not fetch recap API response from {url}: {exc}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not fetch recap API response from {url}: {exc}") from exc
    try: value = json.loads(payload)
    except json.JSONDecodeError as exc: raise RuntimeError(f"Recap API returned invalid JSON from {url}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("result"), list):
        raise RuntimeError(f"Recap API returned an unexpected response from {url}")
    rows = value["result"]
    if not all(isinstance(row, dict) for row in rows):
        raise RuntimeError(f"Recap API returned invalid metadata rows from {url}")
    directory = Path(user_cache_path("world-stage-recap-maker", appauthor=False, ensure_exists=True)) / "api"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"recap-{sha256(url.encode()).hexdigest()[:16]}.json"
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)
    path = path.resolve()
    app_cache.store_api_response(url, etag, path)
    return path
