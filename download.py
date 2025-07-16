#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
import re
import sys
import time
import csv
import shutil
import subprocess as sp
import multiprocessing as mp
from pathlib import Path

import common

@dataclass
class Data:
    ro: int
    year: int
    show: str
    country: str
    video_link: str

@dataclass
class Args:
    csv_path: Path
    output: Path
    browser: str | None
    multiprocessing: bool
    po_token: str | None

_YT_RE = re.compile(r"(?:youtube\.com\/watch.*?[?&]v=|youtu\.be\/)([\w-]{11})")
_GDRIVE_RE = re.compile(r"/d/([A-Za-z0-9_-]{10,})")

def youtube_id(url: str) -> str:
    m = _YT_RE.search(url)
    if not m:
        raise ValueError(f"Cannot parse YouTube id from: {url}")
    return m.group(1)

def download_video(url: str, name: str, out_dir: Path, browser: str | None, po_token: str | None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- YouTube -------------------------------------------------------------
    if "youtu" in url:
        vid = youtube_id(url)
        out_path = out_dir / name
        if not out_path.exists():
            print(f"[dl] YT {vid}")
            yt_dlp_args = [
                "yt-dlp", "-f", "bv*+ba/b"
            ]

            if po_token:
                yt_dlp_args.append("--extractor-args")
                yt_dlp_args.append("youtube:player-client=default,mweb;po_token={po_token}")

            if browser:
                yt_dlp_args.append("--cookies-from-browser")
                yt_dlp_args.append(browser)

            yt_dlp_args.append("--merge-output-format")
            yt_dlp_args.append("mp4")

            yt_dlp_args.append("-o")
            yt_dlp_args.append(str(out_path))

            yt_dlp_args.append(url)

            common.run(yt_dlp_args)
        return out_path

    # --- Google Drive --------------------------------------------------------
    m = _GDRIVE_RE.search(url)
    if m:
        fid = m.group(1)
        out_path = out_dir / name
        if not out_path.exists():
            print(f"[dl] GDrive {fid}")
            common.run(["gdown", "--id", fid, "-O", str(out_path)])
        return out_path

    # --- Direct link ---------------------------------------------------------
    filename = url.split("?")[0].rsplit("/", 1)[-1]
    out_path = out_dir / name
    if not out_path.exists():
        print(f"[dl] {filename}")
        common.run(["curl", "-L", "-o", str(out_path), url])
    return out_path

def main(args: Args) -> None:
    csv_path = Path(args.csv_path)
    with csv_path.open(newline='') as f:
        reader = csv.DictReader(f)
        data = [
            Data(
                ro=int(row["running_order"].strip()),
                year=int(row["year"].strip()),
                show=row["show"].strip(),
                country=row["country"].strip(),
                video_link=row["video_link"].strip(),
            )
            for row in reader
        ]

    data.sort(key=lambda x: int(x.ro))
    sz = len(data)

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"Processing {sz} clips...")
    start1 = time.time()

    if args.multiprocessing:
        mp.Pool(mp.cpu_count()).starmap(
            download_video,
            [(row.video_link, f"{row.year}_{row.show}_{row.ro:02d}_{row.country}.mp4", args.output, args.browser, args.po_token) for row in data]
        )
    else:
        for row in data:
            download_video(row.video_link, f"{row.year}_{row.show}_{row.ro:02d}_{row.country}.mp4", args.output, args.browser, args.po_token)

    end1 = time.time()

    print(f"Processed {sz} clips in {end1 - start1:.2f} seconds")

if __name__ == "__main__":
    if shutil.which("yt-dlp") is None:
        print("Error: yt-dlp is not installed.", file=sys.stderr)
        sys.exit(1)

    ap = argparse.ArgumentParser(
        description="Download videos."
    )
    ap.add_argument("csv", type=Path, help="CSV file with video metadata")
    ap.add_argument("outdir", type=Path, default="output", nargs="?",
                    help="Output directory for the downloaded videos")
    ap.add_argument("--browser",
                    help="Use cookies from the specified browser to download YouTube videos")
    ap.add_argument("--po-token", default="", help="YouTube PO token for downloading videos")
    ap.add_argument("--multiprocessing", action="store_true",
                    help="Use multiprocessing to speed up the processing of clips")
    args = ap.parse_args()

    ar = Args(
        csv_path=args.csv,
        output=args.outdir,
        multiprocessing=args.multiprocessing,
        browser=args.browser,
        po_token=args.po_token
    )
    try:
        start = time.time()
        main(ar)
        end = time.time()
        print(f"Total time: {end - start:.2f} seconds")
    except KeyboardInterrupt:
        sys.exit(130)