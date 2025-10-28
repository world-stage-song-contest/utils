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

import common

@dataclass
class Data:
    ro: str
    year: int
    show: str
    country: str
    country_name: str
    cc: str
    video_link: str
    artist: str
    title: str

    def with_other(self, **kwargs) -> 'Data':
        ret = Data(
            ro=self.ro,
            year=self.year,
            show=self.show,
            country=self.country,
            cc=self.cc,
            country_name=self.country_name,
            video_link=self.video_link,
            artist=self.artist,
            title=self.title,
        )

        for k, v in kwargs.items():
            setattr(ret, k, v)

        return ret

def get_known_name_path(name: str, data: Data, args: common.Args) -> Path | None:
    if name in ["recap", "recap_rev"]:
        return args.vidsdir / f"{data.year}_{data.show}_{name}.mp4"
    elif name in ["silence", "timer"]:
        return args.commondir / f"{name}.mp4"
    elif name == "opening":
        return args.commondir / f"{data.year}_opening.mp4"

    return None

_YT_RE = re.compile(r"(?:youtube\.com\/watch.*?[?&]v=|youtu\.be\/)([\w-]{11})")
_GDRIVE_RE = re.compile(r"/d/([A-Za-z0-9_-]{10,})")

def youtube_id(url: str) -> str:
    m = _YT_RE.search(url)
    if not m:
        raise ValueError(f"Cannot parse YouTube id from: {url}")
    return m.group(1)

def is_single_frame(path: Path) -> bool:
    p = common.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
             "-show_entries", "stream=nb_read_frames",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)])
    return p.stdout.strip() == "1"

def detect_colour_format(path: Path) -> tuple[str, str]:
    """ffprobe -v 0 -select_streams v:0 -show_entries \
        stream=pix_fmt,color_range -of csv=p=0 "$f"""

    p = common.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt,color_range",
             "-of", "csv=p=0", str(path)])
    try:
        pix_fmt, color_range, *_ = p.stdout.strip().split(',')
        return pix_fmt, color_range
    except ValueError:
        raise RuntimeError(f"Cannot parse colour format from: {path}")

