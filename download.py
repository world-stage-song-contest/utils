#!/usr/bin/env python3
import argparse
from collections import defaultdict
from dataclasses import dataclass
import re
import sys
import time
import csv
import shutil
import os
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
    yt_dlp: str
    ffmpeg: str

_YT_RE = re.compile(r"(?:youtube\.com\/watch.*?[?&]v=|youtu\.be\/)([\w-]{11})")
_GDRIVE_RE = re.compile(r"/d/([A-Za-z0-9_-]{10,})")

def youtube_id(url: str) -> str:
    m = _YT_RE.search(url)
    if not m:
        raise ValueError(f"Cannot parse YouTube id from: {url}")
    return m.group(1)

def download_video(url: str, name: str, out_dir: Path, browser: str | None, po_token: str | None, yt_dlp: str, ffmpeg: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / name
    if out_path.exists():
        print(f"[dl] {name} already exists, skipping download.", file=common.OUT_HANDLE)
        return out_path

    # --- YouTube -------------------------------------------------------------
    if "youtu" in url:
        vid = youtube_id(url)
        print(f"[dl] YT {vid}", file=common.OUT_HANDLE)
        yt_dlp_args = [
            yt_dlp, "-f", "bv*+ba/b"
        ]

        if po_token:
            yt_dlp_args.append("--extractor-args")
            yt_dlp_args.append("youtube:player-client=default,mweb;po_token={po_token}")

        if browser:
            yt_dlp_args.append("--cookies-from-browser")
            yt_dlp_args.append(browser)

        if ffmpeg != "ffmpeg":
            yt_dlp_args.append("--ffmpeg-location")
            yt_dlp_args.append(ffmpeg)

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
        print(f"[dl] GDrive {fid}", file=common.OUT_HANDLE)
        common.run(["gdown", "--id", fid, "-O", str(out_path)])
        return out_path

    # --- Direct link ---------------------------------------------------------
    filename = url.split("?")[0].rsplit("/", 1)[-1]
    print(f"[dl] {filename}", file=common.OUT_HANDLE)
    common.run(["curl", "-L", "-o", str(out_path), url])
    return out_path

def link_existing_clip(existing: Path, new: str) -> None:
    if not existing.exists():
        raise FileNotFoundError(f"Existing clip {existing} does not exist.")
    new_path = existing.parent / new
    if new_path.exists(follow_symlinks=False):
        print(f"[dl] {new} already exists, skipping link creation.", file=common.OUT_HANDLE)
        return
    print(f"[dl] Linking {existing} to {new}", file=common.OUT_HANDLE)
    os.link(existing, new_path)

def create_filename(row: Data) -> str:
    return f"{row.year}_{row.show}_{row.ro:02d}_{row.country}.mp4"

def download_many(data: list[Data], out_dir: Path, browser: str | None, po_token: str | None, yt_dlp: str, ffmpeg: str) -> None:
    this = data[0]
    name = create_filename(this)
    master = download_video(this.video_link, name, out_dir, browser, po_token, yt_dlp, ffmpeg)
    for row in data[1:]:
        new_name = create_filename(row)
        link_existing_clip(master, new_name)

def main(args: Args) -> None:
    csv_path = Path(args.csv_path)
    data = defaultdict(list)
    sz = 0
    with csv_path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sz += 1
            video_link = row["video_link"].strip()
            val = Data(
                ro=int(row["running_order"].strip()),
                year=int(row["year"].strip()),
                show=row["show"].strip(),
                country=row["country"].strip(),
                video_link=video_link,
            )
            data[video_link].append(val)

    args.output.mkdir(parents=True, exist_ok=True)

    print(f"[dl] Found {sz} clips in {csv_path}", file=common.OUT_HANDLE)
    start1 = time.time()

    if args.multiprocessing:
        mp.Pool(mp.cpu_count()).starmap(
            download_many,
            [(v, args.output, args.browser, args.po_token, args.yt_dlp, args.ffmpeg) for v in data.values()]
        )
    else:
        for v in data.values():
            download_many(v, args.output, args.browser, args.po_token, args.yt_dlp, args.ffmpeg)

    end1 = time.time()

    print(f"[dl] Processed {sz} clips in {end1 - start1:.2f} seconds", file=common.OUT_HANDLE)

if __name__ == "__main__":
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
    ap.add_argument("--yt-dlp", default="yt-dlp", help="Path to the yt-dlp executable")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="Path to the ffmpeg executable")
    args = ap.parse_args()

    if shutil.which(args.yt_dlp) is None:
        print(f"Error: {args.yt_dlp} not found", file=common.ERR_HANDLE)
        sys.exit(1)

    if shutil.which(args.ffmpeg) is None:
        print(f"Error: {args.ffmpeg} not found", file=common.ERR_HANDLE)
        sys.exit(1)

    ar = Args(
        csv_path=args.csv,
        output=args.outdir,
        multiprocessing=args.multiprocessing,
        browser=args.browser,
        po_token=args.po_token,
        ffmpeg=args.ffmpeg,
        yt_dlp=args.yt_dlp
    )
    try:
        start = time.time()
        main(ar)
        end = time.time()
        print(f"Total time: {end - start:.2f} seconds", file=common.OUT_HANDLE)
    except KeyboardInterrupt:
        sys.exit(130)