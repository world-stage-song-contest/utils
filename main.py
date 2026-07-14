#!/usr/bin/env python3
import os
from pathlib import Path
import argparse
import shutil
import sys
import time
import json

import cards
import download
import ffmpeg_tools
import recap
#import thumbnails
import app_config
import common
import prepare
import recap_api

def cleanup(tmp: Path) -> None:
    for root, dirs, files in tmp.walk(top_down=False):
        for name in files:
            (root / name).unlink()
        for name in dirs:
            (root / name).rmdir()


def even(value: float) -> int:
    return max(2, int(round(value / 2) * 2))


def video_properties(path: Path, args: common.Args) -> tuple[float, int]:
    cached = download.cached_display_properties(args.vidsdir, path)
    if cached is not None:
        return cached
    media = ffmpeg_tools.FFmpeg(args.ffmpeg, args.ffprobe, common.run)
    properties = media.video_properties(path)
    result = properties.display_aspect, properties.height
    download.store_display_properties(args.vidsdir, path, *result)
    return result


def resolve_output_size(clips: common.Clips, args: common.Args) -> None:
    """Use an explicit size verbatim, otherwise derive a canvas aspect ratio."""
    if args.size is not None:
        return

    videos: list[tuple[float, int, Path]] = []
    seen: set[Path] = set()
    for row in common.load_rows(args.csv):
        if row["type"] != "v":
            continue
        raw_ro = row["ro"].strip()
        try:
            ro = f"{int(raw_ro):02d}"
        except ValueError:
            ro = raw_ro
        path = clips[(row["show"].strip(), ro)][row["cc"].strip().upper()]
        if path in seen:
            continue
        seen.add(path)
        aspect, height = video_properties(path, args)
        videos.append((aspect, height, path))

    if videos:
        aspect, _height, source = max(videos, key=lambda value: value[0])
        _source_aspect, source_height, height_source = max(videos, key=lambda value: value[1])
        height = max(2, source_height - source_height % 2)
        args.size = (even(height * aspect), height)
        print(
            f"Selected output size {args.size[0]}x{args.size[1]} from widest source aspect ratio "
            f"{aspect:.5f} ({source}) and tallest source height {source_height} ({height_source}).",
            file=common.OUT_HANDLE,
        )
    else:
        height = even(args.default_height)
        args.size = (even(height * 16 / 9), height)
        print(
            f"No video entries found; using fallback output size {args.size[0]}x{args.size[1]}.",
            file=common.OUT_HANDLE,
        )

def exec(args: common.Args) -> None:
    if args.api_query is not None:
        if not isinstance(args.api_query, recap_api.ApiQuery):
            raise TypeError("api_query must be an ApiQuery")
        args.csv = recap_api.fetch_to_cache(args.api_query)
    if shutil.which(args.ffmpeg) is None:
        print(f"Error: {args.ffmpeg} not found", file=common.ERR_HANDLE)
        sys.exit(1)

    renderer_path = args.inkscape if args.card_renderer == "inkscape" else args.resvg
    if not shutil.which(renderer_path):
        print(f"Error: {renderer_path} not found", file=common.ERR_HANDLE)
        sys.exit(1)

    try:
        upload_session = prepare.open_upload_session(args.upload_recaps)
    except prepare.S3NotConfigured as exc:
        print(f"S3 is unavailable; continuing without recap uploads: {exc}", file=common.ERR_HANDLE)
        upload_session = None

    start = time.time()
    # Download videos
    clips = download.main(args)

    # Resolve an automatic canvas only after source video dimensions are known.
    resolve_output_size(clips, args)

    # Create cards
    cards.main(args)

    # Create thumbnails
    #thumbnails.main(args)

    # Create recap video
    recap_outputs = recap.main(clips, args)

    if upload_session is not None:
        # The preparation uploader already supplies content types and cache
        # checks.  Point its status handles at the recap process so GUI users
        # receive the same live upload messages as command-line users.
        prepare.OUT_HANDLE = common.OUT_HANDLE
        prepare.ERR_HANDLE = common.ERR_HANDLE
        for outputs in recap_outputs.values():
            for output in outputs:
                prepare.upload(
                    output, upload_session.config, upload_session.client, f"recaps/{output.name}",
                )

    # Cleanup temporary files
    if args.cleanup:
        cleanup(args.tmpdir)

    end = time.time()
    print(f"Total processing time: {end - start:.2f} seconds", file=common.OUT_HANDLE)