def clip_duration(path: Path) -> float:
    p = common.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(p.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Cannot parse duration from: {path}")

def build_vf(target_w: int, target_h: int, fps: int) -> str:
    """
    square-pixels → fit/pad to 16:9 → overlay → optional fade-in/out
    → constant-fps → yuv420p   ==> label [v]
    """
    r = f"{target_w}/{target_h}"
    filt = []

    # 1. square the pixels
    filt.append("[0:v]scale=w='ceil(iw*sar/2)*2':h='ceil(ih/2)*2'"
                ":flags=lanczos,setsar=1[v]")

    # 2. fit & pad
    filt.append(f"[v]scale=w='if(gt(a,{r}),{target_w},-2)':"
                f"h='if(gt(a,{r}),-2,{target_h})':flags=lanczos,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[v]")

    # 3. constant fps + pixel format
    filt.append(f"[v]fps=fps={fps},format=yuv420p[v]")
    return ";".join(filt)

def build_af(index: int) -> str:
    """
    loudnorm → optional afade-in/out   ==> label [a]
    """
    chain = f"[{index}:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    return chain

shared_flags = [
    "-color_range", "tv", "-color_primaries", "bt709",
    "-color_trc", "bt709", "-colorspace", "bt709",
    "-c:v", "libx264", "-tune", "stillimage", "-crf", "18",
    "-ac", "2", "-c:a", "aac", "-b:a", "192k",
    "-shortest", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", "-fflags", "+genpts",
    "-avoid_negative_ts", "make_zero",
    "-video_track_timescale", "90000",
]

def process_single_frame(clip: Path, result: Path, args: common.Args) -> None:
    w, h = args.size
    print(f"[post] {clip} is a single frame, creating a normal video.", file=common.OUT_HANDLE)
    still = clip.with_suffix(".still.png")
    common.run([args.ffmpeg, "-hide_banner", "-y",
                "-i", str(clip), "-frames:v", "1", "-q:v", "2", str(still)])

    common.run([args.ffmpeg, "-hide_banner", "-y",
                "-loop", "1", "-framerate", str(args.fps),
                "-i", str(still), "-i", str(clip),
                "-vf", f"[0:v]scale=w='if(gt(a,{w}/{h}),{w},-2)':"
                        f"h='if(gt(a,{w}/{h}),-2,{h})':flags=lanczos,"
                        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[v]",
                *shared_flags,
                str(result)])

    still.unlink()

def postprocess_clip(clip: Path, out: Path, data: Data, args: common.Args, *, unlink: bool = False) -> None:
    result = out.with_suffix(".post.mp4")
    if is_single_frame(clip):
        process_single_frame(clip, result, args)
    else:
        pixel_format, colour_range = detect_colour_format(clip)
        extra_vf = ""
        extra_flags = []
        if pixel_format == "yuvj420p" and colour_range == "pc":
            extra_vf = "[v]zscale=in_range=pc:out_range=tv,format=yuv420p[v]"
        else:
            extra_flags = [
                "-bsf:v", "h264_metadata=video_full_range_flag=0:"
                          "colour_primaries=1:transfer_characteristics=1:"
                          "matrix_coefficients=1"
            ]
        w, h = args.size
        vf = build_vf(w, h, args.fps)
        af = build_af(0)
        common.run([
            args.ffmpeg, "-hide_banner", "-y",
            "-i", str(clip), "-filter_complex", f"{vf}{extra_vf};{af}",
            "-map", "[v]", "-map", "[a]", "-r", str(args.fps),
             *extra_flags, *shared_flags,
            str(result)
        ])
    result.rename(out)
    if unlink:
        clip.unlink(missing_ok=True)

def download_video(data: Data, out_path: Path, args: common.Args) -> Path:
    url = data.video_link
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

    postprocess_clip(dl_path, out_path, data, args, unlink=True)

    return out_path

def link_existing_clip(existing: Path, new: Path) -> Path:
    if new.exists(follow_symlinks=False):
        print(f"[dl] {new} already exists, skipping link creation.", file=common.OUT_HANDLE)
        return new
    new.parent.mkdir(parents=True, exist_ok=True)
    print(f"[dl] Linking {existing} to {new}", file=common.OUT_HANDLE)
    new.symlink_to(existing.absolute())
    return new

def create_filename(row: Data, path: Path) -> Path:
    p = path / f"{row.year}" / row.show / f"{row.ro}_{row.country}.mov"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def download_many(data: list[Data], args: common.Args) -> list[tuple[int, str, str, Path]]:
    ret = []
    this = data[0]
    source = get_known_name_path(this.video_link, this, args)
    if source:
        for d in data:
            name = create_filename(d, args.vidsdir)
            postprocess_clip(source, name, d, args, unlink=False)
            ret.append((d.year, d.show, d.country, name))
        return ret

    name = create_filename(this, args.vidsdir)
    master = download_video(this, name, args)
    ret.append((this.year, this.show, this.country, master))
    for row in data[1:]:
        new_name = create_filename(row, args.vidsdir)
        p = link_existing_clip(master, new_name)
        ret.append((row.year, row.show, row.country, p))
    return ret

def main(args: common.Args) -> common.Clips:
    data = defaultdict(list)
    ret: common.Clips = defaultdict(dict)
    sz = 0

    postcards = {}

    with args.postcards.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            postcards[row["code"].strip()] = row["video_link"].strip()

    with args.csv.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sz += 1
            video_link = row["video_link"].strip()
            raw_ro = row["running_order"].strip()
            try:
                ro = f"{int(raw_ro):02d}"
            except ValueError:
                ro = raw_ro
            val = Data(
                ro=ro,
                year=int(row["year"].strip()),
                show=row["show"].strip(),
                country=row["country"].strip(),
                cc=row["country_code"].strip(),
                video_link=video_link,
                artist=row["artist"].strip(),
                title=row["title"].strip(),
                country_name=row["country_name"].strip(),
            )

            data[video_link].append(val)

    args.vidsdir.mkdir(parents=True, exist_ok=True)

    print(f"[dl] Found {sz} clips in {args.csv}", file=common.OUT_HANDLE)
    start1 = time.time()

    if args.multiprocessing:
        clips = [x
            for xs in mp.Pool(mp.cpu_count()).starmap(
                download_many,
                [(v, args) for v in data.values()]
            )
            for x in xs
            ]
    else:
        clips = []
        for v in data.values():
            clips.extend(download_many(v, args))

    end1 = time.time()

    print(f"[dl] Processed {sz} clips in {end1 - start1:.2f} seconds", file=common.OUT_HANDLE)

    for year, show, country, path in clips:
        ret[(year, show)][country] = path

    return ret
