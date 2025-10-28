#!/usr/bin/env python3
import os
from pathlib import Path
from dataclasses import dataclass
import argparse
import shutil
import sys
import time

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

    start = time.time()
    # Download videos
    clips = download.main(args)

    # Create cards
    cards.main(args)

    # Create thumbnails
    #thumbnails.main(args)

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

    parser.add_argument("csv", type=Path, help="CSV file with video metadata")
    parser.add_argument("--tmp", type=Path, default="temp", help="Temporary directory for clips and cards")
    parser.add_argument("--common", type=Path, default="common", help="Common directory for shared resources")
    parser.add_argument("--postcards", type=Path, default="postcards.csv", help="File with postcard video links")
    parser.add_argument("--style", required=True, help="Style to use for the cards")
    parser.add_argument("--browser", default=None, help="Browser to use for downloads")
    parser.add_argument("--po-token", default="", help="PO token for YouTube downloads")
    parser.add_argument("--size", default="1920x1080", type=common.parse_size, help="Output video size WxH")
    parser.add_argument("--fps", type=int, default=60, help="Output video FPS")
    parser.add_argument("--fade-duration", type=float, default=0.25, help="Fade duration in seconds")
    parser.add_argument("--output", type=Path, default="output", help="Output video file name")
    parser.add_argument("--multiprocessing", action='store_true', help="Use multiprocessing")
    parser.add_argument("--cleanup", action='store_true', help="Cleanup temporary files after processing")
    parser.add_argument("--straight", default=True, action="store_true", help="Create a straight recap")
    parser.add_argument("--no-straight", action="store_false", dest="straight", help="Do not create a straight recap")
    parser.add_argument("--reverse", default=True, action="store_true", help="Create a reverse recap")
    parser.add_argument("--no-reverse", action="store_false", dest="reverse", help="Do not create a reverse recap")
    parser.add_argument("--inkscape", default="inkscape", help="Path to the inkscape executable")
    parser.add_argument("--yt-dlp", default="yt-dlp", help="Path to the yt-dlp executable")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Path to the ffmpeg executable")
    parser.add_argument("--thumb", type=Path, help="Thumbnail background image")
    parser.add_argument("--flags", type=Path, help="Directory that contains flags")

    return parser

def main() -> None:
    if os.name == 'nt' and not common.is_admin():
        print("Please run this script as an administrator on Windows.", file=common.ERR_HANDLE)
        input("Press Enter to exit...")
        return

    args = setup_args().parse_args()
    exec(common.Args(
        csv=args.csv,
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
        inkscape=args.inkscape,
        yt_dlp=args.yt_dlp,
        straight=args.straight,
        reverse=args.reverse,
        commondir=args.common,
        postcards=args.postcards,
        thumb=args.thumb,
        flagsdir=args.flags,
    ))

if __name__ == "__main__":
    main()