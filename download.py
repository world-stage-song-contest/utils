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
        print(f"[yt-dlp] {message}", file=common.OUT_HANDLE)

    def error(self, message: str) -> None:
        print(f"[yt-dlp] {message}", file=common.ERR_HANDLE)


@dataclass(frozen=True)
class DownloadSettings:
    """Downloader settings shared by recap and batch downloads."""

    browser: str | None
    ffmpeg: str
    prefer_av1_opus: bool = False
    youtube_attestation_mode: str = "none"
    po_token: str | None = None
    bgutil_url: str | None = None
    maximum_video_height: int | None = None


@dataclass(frozen=True)
class YouTubeTopicUpload:
    """The thumbnail metadata needed to save a YouTube Topic upload as audio."""

    thumbnail_url: str
    thumbnail_suffix: str


class YouTubeUnavailableError(RuntimeError):
    """A YouTube source is unavailable and may be skipped by a batch job."""


def is_youtube_unavailable_error(error: BaseException) -> bool:
    """Recognize yt-dlp's explicit source-unavailable responses only."""
    message = str(error).lower()
    return any(marker in message for marker in (
        "video unavailable",
        "this video is not available",
        "private video",
        "video has been removed",
        "video is no longer available",
    ))


def youtube_id(url: str) -> str:
    match = _YT_RE.search(url)
    if not match:
        raise ValueError(f"Cannot parse YouTube id from: {url}")
    return match.group(1)


def is_youtube_url(url: str) -> bool:
    """Return whether a URL is handled by yt-dlp's YouTube extractor."""
    return "youtu" in url.lower()


