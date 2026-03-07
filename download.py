#!/usr/bin/env python3
import argparse
from collections import defaultdict
from dataclasses import dataclass
import re
import sys
import time
import csv
import multiprocessing as mp
from pathlib import Path
from typing import Callable, Iterable, TypeVar

import common

_YT_RE = re.compile(r"(?:youtube\.com\/watch.*?[?&]v=|youtu\.be\/)([\w-]{11})")
_GDRIVE_RE = re.compile(r"/d/([A-Za-z0-9_-]{10,})")

def youtube_id(url: str) -> str:
    m = _YT_RE.search(url)
    if not m:
        raise ValueError(f"Cannot parse YouTube id from: {url}")
    return m.group(1)

def download_video(data: common.Data, out_path: Path, args: common.Args) -> Path:
    url = data.media_link
    args.vidsdir.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        print(f"[dl] {out_path} already exists, skipping download.", file=common.OUT_HANDLE)
        return out_path

    dl_path = out_path.with_suffix(".temp.mp4")

    # --- YouTube -------------------------------------------------------------
    if "youtu" in url:
        vid = youtube_id(url)
        print(f"[dl] YT {vid}", file=common.OUT_HANDLE)
        yt_dlp_args = [
            args.yt_dlp, "-f", "bv*+ba/b"
        ]

        yt_dlp_args.append("--extractor-args")
        yt_dlp_args.append("youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416")

        if args.browser:
            yt_dlp_args.append("--cookies-from-browser")
            yt_dlp_args.append(args.browser)

        if args.ffmpeg != "ffmpeg":
            yt_dlp_args.append("--ffmpeg-location")
            yt_dlp_args.append(args.ffmpeg)

        yt_dlp_args.append("-f")
        yt_dlp_args.append("mp4")

        yt_dlp_args.append("-o")
        yt_dlp_args.append(str(dl_path))

        yt_dlp_args.append(url)

        common.run(yt_dlp_args)

    # --- Google Drive --------------------------------------------------------
    elif m := _GDRIVE_RE.search(url):
        fid = m.group(1)
        print(f"[dl] GDrive {fid}", file=common.OUT_HANDLE)
        common.run(["gdown", "--id", fid, "-O", str(dl_path)])

    # --- Direct link ---------------------------------------------------------
    else:
        filename = url.split("?")[0].rsplit("/", 1)[-1]
        print(f"[dl] {filename}", file=common.OUT_HANDLE)
        common.run(["curl", "-L", "-o", str(dl_path), url])

    out_path.hardlink_to(dl_path)
    dl_path.unlink()

    return out_path

def link_existing_clip(existing: Path, new: Path) -> Path:
    if new.exists(follow_symlinks=False):
        print(f"[dl] {new} already exists, skipping link creation.", file=common.OUT_HANDLE)
    else:
        new.parent.mkdir(parents=True, exist_ok=True)
        print(f"[dl] Linking {existing} to {new}", file=common.OUT_HANDLE)
        new.symlink_to(existing.absolute())

    return new

def create_filename(row: common.Data, path: Path) -> Path:
    p = path / row.show / f"{row.ro}_{row.cc}.{row.ext()}"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def download_many(data: list[common.Data], args: common.Args) -> list[common.Data]:
    ret = []
    this = data[0]

    name = create_filename(this, args.vidsdir)
    master = download_video(this, name, args)
    this.video_path = master
    ret.append(this)
    for row in data[1:]:
        new_name = create_filename(row, args.vidsdir)
        p = link_existing_clip(master, new_name)
        row.video_path = p
        ret.append(row)
    return ret

def main(args: common.Args, data: list[common.Data]) -> list[common.Data]:
    sz = 0

    args.vidsdir.mkdir(parents=True, exist_ok=True)

    vals = common.group_by(data, lambda v: v.media_link)

    start1 = time.time()

    if args.multiprocessing:
        clips = [x
            for xs in mp.Pool(mp.cpu_count()//2).starmap(
                download_many,
                [(v, args) for v in vals.values()]
            )
            for x in xs
            ]
    else:
        clips = []
        for v in vals.values():
            clips.extend(download_many(v, args))

    end1 = time.time()

    print(f"[dl] Processed {sz} clips in {end1 - start1:.2f} seconds", file=common.OUT_HANDLE)

    return data
