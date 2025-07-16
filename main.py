#!/usr/bin/env python3
import os
from pathlib import Path
from dataclasses import dataclass
import argparse
import time

import cards
import download
import recap
import common

@dataclass
class Args:
    csv: Path
    style: str
    tmpdir: Path
    browser: str | None
    po_token: str | None
    size: tuple[int, int]
    fps: int
    fade_duration: float
    output: Path
    multiprocessing: bool
    cleanup: bool
    stages: list[str]

def cleanup(tmp: Path) -> None:
    for root, dirs, files in tmp.walk(top_down=False):
        for name in files:
            (root / name).unlink()
        for name in dirs:
            (root / name).rmdir()

def exec(args: Args) -> None:
    start = time.time()
    # Download videos
    if "download" in args.stages:
        download.main(download.Args(
            csv_path=args.csv,
            output=args.tmpdir / "videos",
            browser=args.browser,
            multiprocessing=args.multiprocessing,
            po_token=args.po_token,
        ))

    # Create cards
    if "cards" in args.stages:
        cards.main(cards.Args(
            csv=args.csv,
            style=args.style,
            outdir=args.tmpdir / "cards",
            multiprocessing=args.multiprocessing,
            size=args.size,
        ))

    # Create recap video
    if "recap" in args.stages:
        recap.main(recap.Args(
            csv_path=args.csv,
            vids_dir=args.tmpdir / "videos",
            cards_dir=args.tmpdir / "cards",
            tmp_dir=args.tmpdir,
            output=args.output,
            size=args.size,
            fps=args.fps,
            multiprocessing=args.multiprocessing,
            fade_duration=args.fade_duration,
        ))

    # Cleanup temporary files
    if args.cleanup:
        cleanup(args.tmpdir)

    end = time.time()
    print(f"Total processing time: {end - start:.2f} seconds")

def setup_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process recap videos.")

    parser.add_argument("csv", help="CSV file with video metadata")
    parser.add_argument("--tmp", default="tmp", help="Temporary directory for clips and cards")
    parser.add_argument("--style", required=True, help="Style to use for the cards")
    parser.add_argument("--browser", default=None, help="Browser to use for downloads")
    parser.add_argument("--po-token", default="", help="PO token for YouTube downloads")
    parser.add_argument("--size", default="1920x1080", type=common.parse_size, help="Output video size WxH")
    parser.add_argument("--fps", type=int, default=60, help="Output video FPS")
    parser.add_argument("--fade-duration", type=float, default=0.25, help="Fade duration in seconds")
    parser.add_argument("--output", default="output", help="Output video file name")
    parser.add_argument("--multiprocessing", action='store_true', help="Use multiprocessing")
    parser.add_argument("--cleanup", action='store_true', help="Cleanup temporary files after processing")
    parser.add_argument("--stage", choices=["download", "cards", "recap"], action='append', default=[],
                        help="Stages to run (download, cards, recap). If not specified, all stages will be run.")

    return parser

def main() -> None:
    if os.name == 'nt' and not common.is_admin():
        common.elevate_via_uac()

    args = setup_args().parse_args()
    exec(Args(
        csv=Path(args.csv),
        style=args.style,
        tmpdir=Path(args.tmp),
        browser=args.browser,
        po_token=args.po_token,
        size=args.size,
        fps=args.fps,
        fade_duration=args.fade_duration,
        output=Path(args.output),
        multiprocessing=args.multiprocessing,
        cleanup=args.cleanup,
        stages=args.stage if args.stage else ["download", "cards", "recap"]
    ))

if __name__ == "__main__":
    main()