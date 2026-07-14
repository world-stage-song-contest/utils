#!/usr/bin/env python3
"""Batch preparation commands for World Stage show metadata."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path
import multiprocessing as mp
import re
import subprocess as sp
import tempfile
from typing import Any, Iterable, cast

import app_config
import common
import download
import ffmpeg_tools
import prepare
import recap_api
import song_api


@dataclass(frozen=True)
class BatchVideo:
    """One downloadable video row and its final World Stage filename."""

    year: str
    cc: str
    country: str
    submitter: str
    artist: str
    title: str
    language: str
    media_link: str

    @property
    def name(self) -> str:
        return f"ws{self.year}{self.cc}"


@dataclass(frozen=True)
class BatchDownloadRequest:
    """The GUI- and CLI-independent settings for one batch download."""

    input: Path
    api_query: recap_api.ApiQuery | None
    output_directory: Path
    temporary_directory: Path | None
    browser: str | None
    ffmpeg: str | None
    ffprobe: str | None
    jobs: int
    upload: bool
    update_song_links: bool
    overwrite: bool
    dry_run: bool


@dataclass(frozen=True)
class BatchTask:
    video: BatchVideo
    destination: Path
    raw_directory: Path
    downloader_settings: download.DownloadSettings
    ffprobe: str
    encoding: ffmpeg_tools.RecapEncoding
    overwrite: bool


@dataclass(frozen=True)
class BatchResult:
    video: BatchVideo
    destination: Path
    status: str
    detail: str
    artwork: Path | None = None


@dataclass(frozen=True)
class BatchInput:
    """Downloadable rows plus the rows intentionally excluded from a run."""

    videos: list[BatchVideo]
    skipped: list[str]
    missing_media_links: list[str]


def video_rows(path: Path) -> BatchInput:
    """Read video rows, retaining visible diagnostics for intentionally absent media."""
    videos: list[BatchVideo] = []
    skipped: list[str] = []
    missing_media_links: list[str] = []
    for index, row in enumerate(common.load_rows(path), start=1):
        if row["type"] != "v":
            skipped.append(f"row {index}: not a video")
            continue

        year = row.get("year", "").strip()
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError(f"row {index}: year must be a four-digit year, got {year!r}")
        cc = row.get("cc", "").strip().lower()
        if not re.fullmatch(r"[a-z]{2}", cc):
            raise ValueError(f"row {index}: cc must be a two-letter country code, got {cc!r}")
        submitter = row.get("submitter", "").strip()
        if not submitter:
            raise ValueError(f"row {index} ({year}/{cc}): submitter must not be empty")
        country = row.get("country", "").strip()
        if not country:
            raise ValueError(f"row {index} ({year}/{cc}): country must not be empty")

        media_link = row.get("media_link", "").strip()
        if not media_link:
            skipped.append(f"row {index} ({year}/{cc}): no media_link")
            missing_media_links.append(f"{country} {year}")
            continue
        if download.is_world_stage_url(media_link):
            skipped.append(f"row {index} ({year}/{cc}): already hosted on media.world-stage.org")
            continue

        # Existing historical metadata contains a few legacy two-letter values.
        # Preserve the supplied value as media metadata rather than making an
        # otherwise downloadable row unusable.
        language = row.get("language", "").strip().lower()
        if not language:
            raise ValueError(f"row {index} ({year}/{cc}): language must not be empty")
        videos.append(BatchVideo(
            year=year,
            cc=cc,
            country=country,
            submitter=submitter,
            artist=row.get("artist", "").strip(),
            title=row.get("title", "").strip(),
            language=language,
            media_link=media_link,
        ))

    names = [video.name for video in videos]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Input has duplicate output names: {', '.join(duplicates)}")
    return BatchInput(videos, skipped, missing_media_links)


def configured_text(settings: dict[str, Any], key: str) -> str:
    value = settings[key]
    if not isinstance(value, str):
        raise TypeError(f"Saved {key} setting must be a string")
    return value


def _worker_run(cmd: list[str], capture: bool = False) -> sp.CompletedProcess[bytes]:
    """Run FFmpeg inside a batch worker without interleaving child output."""
    try:
        return sp.run(
            cmd,
            check=True,
            stdout=sp.PIPE if capture else sp.DEVNULL,
            stderr=sp.PIPE,
        )
    except sp.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", "replace")
        raise RuntimeError(f"Command failed: {cmd}\nstderr:\n{stderr}") from exc


def _worker_media(task: BatchTask) -> ffmpeg_tools.FFmpeg:
    return ffmpeg_tools.FFmpeg(task.downloader_settings.ffmpeg, task.ffprobe, _worker_run)


def _media_tags(video: BatchVideo) -> ffmpeg_tools.MediaTags:
    return prepare.media_tags(
        video.year, video.cc, video.artist, video.title, video.language, video.country,
    )


def _fetch_task_media(
    task: BatchTask,
    destination: Path,
    media_type: str,
    raw_path: Path,
    settings: download.DownloadSettings,
) -> BatchResult | None:
    """Fetch one task source and convert an unavailable YouTube result to a status."""
    try:
        download.fetch_external(task.video.media_link, media_type, raw_path, settings)
    except download.YouTubeUnavailableError as exc:
        raw_path.unlink(missing_ok=True)
        return BatchResult(task.video, destination, "unavailable", str(exc))
    if not raw_path.exists():
        raise FileNotFoundError(f"Downloader did not create expected file: {raw_path}")
    return None


def process_task(task: BatchTask) -> BatchResult:
    """Download, transcode if needed, and tag one independent batch video."""
    try:
        topic_upload = download.youtube_topic_upload(task.video.media_link, task.downloader_settings)
    except download.YouTubeUnavailableError as exc:
        return BatchResult(task.video, task.destination, "unavailable", str(exc))

    destination = task.destination
    if topic_upload is not None:
        destination = destination.with_suffix(".m4a")
        cover = destination.with_suffix(topic_upload.thumbnail_suffix)
        if destination.exists() and not task.overwrite:
            if cover.exists():
                return BatchResult(task.video, destination, "existing", "Topic audio already exists", cover)
            download.download_direct(topic_upload.thumbnail_url, cover)
            return BatchResult(task.video, destination, "complete", "existing Topic audio", cover)

        raw_path = task.raw_directory / f"{task.video.name}.download.m4a"
        download.download_direct(topic_upload.thumbnail_url, cover)
        if result := _fetch_task_media(
            task, destination, "a", raw_path,
            replace(task.downloader_settings, prefer_av1_opus=False),
        ):
            return result

        _worker_media(task).make_audio(cover, raw_path, destination, _media_tags(task.video))
        raw_path.unlink()
        return BatchResult(task.video, destination, "complete", "YouTube Topic audio", cover)

    if destination.exists() and not task.overwrite:
        return BatchResult(task.video, destination, "existing", "already exists")

    raw_path = task.raw_directory / f"{task.video.name}.download.mov"
    if result := _fetch_task_media(
        task, destination, "v", raw_path, task.downloader_settings,
    ):
        return result

    source_codecs = _worker_media(task).make_av1_opus_video(
        raw_path,
        destination,
        _media_tags(task.video),
        task.encoding,
        preserve_flac=download.is_google_drive_url(task.video.media_link),
    )
    raw_path.unlink()
    return BatchResult(task.video, destination, "complete", f"{source_codecs.video}/{source_codecs.audio}")


def worker_count(jobs: int, task_count: int) -> int:
    if jobs < 0:
        raise ValueError("Concurrent downloads cannot be negative")
    if jobs > 0:
        return min(task_count, jobs)
    return common.automatic_worker_count(task_count)


def download_one_batch(
    videos: list[BatchVideo],
    *,
    output_directory: Path,
    raw_directory: Path,
    downloader_settings: download.DownloadSettings,
    ffprobe: str,
    encoding: ffmpeg_tools.RecapEncoding,
    jobs: int,
    s3_config: prepare.S3Config | None,
    s3_client: Any,
    song_api_token: str | None,
    overwrite: bool,
    dry_run: bool,
) -> list[str]:
    if dry_run:
        for video in videos:
            destination = output_directory / f"{video.name}.mov"
            if destination.exists() and not overwrite:
                print(f"[batch] Skipping existing {destination}")
                continue
            raw_path = raw_directory / f"{video.name}.download.mov"
            print(f"[batch] Would download {video.media_link} -> {raw_path}")
            print(f"[batch] Would tag {raw_path} -> {destination}")
            if s3_config is not None:
                print(f"[batch] Would upload {destination} to s3://{s3_config.bucket}/{destination.name}")
        return []

    raw_directory.mkdir(parents=True, exist_ok=True)
    tasks: list[BatchTask] = []
    for video in videos:
        destination = output_directory / f"{video.name}.mov"
        if destination.exists() and not overwrite and not download.is_youtube_url(video.media_link):
            print(f"[batch] Skipping existing {destination}")
            continue
        print(f"[batch] Queued {video.name} from {video.media_link}")
        tasks.append(BatchTask(
            video, destination, raw_directory, downloader_settings, ffprobe, encoding, overwrite,
        ))
    if not tasks:
        return []

    count = worker_count(jobs, len(tasks))
    print(f"[batch] Processing {len(tasks)} videos with {count} worker(s).")
    if count == 1:
        return _consume_results(
            map(process_task, tasks), s3_config, s3_client,
            song_api_token, downloader_settings.ffmpeg, ffprobe, overwrite,
        )
    with mp.Pool(count) as pool:
        return _consume_results(
            pool.imap_unordered(process_task, tasks), s3_config, s3_client,
            song_api_token, downloader_settings.ffmpeg, ffprobe, overwrite,
        )


def _make_metadata(
    result: BatchResult, ffmpeg: str, ffprobe: str, overwrite: bool,
) -> Path:
    """Generate the same CDN JSON document produced by prepare.py."""
    media = ffmpeg_tools.FFmpeg(ffmpeg, ffprobe, common.run)
    return prepare.make_json_for_media(
        result.destination,
        artist=result.video.artist,
        title=result.video.title,
        duration=media.duration(result.destination),
        mode="audio" if result.artwork is not None else "video",
        image_path=result.artwork,
        overwrite_existing=overwrite,
    )


def _upload_artifacts(
    config: prepare.S3Config | None, client: Any, *paths: Path | None,
) -> None:
    """Upload all artifacts belonging to one completed batch item."""
    if config is not None:
        for path in paths:
            prepare.upload(path, config, client)


def _update_song_links(result: BatchResult, token: str) -> None:
    """Publish the exact CDN URLs only after the corresponding uploads succeed."""
    song_api.update_song_links(
        token,
        year=result.video.year,
        country=result.video.cc,
        video_link=song_api.media_url(result.destination.name),
        poster_link=song_api.media_url(result.artwork.name) if result.artwork is not None else None,
    )
    print(f"[batch] Updated World Stage media links for {result.video.country} {result.video.year}")


def _log_result(
    result: BatchResult,
    s3_config: prepare.S3Config | None,
    s3_client: Any,
    song_api_token: str | None,
    ffmpeg: str,
    ffprobe: str,
    overwrite: bool,
) -> None:
    if result.status == "unavailable":
        print(f"[batch] Skipping unavailable YouTube video {result.video.name}: {result.detail}")
        return
    if result.status == "existing":
        print(f"[batch] Skipping existing {result.destination}")
        metadata = result.destination.with_suffix(".json")
        if not metadata.exists():
            metadata = _make_metadata(result, ffmpeg, ffprobe, overwrite=False)
            print(f"[batch] Created missing metadata {metadata}")
            _upload_artifacts(s3_config, s3_client, metadata)
        return
    print(f"[batch] Tagged {result.destination.name} ({result.detail})")
    metadata = _make_metadata(result, ffmpeg, ffprobe, overwrite=True)
    _upload_artifacts(s3_config, s3_client, result.destination, result.artwork, metadata)
    if song_api_token is not None:
        _update_song_links(result, song_api_token)


def _consume_results(
    results: Iterable[BatchResult],
    s3_config: prepare.S3Config | None,
    s3_client: Any,
    song_api_token: str | None,
    ffmpeg: str,
    ffprobe: str,
    overwrite: bool,
) -> list[str]:
    """Log completed tasks and collect the final unavailable-video report."""
    unavailable: list[str] = []
    for result in results:
        _log_result(result, s3_config, s3_client, song_api_token, ffmpeg, ffprobe, overwrite)
        if result.status == "unavailable":
            unavailable.append(f"{result.video.country} {result.video.year}")
    return unavailable


def print_report(unavailable: list[str], missing_media_links: list[str]) -> None:
    """Print the final actionable report for sources the batch could not process."""
    print("[batch] Download report")
    for heading, videos in (
        ("Unavailable videos", unavailable),
        ("Videos without media links", missing_media_links),
    ):
        print(f"[batch] {heading}:")
        if videos:
            for video in sorted(videos):
                print(f"[batch]   {video}")
        else:
            print("[batch]   None")


def download_videos(request: BatchDownloadRequest) -> None:
    batch_input = video_rows(recap_api.fetch_to_cache(request.api_query) if request.api_query else request.input)
    for message in batch_input.skipped:
        print(f"[batch] Skipping {message}")
    if not batch_input.videos:
        print_report([], batch_input.missing_media_links)
        raise ValueError("The input contains no downloadable video rows")

    request.output_directory.mkdir(parents=True, exist_ok=True)
    settings = app_config.recap_settings()
    downloader_settings = download.DownloadSettings(
        browser=request.browser if request.browser is not None else configured_text(settings, "browser") or None,
        ffmpeg=request.ffmpeg if request.ffmpeg is not None else configured_text(settings, "ffmpeg"),
        prefer_av1_opus=True,
        youtube_attestation_mode=configured_text(settings, "youtube_attestation_mode"),
        po_token=configured_text(settings, "po_token") or None,
        bgutil_url=configured_text(settings, "bgutil_url") or None,
    )
    ffprobe = request.ffprobe if request.ffprobe is not None else configured_text(settings, "ffprobe")
    encoding = ffmpeg_tools.RecapEncoding(
        av1_preset=int(configured_text(settings, "av1_preset")),
        av1_crf=int(configured_text(settings, "av1_crf")),
        av1_threads=int(configured_text(settings, "av1_threads")),
        opus_bitrate=configured_text(settings, "opus_bitrate"),
    )
    if request.jobs < 0:
        raise ValueError("Concurrent downloads cannot be negative")
    try:
        upload_session = prepare.open_upload_session(request.upload, dry_run_mode=request.dry_run)
    except prepare.S3NotConfigured:
        print("[batch] S3 is not configured; continuing without uploads.")
        upload_session = None
    s3_config = upload_session.config if upload_session is not None else None
    s3_client = upload_session.client if upload_session is not None else None
    song_token = configured_text(settings, "song_api_token").strip()
    if request.update_song_links:
        if upload_session is None:
            raise RuntimeError("World Stage link updates require configured S3 uploads")
        if not song_token:
            raise ValueError("Configure a World Stage song API token before updating media links")
    else:
        song_token = ""
    if request.temporary_directory is not None:
        unavailable = download_one_batch(
            batch_input.videos, output_directory=request.output_directory, raw_directory=request.temporary_directory,
            downloader_settings=downloader_settings, ffprobe=ffprobe,
            encoding=encoding, jobs=request.jobs, s3_config=s3_config, s3_client=s3_client, song_api_token=song_token or None,
            overwrite=request.overwrite, dry_run=request.dry_run,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="world-stage-batch-") as temporary_path:
            unavailable = download_one_batch(
                batch_input.videos, output_directory=request.output_directory, raw_directory=Path(temporary_path),
                downloader_settings=downloader_settings, ffprobe=ffprobe,
                encoding=encoding, jobs=request.jobs, s3_config=s3_config, s3_client=s3_client, song_api_token=song_token or None,
                overwrite=request.overwrite, dry_run=request.dry_run,
            )
    print_report(unavailable, batch_input.missing_media_links)


def setup_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch-download and prepare World Stage files.")
    settings = app_config.recap_settings()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    downloader = subparsers.add_parser("download", help="Download and tag all available video rows")
    downloader.add_argument("input", type=Path, nargs="?", help="JSON or CSV show metadata")
    recap_api.add_cli_arguments(downloader)
    downloader.add_argument("--output-directory", "-o", type=Path, default=Path("output"))
    downloader.add_argument("--temporary-directory", type=Path)
    downloader.add_argument("--browser", help="Browser profile for YouTube cookies")
    downloader.add_argument("--ffmpeg", help="ffmpeg executable (defaults to saved setting)")
    downloader.add_argument("--ffprobe", help="ffprobe executable (defaults to saved setting)")
    downloader.add_argument("--jobs", type=int, default=0, help="Concurrent downloads (0 selects automatically)")
    downloader.add_argument("--upload", action=argparse.BooleanOptionalAction, default=prepare.s3_configured(), help="Upload completed files to configured S3")
    downloader.add_argument("--update-song-links", action=argparse.BooleanOptionalAction, default=bool(settings["song_api_token"]) and prepare.s3_configured(), help="Update uploaded media links through the World Stage song API")
    downloader.add_argument("--overwrite", "-y", action="store_true")
    downloader.add_argument("--dry-run", "-n", action="store_true")
    return parser


def main() -> None:
    args = setup_args().parse_args()
    if args.mode == "download":
        input_path, api_query = recap_api.source_from_cli(args, "input")
        download_videos(BatchDownloadRequest(
            input=input_path,
            api_query=api_query,
            output_directory=cast(Path, args.output_directory),
            temporary_directory=cast(Path | None, args.temporary_directory),
            browser=cast(str | None, args.browser),
            ffmpeg=cast(str | None, args.ffmpeg),
            ffprobe=cast(str | None, args.ffprobe),
            jobs=cast(int, args.jobs),
            upload=cast(bool, args.upload),
            update_song_links=cast(bool, args.update_song_links),
            overwrite=cast(bool, args.overwrite),
            dry_run=cast(bool, args.dry_run),
        ))
        return
    raise ValueError(f"Unsupported batch mode: {args.mode}")


if __name__ == "__main__":
    main()
