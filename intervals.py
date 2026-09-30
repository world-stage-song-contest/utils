#!/usr/bin/env python3
"""Download opening and interval acts, prepare CDN artifacts, and update shows."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
import csv
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import app_config
import common
import download
import ffmpeg_tools
import prepare
import show_api
import song_api


FIELDS: tuple[str, ...] = ("year", "show", "interval", "title", "url")


@dataclass(frozen=True)
class Interval:
    year: str
    show: str
    interval: int
    title: str
    url: str

    @property
    def display_title(self) -> str:
        prefix = "Opening" if self.interval == 0 else f"Interval {self.interval}"
        return f"{prefix}: {self.title}"

    @property
    def key(self) -> str:
        return f"intervals/{self.year}/{self.show}/i{self.interval}"


@dataclass(frozen=True)
class IntervalDownloadRequest:
    entries: list[Interval]
    output_directory: Path = Path("output")
    target_height: int = 576
    upload: bool = True
    dry_run: bool = False


def parse_rows(rows: Iterable[object]) -> list[Interval]:
    entries: list[Interval] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise ValueError(f"Row {index}: expected an object")
        values = {field: str(row.get(field, "") or "").strip() for field in FIELDS}
        # Numeric zero is a valid opening number, including in JSON input.
        values["interval"] = str(row.get("interval", "")).strip()
        try:
            show_api.validate_show(values["year"], values["show"])
            if not re.fullmatch(r"[0-9]+", values["interval"]):
                raise ValueError("Interval number must be a nonnegative integer (0 is the opening)")
            if not values["title"]:
                raise ValueError("Title is required")
            url = urlsplit(values["url"])
            if url.scheme not in {"http", "https"} or not url.netloc:
                raise ValueError("URL must be an HTTP or HTTPS download link")
            entry = Interval(values["year"], values["show"], int(values["interval"]), values["title"], values["url"])
            if entry.key in seen:
                raise ValueError(f"Duplicate interval: {entry.year}/{entry.show}/i{entry.interval}")
        except ValueError as exc:
            raise ValueError(f"Row {index}: {exc}") from exc
        seen.add(entry.key)
        entries.append(entry)
    if not entries:
        raise ValueError("Add at least one opening or interval")
    return entries


def load_entries(path: Path) -> list[Interval]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        if path.suffix.lower() == ".csv":
            return parse_rows(csv.DictReader(source))
        rows = json.load(source)
    if not isinstance(rows, list):
        raise ValueError("Expected a JSON array of interval rows")
    return parse_rows(rows)


def save_entries(path: Path, entries: list[Interval]) -> None:
    rows = [asdict(entry) for entry in entries]
    with path.open("w", encoding="utf-8", newline="") as output:
        if path.suffix.lower() == ".csv":
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        else:
            output.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")


def metadata_payload(entries: list[Interval]) -> dict[str, object]:
    payload: dict[str, object] = {
        "intervals": [song_api.media_url(f"{entry.key}.json")
                      for entry in sorted(entries, key=lambda entry: entry.interval) if entry.interval > 0],
    }
    for entry in entries:
        if entry.interval == 0:
            payload["opening"] = song_api.media_url(f"{entry.key}.json")
    return payload


def prepare_interval(
    entry: Interval, output_directory: Path, settings: download.DownloadSettings,
    media: ffmpeg_tools.FFmpeg, encoding: ffmpeg_tools.RecapEncoding,
) -> list[Path]:
    """Stage a complete set of artifacts before replacing existing local files."""
    destination = output_directory / entry.key
    destination.parent.mkdir(parents=True, exist_ok=True)
    tags = ffmpeg_tools.MediaTags(
        title=entry.display_title, artist="", album=f"World Stage {entry.year} {entry.show}",
        keywords=f"{entry.year};{entry.show}", date=entry.year, location="", language="und",
    )
    with tempfile.TemporaryDirectory(prefix=".interval-", dir=destination.parent) as temporary:
        work = Path(temporary)
        topic = download.youtube_topic_upload(entry.url, settings)
        cover = None
        if topic is not None:
            raw = work / "source.m4a"
            download.fetch_external(entry.url, "a", raw, replace(settings, prefer_av1_opus=False))
            thumbnail = work / f"thumbnail{topic.thumbnail_suffix}"
            download.download_direct(topic.thumbnail_url, thumbnail)
            # Topic thumbnails can be WebP; publish only the requested PNG/JPEG formats.
            cover = work / f"{destination.name}.{'png' if topic.thumbnail_suffix == '.png' else 'jpeg'}"
            if topic.thumbnail_suffix in {".jpg", ".jpeg", ".png"}:
                thumbnail.replace(cover)
            else:
                media.run([media.executable, "-y", "-hide_banner", "-i", str(thumbnail),
                           "-frames:v", "1", str(cover)])
            output = work / f"{destination.name}.m4a"
            media.make_audio(cover, raw, output, tags)
        else:
            raw = work / "source.mov"
            download.fetch_external(entry.url, "v", raw, settings)
            output = work / f"{destination.name}.mov"
            media.make_av1_opus_video(
                raw, output, tags, encoding, preserve_flac=download.is_google_drive_url(entry.url),
                maximum_height=settings.maximum_video_height,
            )
        metadata = prepare.write_json(
            json_path=work / f"{destination.name}.json", base_name=entry.key,
            artist="", title=entry.display_title, display_title=entry.display_title,
            duration=media.duration(output), mode="audio" if cover else "video",
            image_name=f"{entry.key}{cover.suffix}" if cover else "", overwrite_existing=True,
        )
        artifacts = [output] + ([cover] if cover else []) + [metadata]
        return [path.replace(destination.parent / path.name) for path in artifacts]


def execute(request: IntervalDownloadRequest) -> None:
    entries = parse_rows(asdict(entry) for entry in request.entries)
    if request.target_height <= 0:
        raise ValueError("Target video height must be positive")
    settings = app_config.recap_settings()
    token = str(settings["song_api_token"]).strip()
    if request.upload and not token and not request.dry_run:
        raise ValueError("Configure the World Stage API token in Settings before uploading intervals")
    session = prepare.open_upload_session(request.upload, dry_run_mode=request.dry_run)
    downloader = download.DownloadSettings(
        browser=str(settings["browser"]) or None, ffmpeg=str(settings["ffmpeg"]), prefer_av1_opus=True,
        youtube_attestation_mode=str(settings["youtube_attestation_mode"]),
        po_token=str(settings["po_token"]) or None, bgutil_url=str(settings["bgutil_url"]) or None,
        maximum_video_height=request.target_height,
    )
    encoding = ffmpeg_tools.RecapEncoding(
        int(str(settings["av1_preset"])), int(str(settings["av1_crf"])),
        int(str(settings["av1_threads"])), str(settings["opus_bitrate"]),
    )
    media = ffmpeg_tools.FFmpeg(downloader.ffmpeg, str(settings["ffprobe"]), common.run)
    groups: dict[tuple[str, str], list[Interval]] = defaultdict(list)
    for entry in entries:
        groups[(entry.year, entry.show)].append(entry)
    for (year, show), group in groups.items():
        for entry in sorted(group, key=lambda entry: entry.interval):
            print(f"[intervals] {entry.display_title}: {entry.url} -> {request.output_directory / entry.key}")
            if request.dry_run:
                if session is not None:
                    print(f"[intervals] Would upload artifacts to s3://{session.config.bucket}/{entry.key}.*")
                continue
            artifacts = prepare_interval(entry, request.output_directory, downloader, media, encoding)
            if session is not None:
                for path in artifacts:
                    prepare.upload(path, session.config, session.client, object_name=f"{entry.key}{path.suffix}")
        # Never publish a partial interval list if a source, encoding or upload failed.
        if session is not None:
            payload = metadata_payload(group)
            if request.dry_run:
                print(f"[intervals] Would PUT {show_api.SHOW_API_URL}/{year}-{show}/metadata: {json.dumps(payload)}")
            else:
                show_api.update_metadata(token, year, show, payload)
                print(f"[intervals] Updated World Stage show {year}-{show}")


def setup_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON or CSV table with year, show, interval, title, url")
    parser.add_argument("-o", "--output-directory", type=Path, default=Path("output"))
    parser.add_argument("--target-height", type=int, default=576, help="Maximum video height (default: 576)")
    parser.add_argument("--no-upload", action="store_true", help="Prepare local files without uploading or updating the API")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Preview downloads, uploads and API payloads")
    return parser


def main() -> None:
    parser = setup_args()
    args = parser.parse_args()
    try:
        execute(IntervalDownloadRequest(
            load_entries(args.input), args.output_directory, args.target_height, not args.no_upload, args.dry_run,
        ))
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