STAGES = ["download", "cards", "recap", "thumbs", "show"]

def setup_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process recap videos.")
    config = app_config.recap_settings()

    parser.add_argument("csv", type=Path, nargs="?", help="CSV or JSON file with recap metadata")
    recap_api.add_cli_arguments(parser)
    parser.add_argument("--tmp", '-t', type=Path, default="temp", help="Temporary directory for clips and cards")
    parser.add_argument("--style", '-S', default="70s", help="Style to use for the cards")
    parser.add_argument("--browser", '-b', default=config["browser"] or None, help="Browser to use for downloads")
    parser.add_argument("--youtube-attestation-mode", choices=["none", "po-token", "bgutil"], default=config["youtube_attestation_mode"], help="YouTube attestation provider")
    parser.add_argument("--po-token", '-p', default=config["po_token"], help="PO token for YouTube downloads")
    parser.add_argument("--bgutil-url", default=config["bgutil_url"], help="Optional bgutil attestation server URL for YouTube downloads")
    parser.add_argument("--size", '-s', type=common.parse_size, help="Output size WxH (overrides automatic aspect ratio)")
    parser.add_argument("--default-height", type=int, default=480, help="Default output height when all entries are audio")
    parser.add_argument("--fps", '-F', type=int, default=60, help="Output video FPS")
    parser.add_argument("--fade-duration", '-f', type=float, default=0.25, help="Fade duration in seconds")
    parser.add_argument("--av1-preset", type=int, default=config["av1_preset"], help="SVT-AV1 speed preset (higher is faster)")
    parser.add_argument("--av1-crf", type=int, default=config["av1_crf"], help="SVT-AV1 constant-quality value")
    parser.add_argument("--av1-threads", type=int, default=config["av1_threads"], help="SVT-AV1 threads per render (0 uses encoder default)")
    parser.add_argument("--opus-bitrate", default=config["opus_bitrate"], help="Recap Opus audio bitrate")
    parser.add_argument("--audio-normalization", choices=["none", "one-pass", "two-pass"], default=config["audio_normalization"], help="Recap audio loudness mode")
    parser.add_argument("--jobs", type=int, default=config["jobs"], help="Concurrent recap renders (0 selects automatically)")
    parser.add_argument("--output", '-o', type=Path, default="output", help="Output video file name")
    parser.add_argument("--multiprocessing", '-m', action='store_true', help="Use multiprocessing")
    parser.add_argument("--cleanup", '-c', action='store_true', help="Cleanup temporary files after processing")
    parser.add_argument("--only-direct", '-d', default=False, action="store_true", dest="direct", help="Only create a straight recap")
    parser.add_argument("--only-reverse", '-r', default=False, action="store_true", dest="reverse", help="Only create a reverse recap")
    parser.add_argument("--upload-recaps", action=argparse.BooleanOptionalAction, default=prepare.s3_configured(), help="Upload recaps to the configured S3 bucket")
    parser.add_argument("--inkscape", default=config["inkscape"], help="Path to the inkscape executable")
    parser.add_argument("--card-renderer", choices=["inkscape", "resvg"], default=config["card_renderer"], help="SVG-to-PNG renderer")
    parser.add_argument("--resvg", default=config["resvg"], help="Path to the rsvg-convert executable")
    parser.add_argument("--ffmpeg", default=config["ffmpeg"], help="Path to the ffmpeg executable")
    parser.add_argument("--ffprobe", default=config["ffprobe"], help="Path to the ffprobe executable")

    return parser


