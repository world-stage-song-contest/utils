#!/usr/bin/env python3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import hashlib
import multiprocessing as mp
import re
import shutil
import sqlite3
import time
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from gdown.download import download as gdown_download
from yt_dlp import YoutubeDL

import common

RECAP_MEDIA_TYPES = {"v", "a"}
WORLD_STAGE_HOST = "media.world-stage.org"
HTTP_HEADERS = {"User-Agent": "World Stage recap maker"}
_YT_RE = re.compile(r"(?:youtube\.com\/watch.*?[?&]v=|youtu\.be\/)([\w-]{11})")
_GDRIVE_RE = re.compile(r"/d/([A-Za-z0-9_-]{10,})")


@dataclass(frozen=True)
class Data:
    ro: str
    show: str
    country: str
    media_link: str
    media_type: str
    image_link: str


@dataclass(frozen=True)
class CacheRecord:
    url: str
    etag: str | None
    object_path: Path
    display_aspect: float | None


class YtDlpLogger:
    """Forward embedded yt-dlp warnings and errors to the application log."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        print(f"[yt-dlp] {message}", file=common.ERR_HANDLE)

    def error(self, message: str) -> None:
        print(f"[yt-dlp] {message}", file=common.ERR_HANDLE)


def youtube_id(url: str) -> str:
    match = _YT_RE.search(url)
    if not match:
        raise ValueError(f"Cannot parse YouTube id from: {url}")
    return match.group(1)


def cache_database_path(sources_dir: Path) -> Path:
    return sources_dir / "source-cache.sqlite3"


def initialize_cache(database: Path) -> None:
    """Create the content-addressed source cache, migrating the old path cache."""
    with sqlite3.connect(database, timeout=30) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(source_cache)")}
        if columns and "cache_key" not in columns:
            conn.execute("ALTER TABLE source_cache RENAME TO source_cache_legacy")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_cache (
                cache_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                etag TEXT,
                object_path TEXT NOT NULL,
                display_aspect REAL,
                display_height INTEGER,
                updated_at INTEGER NOT NULL
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(source_cache)")}
        if "display_height" not in columns:
            conn.execute("ALTER TABLE source_cache ADD COLUMN display_height INTEGER")
        if "source_cache_legacy" in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }:
            for media_path, url, etag, updated_at in conn.execute(
                "SELECT media_path, url, etag, updated_at FROM source_cache_legacy"
            ):
                key = cache_key("media", url, etag)
                conn.execute("""
                    INSERT OR IGNORE INTO source_cache
                        (cache_key, url, etag, object_path, display_aspect, updated_at)
                    VALUES (?, ?, ?, ?, NULL, ?)
                """, (key, url, etag, media_path, updated_at))
            conn.execute("DROP TABLE source_cache_legacy")
        for key, stored_path in conn.execute("SELECT cache_key, object_path FROM source_cache"):
            normalized = str(Path(stored_path).resolve())
            if normalized != stored_path:
                conn.execute("UPDATE source_cache SET object_path = ? WHERE cache_key = ?", (normalized, key))


def cache_key(kind: str, url: str, etag: str | None) -> str:
    if is_world_stage_url(url) and etag:
        return f"{kind}:etag:{etag}"
    return f"{kind}:url:{url}"


def read_cache_record(database: Path, key: str) -> CacheRecord | None:
    with sqlite3.connect(database, timeout=30) as conn:
        row = conn.execute(
            "SELECT url, etag, object_path, display_aspect FROM source_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    return CacheRecord(row[0], row[1], Path(row[2]), row[3])


def write_cache_record(
    database: Path, key: str, url: str, etag: str | None, object_path: Path,
) -> None:
    with sqlite3.connect(database, timeout=30) as conn:
        conn.execute("""
            INSERT INTO source_cache (cache_key, url, etag, object_path, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                url = excluded.url,
                etag = excluded.etag,
                object_path = excluded.object_path,
                updated_at = excluded.updated_at
        """, (key, url, etag, str(object_path.resolve()), int(time.time())))


def cached_display_properties(sources_dir: Path, media_path: Path) -> tuple[float, int] | None:
    database = cache_database_path(sources_dir)
    with sqlite3.connect(database, timeout=30) as conn:
        row = conn.execute(
            "SELECT display_aspect, display_height FROM source_cache WHERE object_path = ?",
            (str(media_path.resolve()),),
        ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    return float(row[0]), int(row[1])

def store_display_properties(
    sources_dir: Path, media_path: Path, aspect: float, height: int,
) -> None:
    database = cache_database_path(sources_dir)
    with sqlite3.connect(database, timeout=30) as conn:
        conn.execute(
            "UPDATE source_cache SET display_aspect = ?, display_height = ? WHERE object_path = ?",
            (aspect, height, str(media_path.resolve())),
        )


def is_world_stage_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() == WORLD_STAGE_HOST


def world_stage_etag(url: str) -> str | None:
    request = Request(url, headers=HTTP_HEADERS, method="HEAD")
    try:
        with urlopen(request, timeout=60) as response:
            return response.headers.get("ETag")
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Could not read ETag for {url}: {exc}") from exc


def download_direct(url: str, destination: Path) -> None:
    """Stream a direct URL and resume a partial file when the server supports it."""
    offset = destination.stat().st_size if destination.exists() else 0
    headers = dict(HTTP_HEADERS)
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            status = response.getcode()
            mode = "ab" if offset and status == 206 else "wb"
            with destination.open(mode) as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Could not download {url}: {exc}") from exc


def object_path(sources_dir: Path, key: str, suffix: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    path = sources_dir / "objects" / f"{digest}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def link_object(existing: Path, alias: Path) -> Path:
    alias.parent.mkdir(parents=True, exist_ok=True)
    if existing.absolute() == alias.absolute():
        return alias
    if alias.is_symlink() and alias.resolve() == existing.resolve():
        return alias
    if alias.exists() or alias.is_symlink():
        alias.unlink()
    alias.symlink_to(existing.absolute())
    return alias


def fetch(url: str, media_type: str, destination: Path, args: common.Args) -> None:
    if "youtu" in url:
        format_selector = "ba[ext=m4a]/ba" if media_type == "a" else "bv*+ba/b"
        options: dict[str, object] = {
            "format": format_selector,
            "outtmpl": str(destination),
            "extractor_args": {
                "youtubepot-bgutilhttp": {"base_url": ["http://127.0.0.1:4416"]},
            },
            "logger": YtDlpLogger(),
            "quiet": True,
            "no_warnings": True,
        }
        if media_type == "v":
            options["merge_output_format"] = "mp4"
        if args.browser:
            options["cookiesfrombrowser"] = (args.browser,)
        if args.ffmpeg != "ffmpeg":
            options["ffmpeg_location"] = args.ffmpeg
        try:
            with YoutubeDL(cast(Any, options)) as downloader:
                downloader.download([url])
        except Exception as exc:
            raise RuntimeError(f"Could not download YouTube media {url}: {exc}") from exc
    elif match := _GDRIVE_RE.search(url):
        try:
            output = gdown_download(id=match.group(1), output=str(destination), quiet=True)
        except Exception as exc:
            raise RuntimeError(f"Could not download Google Drive file {match.group(1)}: {exc}") from exc
        if output is None or not destination.exists():
            raise RuntimeError(f"Google Drive download did not create expected file: {destination}")
    else:
        download_direct(url, destination)


def fetch_cached(
    url: str, suffix: str, kind: str, media_type: str, args: common.Args,
) -> Path:
    database = cache_database_path(args.vidsdir)
    etag = world_stage_etag(url) if is_world_stage_url(url) else None
    key = cache_key(kind, url, etag)
    record = read_cache_record(database, key)
    if record is not None and record.object_path.exists():
        return record.object_path

    destination = object_path(args.vidsdir, key, suffix)
    partial = destination.with_suffix(f".download{destination.suffix}")
    print(f"[dl] Fetching {url.rsplit('/', 1)[-1]}", file=common.OUT_HANDLE)
    fetch(url, media_type, partial, args)
    if not partial.exists():
        raise FileNotFoundError(f"Downloader did not create expected file: {partial}")
    partial.replace(destination)
    write_cache_record(database, key, url, etag, destination)
    return destination


def create_filename(row: Data, path: Path) -> Path:
    suffix = ".m4a" if row.media_type == "a" else ".mov"
    return path / row.show / f"{row.ro}_{row.country}{suffix}"


def cover_filename(row: Data, path: Path) -> Path | None:
    if not row.image_link:
        return None
    suffix = Path(urlparse(row.image_link).path).suffix.lower() or ".jpg"
    return path / row.show / f"{row.ro}_{row.country}.cover{suffix}"


def download_media(data: Data, args: common.Args) -> Path:
    suffix = ".m4a" if data.media_type == "a" else ".mov"
    object_file = fetch_cached(data.media_link, suffix, "media", data.media_type, args)
    return link_object(object_file, create_filename(data, args.vidsdir))


def download_cover(data: Data, args: common.Args) -> None:
    alias = cover_filename(data, args.vidsdir)
    if alias is None:
        return
    object_file = fetch_cached(data.image_link, alias.suffix, "cover", "a", args)
    link_object(object_file, alias)


def download_many(data: list[Data], args: common.Args) -> list[tuple[str, str, str, Path]]:
    master = download_media(data[0], args)
    result = [(data[0].show, data[0].country, data[0].ro, master)]
    for row in data[1:]:
        result.append((row.show, row.country, row.ro, link_object(master.resolve(), create_filename(row, args.vidsdir))))
    for row in data:
        if row.media_type == "a":
            download_cover(row, args)
    return result


def main(args: common.Args) -> common.Clips:
    data: dict[tuple[str, str], list[Data]] = defaultdict(list)
    result: common.Clips = defaultdict(dict)
    for row in common.load_rows(args.csv):
        media_type = row["type"]
        if media_type not in RECAP_MEDIA_TYPES:
            continue
        raw_ro = row["ro"].strip()
        try:
            ro = f"{int(raw_ro):02d}"
        except ValueError:
            ro = raw_ro
        value = Data(
            ro=ro, show=row["show"].strip(), country=row["cc"].strip().upper(),
            media_link=row["media_link"].strip(), media_type=media_type,
            image_link=row.get("image_link", "").strip(),
        )
        data[(value.media_link, value.media_type)].append(value)

    args.vidsdir.mkdir(parents=True, exist_ok=True)
    initialize_cache(cache_database_path(args.vidsdir))
    print(f"[dl] Found {sum(map(len, data.values()))} recap sources in {args.csv}", file=common.OUT_HANDLE)
    start = time.time()
    jobs = [(values, args) for values in data.values()]
    if args.multiprocessing and jobs:
        with mp.Pool(max(1, mp.cpu_count() // 2)) as pool:
            clips = [item for group in pool.starmap(download_many, jobs) for item in group]
    else:
        clips = [item for values in data.values() for item in download_many(values, args)]
    print(f"[dl] Processed {len(clips)} sources in {time.time() - start:.2f} seconds", file=common.OUT_HANDLE)
    for show, country, ro, path in clips:
        result[(show, ro)][country] = path
    return result
