#!/usr/bin/env python3
from collections import defaultdict
import json
import os
from pathlib import Path
from dataclasses import dataclass
import argparse
import shutil
import sys
import time
from typing import Any

import cards
import download
import recap
#import thumbnails
import common

def cleanup(tmp: Path) -> None:
    for root, dirs, files in tmp.walk(top_down=False):
        for name in files:
            (root / name).unlink()
        for name in dirs:
            (root / name).rmdir()

def data_from_dict(obj: dict[str, Any]) -> common.Data:
    print(obj)
    try:
        type_tag = obj["type"]
    except KeyError:
        raise ValueError("Missing 'type' field")

    try:
        cls = common.CONSTRUCTORS[type_tag]
    except KeyError:
        raise ValueError(f"Unknown type: {type_tag!r}")

    kwargs = dict(obj)
    kwargs.pop("type")

    return cls(**kwargs)

def data_from_json(file: Path) -> list[common.Data]:
    with file.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    items = [data_from_dict(obj) for obj in raw]
    return items

def transform_data(data: list[common.Data]) -> dict[str, list[common.Data]]:
    dic = defaultdict(list)

    for d in data:
        dic[d.media_link].append(d)

    return dic

def exec(args: common.Args) -> None:
    if shutil.which(args.yt_dlp) is None:
        print(f"Error: {args.yt_dlp} not found", file=common.ERR_HANDLE)
        sys.exit(1)

    if shutil.which(args.ffmpeg) is None:
        print(f"Error: {args.ffmpeg} not found", file=common.ERR_HANDLE)
        sys.exit(1)

    if not shutil.which(args.inkscape):
        print(f"Error: {args.inkscape} not found", file=common.ERR_HANDLE)
        sys.exit(1)

    data = data_from_json(args.json)

    start = time.time()
    # Download videos
    clips = download.main(args, data)
    print(clips)

    # Create cards
    cards.main(args, data)

    return

    # Create recap video
    recap.main(clips, args)

    # Cleanup temporary files
    if args.cleanup:
        cleanup(args.tmpdir)

    end = time.time()
    print(f"Total processing time: {end - start:.2f} seconds", file=common.OUT_HANDLE)

STAGES = ["download", "cards", "recap", "thumbs", "show"]

def setup_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process recap videos.")

    parser.add_argument("json", type=Path, help="JSON file with video metadata")
    parser.add_argument("--tmp", '-t', type=Path, default="temp", help="Temporary directory for clips and cards")
    parser.add_argument("--style", '-S', default="70s", help="Style to use for the cards")
    parser.add_argument("--browser", '-b', default=None, help="Browser to use for downloads")
    parser.add_argument("--po-token", '-p', default="", help="PO token for YouTube downloads")
    parser.add_argument("--size", '-s', default="1280x720", type=common.parse_size, help="Output video size WxH")
    parser.add_argument("--fps", '-F', type=int, default=60, help="Output video FPS")
    parser.add_argument("--fade-duration", '-f', type=float, default=0.25, help="Fade duration in seconds")
    parser.add_argument("--output", '-o', type=Path, default="output", help="Output video file name")
    parser.add_argument("--multiprocessing", '-m', action='store_true', help="Use multiprocessing")
    parser.add_argument("--cleanup", '-c', action='store_true', help="Cleanup temporary files after processing")
    parser.add_argument("--only-direct", '-d', default=False, action="store_true", dest="direct", help="Only create a straight recap")
    parser.add_argument("--only-reverse", '-r', default=False, action="store_true", dest="reverse", help="Only create a reverse recap")
    parser.add_argument("--inkscape", default="inkscape", help="Path to the inkscape executable")
    parser.add_argument("--yt-dlp", default="yt-dlp", help="Path to the yt-dlp executable")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Path to the ffmpeg executable")
    parser.add_argument("--ffprobe", default="ffprobe", help="Path to the ffprobe executable")

    return parser

def main() -> None:
    if os.name == 'nt' and not common.is_admin():
        print("Please run this script as an administrator on Windows.", file=common.ERR_HANDLE)
        input("Press Enter to exit...")
        return

    args = setup_args().parse_args()

    if args.reverse and args.direct:
        print("--only-reverse and --only-straight parameters are mutually exclusive", file=sys.stderr)
        sys.exit(2)

    exec(common.Args(
        json=args.json,
        style=args.style,
        tmpdir=args.tmp,
        vidsdir=args.tmp / "videos",
        cardsdir=args.tmp / "cards",
        clipsdir=args.tmp / "clips",
        browser=args.browser,
        po_token=args.po_token,
        size=args.size,
        fps=args.fps,
        fade_duration=args.fade_duration,
        output=args.output,
        multiprocessing=args.multiprocessing,
        cleanup=args.cleanup,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        inkscape=args.inkscape,
        yt_dlp=args.yt_dlp,
        only_straight=args.direct,
        only_reverse=args.reverse,
    ))

if __name__ == "__main__":
    main()