def setup_configure_args() -> argparse.ArgumentParser:
    """Create the persistent recap-settings CLI without requiring a show file."""
    parser = argparse.ArgumentParser(description="Read or update recap-maker defaults.")
    parser.add_argument("--show", action="store_true", help="Print the current configuration and exit")
    parser.add_argument("--browser", default=argparse.SUPPRESS)
    parser.add_argument("--youtube-attestation-mode", choices=["none", "po-token", "bgutil"], default=argparse.SUPPRESS)
    parser.add_argument("--po-token", default=argparse.SUPPRESS)
    parser.add_argument("--bgutil-url", default=argparse.SUPPRESS)
    parser.add_argument("--song-api-token", default=argparse.SUPPRESS)
    parser.add_argument("--av1-preset", default=argparse.SUPPRESS)
    parser.add_argument("--av1-crf", default=argparse.SUPPRESS)
    parser.add_argument("--av1-threads", default=argparse.SUPPRESS)
    parser.add_argument("--opus-bitrate", default=argparse.SUPPRESS)
    parser.add_argument("--audio-normalization", choices=["none", "one-pass", "two-pass"], default=argparse.SUPPRESS)
    parser.add_argument("--jobs", default=argparse.SUPPRESS)
    parser.add_argument("--inkscape", default=argparse.SUPPRESS)
    parser.add_argument("--card-renderer", choices=["inkscape", "resvg"], default=argparse.SUPPRESS)
    parser.add_argument("--resvg", default=argparse.SUPPRESS)
    parser.add_argument("--ffmpeg", default=argparse.SUPPRESS)
    parser.add_argument("--ffprobe", default=argparse.SUPPRESS)
    return parser

def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "configure":
        args = setup_configure_args().parse_args(sys.argv[2:])
        if args.show:
            settings = app_config.recap_settings()
            if settings["song_api_token"]:
                settings["song_api_token"] = "********"
            print(json.dumps(settings, indent=2))
            return
        values = {key: value for key, value in vars(args).items() if key != "show"}
        if not values:
            print("No settings supplied. Use --show to view current settings.", file=sys.stderr)
            sys.exit(2)
        path = app_config.update_recap_settings(values)
        print(f"Saved recap configuration to {path}")
        return

    if os.name == 'nt' and not common.is_admin():
        print("Please run this script as an administrator on Windows.", file=common.ERR_HANDLE)
        input("Press Enter to exit...")
        return

    args = setup_args().parse_args()

    csv, api_query = recap_api.source_from_cli(args, "csv")

    if args.reverse and args.direct:
        print("--only-reverse and --only-straight parameters are mutually exclusive", file=sys.stderr)
        sys.exit(2)

    exec(common.Args(
        csv=csv,
        api_query=api_query,
        style=args.style,
        tmpdir=args.tmp,
        vidsdir=args.tmp / "sources",
        cardsdir=args.tmp / "cards",
        clipsdir=args.tmp / "clips",
        browser=args.browser,
        youtube_attestation_mode=args.youtube_attestation_mode,
        po_token=args.po_token or None,
        bgutil_url=args.bgutil_url or None,
        size=args.size,
        default_height=args.default_height,
        fps=args.fps,
        fade_duration=args.fade_duration,
        av1_preset=args.av1_preset,
        av1_crf=args.av1_crf,
        av1_threads=args.av1_threads,
        opus_bitrate=args.opus_bitrate,
        audio_normalization=args.audio_normalization,
        jobs=args.jobs,
        output=args.output,
        multiprocessing=args.multiprocessing,
        cleanup=args.cleanup,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        inkscape=args.inkscape,
        card_renderer=args.card_renderer,
        resvg=args.resvg,
        only_straight=args.direct,
        only_reverse=args.reverse,
        upload_recaps=args.upload_recaps,
    ))

if __name__ == "__main__":
    main()
