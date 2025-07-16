#!/usr/bin/env python3
import argparse
from collections import defaultdict
from dataclasses import dataclass
import os
import shutil
import sys
import time
import csv
import multiprocessing as mp
from pathlib import Path
from typing import List, Tuple

import common

@dataclass
class Data:
    ro: int
    year: int
    show: str
    country: str
    artist: str
    title: str
    snippet_start: float
    snippet_end: float

@dataclass
class Args:
    csv_path: Path
    vids_dir: Path
    cards_dir: Path
    tmp_dir: Path
    output: Path
    size: Tuple[int, int]
    fps: int
    multiprocessing: bool
    fade_duration: float

def hms(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"

def build_vf(target_w: int, target_h: int, fps: int,
             dur: float, fade_dur: float) -> str:
    """
    square-pixels → fit/pad to 16:9 → overlay → optional fade-in/out
    → constant-fps → yuv420p   ==> label [v]
    """
    r169 = target_w / target_h        # 1.777…
    filt = []

    # 1. square the pixels
    filt.append("[0:v]scale=w='ceil(iw*sar/2)*2':h='ceil(ih/2)*2'"
                ":flags=lanczos,setsar=1[sq]")

    # 2. fit & pad
    filt.append(f"[sq]scale="
                f"w='if(gt(a,{r169:.6f}),{target_w},-2)':"
                f"h='if(gt(a,{r169:.6f}),-2,{target_h})':flags=lanczos,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2[fit]")

    # 3. overlay (card scaled 92.5 %)
    filt.append("[1:v]scale=iw*0.925:ih*0.925[ol]")
    filt.append("[fit][ol]overlay=(W-w)/2:(H-h)/2:format=auto[ovl]")

    # 4. optional fades (use the *current* label each time)
    filt.append(f"[ovl]fade=t=in:st=0:d={fade_dur:.3f}[fi]")
    filt.append(f"[fi]fade=t=out:st={dur-fade_dur:.3f}:d={fade_dur:.3f}[fo]")

    # 5. constant fps + pixel format
    filt.append(f"[fo]fps=fps={fps},format=yuv420p[v]")
    return ";".join(filt)

def build_af(dur: float, fade_dur: float) -> str:
    """
    loudnorm → optional afade-in/out   ==> label [a]
    """
    chain = ("[0:a]loudnorm=I=-14:TP=-1.5:LRA=11"
             f",afade=t=in:st=0:d={fade_dur:.3f}"
             f",afade=t=out:st={dur-fade_dur:.3f}:d={fade_dur}[a]")
    return chain


def process_clip(out_: Path, src: Path, overlay: Path,
                 start: float, end: float, size: Tuple[int, int],
                 fps: int, fade_dur: float) -> None:
    if not overlay.exists():
        raise FileNotFoundError(f"Overlay not found: {overlay}")
    w, h = size
    dur = end - start
    vf = build_vf(w, h, fps, dur, fade_dur)
    af = build_af(dur, fade_dur)
    common.run([
        "ffmpeg", "-hide_banner", "-y", "-ss", hms(start), "-to", hms(end),
        "-i", str(src), "-i", str(overlay),
        "-filter_complex", f"{vf};{af}",
        "-map", "[v]", "-map", "[a]", "-r", str(fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", str(out_)
    ])

def make_country_data(data: Data, prev_duration: float, fade_duration: float) -> str:
    end = prev_duration + int(data.snippet_end - data.snippet_start) + fade_duration
    return f"""
[CHAPTER]
TIMEBASE=1/1000
START={prev_duration * 1000:.0f}
END={end * 1000:.0f}
title={common.schemes[data.country].name}: {data.artist} - {data.title}
"""

def make_chapter_data(data: List[Data], args: Args, out_: Path):
    prev_duration = 1.0
    chapters = [';FFMETADATA1\n']
    for d in data:
        chapters.append(make_country_data(d, prev_duration, args.fade_duration))
        prev_duration += int(d.snippet_end - d.snippet_start) + args.fade_duration * 2

    out_.write_text(''.join(chapters))

def concat(clips: List[Path], metadata: Path, temp_video: Path, out_: Path) -> None:
    manifest = temp_video.with_suffix(".txt")
    manifest.write_text("\n".join(f"file '{c.absolute()}'" for c in clips))

    common.run(["ffmpeg",
         "-hide_banner", "-y", "-f", "concat",
         "-safe", "0", "-i", str(manifest),
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-c:a", "aac", "-b:a", "192k",
         "-movflags", "faststart", str(temp_video)])

    common.run(["ffmpeg", "-hide_banner", "-y", "-i", str(temp_video),
         "-i", str(metadata),
         "-map_metadata", "1", "-c", "copy",
         str(out_)])

def process_row(row: Data, srcd: Path, cardsd: Path, clipsd: Path, args: Args) -> tuple[tuple[int, str], Path]:
    out_clip = clipsd / f"{row.year}_{row.show}_{row.ro:02d}_{str(row.country)}.mp4"

    if out_clip.exists():
        common.write(f"[recap] {out_clip} already exists, skipping.")
        return ((row.year, row.show), out_clip)

    card_name = f"{row.year}_{row.show}_{row.ro:02d}_{str(row.country)}.png"
    vid_name = f"{row.year}_{row.show}_{row.ro:02d}_{str(row.country)}.mp4"

    snippet_end = row.snippet_end + args.fade_duration

    snippet_start = row.snippet_start - args.fade_duration
    if snippet_start < 0:
        snippet_start = 0
        snippet_end = snippet_end + args.fade_duration

    src = srcd / vid_name
    if not src.exists(follow_symlinks=False):
        raise FileNotFoundError(f"Source video not found: {src}")
    overlay = cardsd / card_name
    if not overlay.exists():
        raise FileNotFoundError(f"Overlay card not found: {overlay}")

    # TODO: add silence snapping, maybe
    s0, s1 = snippet_start, snippet_end
    if s1 <= s0:
        raise RuntimeError(f"Snapping produced empty clip (order={row.ro}).")

    process_clip(out_clip, src, overlay, s0, s1, args.size, args.fps, args.fade_duration)
    return ((row.year, row.show), out_clip)

def main(args: Args) -> None:
    csv_path = Path(args.csv_path)
    data: dict[tuple[int, str], list[Data]] = defaultdict(list)
    n = 0
    with csv_path.open(newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            n += 1
            year = int(row["year"].strip())
            show = row["show"].strip()
            val = Data(
                ro=int(row["running_order"].strip()),
                country=row["country"].strip(),
                year=year,
                show=show,
                artist=row["artist"].strip(),
                title=row["title"].strip(),
                snippet_start=float(row["snippet_start"].strip()),
                snippet_end=float(row["snippet_end"].strip())
            )

            data[(year, show)].append(val)

    sz = len(data)

    clipsd = args.tmp_dir / "clips"
    clipsd.mkdir(parents=True, exist_ok=True)
    clips: dict[tuple[int, str], list[Path]] = defaultdict(list)

    common.write(f"Processing {sz} clips...")
    start1 = time.time()

    temp_clips = []
    if args.multiprocessing:
        temp_clips = mp.Pool(mp.cpu_count()).starmap(
            process_row,
            [(v, Path(args.vids_dir), Path(args.cards_dir), clipsd, args) for row in data.values() for v in row]
        )
        for key, clip in temp_clips:
            clips[key].append(clip)
    else:
        for vs in data.values():
            for v in vs:
                key, clip = process_row(v, Path(args.vids_dir), Path(args.cards_dir), clipsd, args)
                clips[key].append(clip)

    end1 = time.time()

    common.write(f"Concatenating clips...")
    values = []
    start2 = time.time()
    args.output.mkdir(parents=True, exist_ok=True)
    tmp = args.tmp_dir / "recaps"
    tmp.mkdir(parents=True, exist_ok=True)
    for key, clip_list in clips.items():
        vs = data[key]
        clip_list.sort(key=lambda c: c.name)
        output = args.output / f"{key[0]}_{key[1]}_recap.mp4"
        print(output)
        temp_output = tmp / output.with_suffix(".temp.mp4").name
        metadata = tmp / output.with_suffix(".meta.txt").name
        make_chapter_data(vs, args, metadata)

        rev_list = list(reversed(clip_list))
        rev_output = args.output.with_name(f"{output.stem}_rev{output.suffix}")
        temp_rev_output = tmp / rev_output.with_suffix(".temp.mp4").name
        rev_metadata = tmp / rev_output.with_suffix(".meta.txt").name
        make_chapter_data(list(reversed(vs)), args, rev_metadata)

        values.append((clip_list, metadata, temp_output, output))
        values.append((rev_list, rev_metadata, temp_rev_output, rev_output))

    if args.multiprocessing:
        mp.Pool(mp.cpu_count()).starmap(
            concat, values
        )
    else:
        for vss in values:
            concat(*vss)

    #cleanup(tmp)
    end2 = time.time()
    common.write(f"Processed {sz} shows and {n} clips in {end1 - start1:.2f} seconds")
    common.write(f"Concatenated clips in {end2 - start2:.2f} seconds")
    common.write(f"Total processing time: {end2 - start1:.2f} seconds")

def main_wrapper(args: Args):
    if os.name == 'nt' and not common.is_admin():
        common.elevate_via_uac()

    main(args)

if __name__ == "__main__":
    if shutil.which("ffmpeg") is None:
        common.error("Error: ffmpeg is not installed.", file=sys.stderr)
        sys.exit(1)

    ap = argparse.ArgumentParser(
        description="Cut & assemble snippets (16:9, −14 LUFS, overlay, constant fps)."
    )
    ap.add_argument("csv", type=Path, help="CSV file with video metadata")
    ap.add_argument("vidsdir", type=Path, help="Directory with input videos")
    ap.add_argument("cardsdir", type=Path, help="Directory with overlay cards")
    ap.add_argument("--tmp", type=Path, default="tmp", help="Temporary directory for clips")
    ap.add_argument("-o", "--output", type=Path, default="output",
                    help="Output video directory")
    ap.add_argument("--size", default="1920x1080", type=common.parse_size,
                    help="target frame size WxH")
    ap.add_argument("--fps", default=60, type=int,
                    help="constant output fps (e.g. 23.98, 24, 25, 29.97, 30, 50, 59.94, 60). Default 60")
    ap.add_argument("--fade-duration", default=0.25, type=float,
                    help="Duration of fade-in and fade-out in seconds (default: 0.25)")
    ap.add_argument("--multiprocessing", action="store_true",
                    help="Use multiprocessing to speed up the processing of clips")
    args = ap.parse_args()

    ar = Args(
        csv_path=args.csv,
        vids_dir=args.vidsdir,
        cards_dir=args.cardsdir,
        tmp_dir=args.tmp,
        output=args.output,
        size=args.size,
        fps=args.fps,
        multiprocessing=args.multiprocessing,
        fade_duration=args.fade_duration
    )

    try:
        main_wrapper(ar)
    except KeyboardInterrupt:
        sys.exit(130)