def youtube_options(settings: DownloadSettings) -> dict[str, object]:
    """Build the shared yt-dlp options, including the selected attestation mode."""
    extractor_args: dict[str, dict[str, list[str]]] = {}
    if settings.youtube_attestation_mode == "po-token":
        if not settings.po_token:
            raise ValueError("YouTube attestation mode 'po-token' requires a PO token")
        extractor_args["youtube"] = {"po_token": [settings.po_token]}
    elif settings.youtube_attestation_mode == "bgutil":
        if not settings.bgutil_url:
            raise ValueError("YouTube attestation mode 'bgutil' requires a bgutil URL")
        extractor_args["youtubepot-bgutilhttp"] = {"base_url": [settings.bgutil_url]}
    elif settings.youtube_attestation_mode != "none":
        raise ValueError(f"Unknown YouTube attestation mode: {settings.youtube_attestation_mode!r}")
    options: dict[str, object] = {
        "extractor_args": extractor_args,
        "logger": YtDlpLogger(),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if settings.browser:
        options["cookiesfrombrowser"] = (settings.browser,)
    if settings.ffmpeg != "ffmpeg":
        options["ffmpeg_location"] = settings.ffmpeg
    return options


def youtube_video_format_selector(settings: DownloadSettings) -> str:
    """Prefer the best video at or below the requested height limit.

    If YouTube has no source at or below the limit, its ``worstvideo`` selector
    chooses the lowest source above it.  FFmpeg subsequently downscales that
    fallback to the requested height.
    """
    limit = settings.maximum_video_height
    if limit is None:
        if settings.prefer_av1_opus:
            return (
                "bv*[vcodec^=av01]+ba[acodec^=opus]/"
                "bv*[vcodec^=av01]+ba/"
                "bv*+ba[acodec^=opus]/bv*+ba/b"
            )
        return "bv*+ba/b"
    if limit <= 0:
        raise ValueError("Maximum video height must be positive")
    at_or_below = f"[height<={limit}]"
    above = f"[height>{limit}]"
    preferred = (
        f"bv*[vcodec^=av01]{at_or_below}+ba[acodec^=opus]/"
        f"bv*[vcodec^=av01]{at_or_below}+ba/"
        f"bv*{at_or_below}+ba[acodec^=opus]/"
    ) if settings.prefer_av1_opus else ""
    return (
        f"{preferred}bv*{at_or_below}+ba/b{at_or_below}/"
        f"worstvideo{above}+bestaudio/worst{above}/bv*+ba/b"
    )


def youtube_topic_upload(url: str, settings: DownloadSettings) -> YouTubeTopicUpload | None:
    """Return Topic-upload artwork metadata, or ``None`` for a normal video.

    YouTube labels auto-generated music channels as ``Artist - Topic``.  These
    uploads are audio releases, so the batch downloader stores them as M4A
    together with yt-dlp's selected thumbnail instead of treating them as video.
    """
    if not is_youtube_url(url):
        return None
    try:
        options = youtube_options(settings)
        options["skip_download"] = True
        with YoutubeDL(cast(Any, options)) as downloader:
            info = downloader.extract_info(url, download=False)
    except Exception as exc:
        message = f"Could not inspect YouTube media {url}: {exc}"
        print(message, file=common.ERR_HANDLE)
        if is_youtube_unavailable_error(exc):
            raise YouTubeUnavailableError(message) from exc
        raise RuntimeError(message) from exc
    if not isinstance(info, dict):
        raise RuntimeError(f"yt-dlp did not return metadata for {url}")
    if not any(
        isinstance(value, str) and value.strip().lower().endswith(" - topic")
        for value in (info.get("channel"), info.get("uploader"))
    ):
        return None
    thumbnail_url = info.get("thumbnail")
    if not isinstance(thumbnail_url, str) or not thumbnail_url:
        raise RuntimeError(f"YouTube Topic upload has no thumbnail: {url}")
    thumbnail_suffix = Path(urlparse(thumbnail_url).path).suffix.lower()
    if thumbnail_suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise RuntimeError(f"Unsupported YouTube thumbnail format {thumbnail_suffix!r}: {thumbnail_url}")
    return YouTubeTopicUpload(thumbnail_url, thumbnail_suffix)


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


def is_google_drive_url(url: str) -> bool:
    return _GDRIVE_RE.search(url) is not None


def world_stage_etag(url: str) -> str | None:
    request = Request(url, headers=HTTP_HEADERS, method="HEAD")
    try:
        with urlopen(request, timeout=60) as response:
            return response.headers.get("ETag")
    except (HTTPError, URLError) as exc:
        message = f"Could not read ETag for {url}: {exc}"
        print(message, file=common.ERR_HANDLE)
        raise RuntimeError(message) from exc


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
        message = f"Could not download {url}: {exc}"
        print(message, file=common.ERR_HANDLE)
        raise RuntimeError(message) from exc


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


def fetch_external(
    url: str,
    media_type: str,
    destination: Path,
    settings: DownloadSettings,
) -> None:
    """Download one external media file to an exact destination path."""
    if is_youtube_url(url):
        if media_type == "a":
            format_selector = "ba[acodec^=opus]/ba" if settings.prefer_av1_opus else "ba[ext=m4a]/ba"
        else:
            format_selector = youtube_video_format_selector(settings)
        output_template = str(destination.with_suffix("")) + ".%(ext)s"
        options = youtube_options(settings)
        options.update({
            "format": format_selector,
            "outtmpl": output_template,
        })
        if media_type == "v":
            options["merge_output_format"] = "mp4"
        try:
            with YoutubeDL(cast(Any, options)) as downloader:
                status = downloader.download([url])
            if status:
                raise RuntimeError(f"yt-dlp exited with status {status}")
            prefix = destination.with_suffix("").name
            files = [
                path for path in destination.parent.glob(f"{prefix}.*")
                if path.is_file() and path.suffix not in {".part", ".ytdl"}
            ]
            if len(files) != 1:
                names = ", ".join(str(path) for path in files) or "none"
                raise RuntimeError(f"yt-dlp did not produce one merged media file for {url}: {names}")
            files[0].replace(destination)
        except Exception as exc:
            message = f"Could not download YouTube media {url}: {exc}"
            print(message, file=common.ERR_HANDLE)
            if is_youtube_unavailable_error(exc):
                raise YouTubeUnavailableError(message) from exc
            raise RuntimeError(message) from exc
    elif match := _GDRIVE_RE.search(url):
        try:
            output = gdown_download(id=match.group(1), output=str(destination), quiet=True)
        except Exception as exc:
            message = f"Could not download Google Drive file {match.group(1)}: {exc}"
            print(message, file=common.ERR_HANDLE)
            raise RuntimeError(message) from exc
        if output is None or not destination.exists():
            raise RuntimeError(f"Google Drive download did not create expected file: {destination}")
    else:
        download_direct(url, destination)


def fetch(url: str, media_type: str, destination: Path, args: common.Args) -> None:
    """Download a recap source using the recap command's configured tools."""
    fetch_external(
        url, media_type, destination,
        DownloadSettings(
            args.browser, args.ffmpeg,
            youtube_attestation_mode=args.youtube_attestation_mode,
            po_token=args.po_token,
            bgutil_url=args.bgutil_url,
        ),
    )


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
        ro = f"{int(raw_ro):02d}"
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
