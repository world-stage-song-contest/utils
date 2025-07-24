#!/usr/bin/env python3
import argparse
from collections import defaultdict
from dataclasses import dataclass
import time
import csv
import multiprocessing as mp
from pathlib import Path
from typing import List, Tuple

import common

@dataclass
class Data:
    ro: str
    year: int
    show: str
    country: str
    artist: str
    title: str
    path: Path
    snippet_start: float
    snippet_end: float

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
    r = f"{target_w}/{target_h}"
    filt = []

    # 1. square the pixels
    filt.append("[0:v]scale=w='ceil(iw*sar/2)*2':h='ceil(ih/2)*2'"
                ":flags=lanczos,setsar=1[sq]")

    # 2. fit & pad
    filt.append(f"[sq]scale=w='if(gt(a,{r}),{target_w},-2)':"
                f"h='if(gt(a,{r}),-2,{target_h})':flags=lanczos,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[fit]")

    # 3. overlay
    filt.append("[fit][1:v]overlay=(W-w)/2:(H-h)/2:format=auto[ovl]")

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
             f",afade=t=out:st={dur-fade_dur:.3f}:d={fade_dur:.3f}[a]")
    return chain


def process_clip(out_: Path, src: Path, overlay: Path,
                 start: float, end: float, args: common.Args) -> None:
    if not overlay.exists():
        raise FileNotFoundError(f"Overlay not found: {overlay}")
    w, h = args.size
    dur = end - start
    vf = build_vf(w, h, args.fps, dur, args.fade_duration)
    af = build_af(dur, args.fade_duration)
    temp_out = out_.with_suffix(".temp.mp4")
    common.run([
        args.ffmpeg, "-hide_banner", "-y",
        "-ss", hms(start), "-to", hms(end),
        "-i", str(src), "-i", str(overlay),
        "-filter_complex", f"{vf};{af}",
        "-map", "[v]", "-map", "[a]", "-r", str(args.fps),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(temp_out)
    ])

    temp_out.rename(out_)

def make_country_data(data: Data, prev_duration: float, fade_duration: float) -> str:
    end = prev_duration + int(data.snippet_end - data.snippet_start) + fade_duration
    return f"""
[CHAPTER]
TIMEBASE=1/1000
START={prev_duration * 1000:.0f}
END={end * 1000:.0f}
title={common.schemes[data.country].name}: {data.artist} - {data.title}
"""

def make_chapter_data(data: List[Data], args: common.Args, out_: Path):
    prev_duration = 1.0
    chapters = [';FFMETADATA1\n']
    for d in data:
        chapters.append(make_country_data(d, prev_duration, args.fade_duration))
        prev_duration += int(d.snippet_end - d.snippet_start) + args.fade_duration * 2

    out_.write_text(''.join(chapters), encoding='utf-8')

def concat(clips: List[Path], metadata: Path, manifest: Path, out_: Path, ffmpeg: str, key: tuple[int, str]) -> tuple[tuple[int, str], Path]:
    manifest.write_text("\n".join(f"file '{c.absolute()}'" for c in clips), encoding='utf-8')

    temp_out = out_.with_suffix(".temp.mp4")
    common.run([ffmpeg,
         "-hide_banner", "-y", "-f", "concat",
         "-safe", "0", "-i", str(manifest),
         "-f", "ffmetadata", "-i", str(metadata),
         "-map", "0", "-map_metadata", "1",
         "-c", "copy",
         "-movflags", "faststart",
         str(temp_out)])

    temp_out.rename(out_)

    return (key, out_)

def process_row(row: Data, srcd: Path, cardsd: Path, clipsd: Path, args: common.Args) -> tuple[tuple[int, str], Path]:
    out_clip = clipsd / f"{row.year}" / row.show / f"{row.country}.mp4"
    out_clip.parent.mkdir(parents=True, exist_ok=True)
    if out_clip.exists():
        print(f"[recap] {out_clip} already exists, skipping.", file=common.OUT_HANDLE)
        return ((row.year, row.show), out_clip)

    snippet_end = row.snippet_end + args.fade_duration

    snippet_start = row.snippet_start - args.fade_duration
    if snippet_start < 0:
        snippet_start = 0
        snippet_end = snippet_end + args.fade_duration

    src = row.path
    if not src.exists(follow_symlinks=False):
        raise FileNotFoundError(f"Source video not found: {src}")
    overlay = cardsd / f"{row.year}_{row.show}_{row.ro}_{row.country}.png"
    if not overlay.exists():
        raise FileNotFoundError(f"Overlay card not found: {overlay}")

    # TODO: add silence snapping, maybe
    s0, s1 = snippet_start, snippet_end
    if s1 <= s0:
        raise RuntimeError(f"Snapping produced empty clip (order={row.ro}).")

    process_clip(out_clip, src, overlay, s0, s1, args)
    return ((row.year, row.show), out_clip)

def main(all_clips: common.Clips, args: common.Args) -> dict[tuple[int, str], list[Path]]:
    ret = defaultdict(list)
    data: dict[tuple[int, str], list[Data]] = defaultdict(list)
    n = 0
    with args.csv.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            n += 1
            typ = (row.get("type",'') or 'v').strip()
            if typ != 'v':
                continue
            rro = row["running_order"].strip()
            try:
                ro = f"{int(rro):02d}"
            except ValueError:
                ro = rro
            year = int(row["year"].strip())
            show = row["show"].strip()
            country=row["country"].strip()
            path = all_clips.videos[(year, show)][country]
            val = Data(
                ro=ro,
                country=country,
                year=year,
                show=show,
                artist=row["artist"].strip(),
                title=row["title"].strip(),
                snippet_start=float(row["snippet_start"].strip() or '50'),
                snippet_end=float(row["snippet_end"].strip() or '70'),
                path=path,
            )

            data[(year, show)].append(val)

    sz = len(data)

    args.tmpdir.mkdir(parents=True, exist_ok=True)
    clips: dict[tuple[int, str], list[Path]] = defaultdict(list)

    print(f"Processing {sz} clips...", file=common.OUT_HANDLE)
    start1 = time.time()

    temp_clips = []
    clips_dir = args.tmpdir / "clips"
    if args.multiprocessing:
        temp_clips = mp.Pool(mp.cpu_count()).starmap(
            process_row,
            [(v, args.vidsdir, args.cardsdir, clips_dir, args) for row in data.values() for v in row]
        )
        for key, clip in temp_clips:
            clips[key].append(clip)
    else:
        for vs in data.values():
            for v in vs:
                key, clip = process_row(v, args.vidsdir, args.cardsdir, clips_dir, args)
                clips[key].append(clip)

    end1 = time.time()

    print(f"Concatenating clips...", file=common.OUT_HANDLE)
    values = []
    start2 = time.time()
    scratch = args.tmpdir / "metadata"
    args.output.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    for key, clip_list in clips.items():
        vs = data[key]
        output = args.output / f"{key[0]}_{key[1]}_recap.mp4"
        if not output.exists() and args.straight:
            manifest = scratch / output.with_suffix(".manifest.txt").name
            metadata = scratch / output.with_suffix(".meta.txt").name
            make_chapter_data(vs, args, metadata)
            values.append((clip_list, metadata, manifest, output, args.ffmpeg, key))
        else:
            print(f"[recap] {output} exists, skipping", file=common.OUT_HANDLE)

        rev_output = output.with_stem(f"{key[0]}_{key[1]}_recap_rev")
        if not rev_output.exists() and args.reverse:
            rev_list = list(reversed(clip_list))
            rev_manifest = scratch / rev_output.with_suffix(".manifest.txt").name
            rev_metadata = scratch / rev_output.with_suffix(".meta.txt").name
            make_chapter_data(list(reversed(vs)), args, rev_metadata)
            values.append((rev_list, rev_metadata, rev_manifest, rev_output, args.ffmpeg, key))
        else:
            print(f"[recap] {rev_output} exists, skipping", file=common.OUT_HANDLE)

    if args.multiprocessing:
        vals = mp.Pool(mp.cpu_count()).starmap(
            concat, values
        )
    else:
        vals = []
        for vss in values:
            vals.append(concat(*vss))

    end2 = time.time()
    print(f"Processed {sz} shows and {n} clips in {end1 - start1:.2f} seconds", file=common.OUT_HANDLE)
    print(f"Concatenated clips in {end2 - start2:.2f} seconds", file=common.OUT_HANDLE)
    print(f"Total processing time: {end2 - start1:.2f} seconds", file=common.OUT_HANDLE)

    for key, out_ in vals:
        ret[key].append(out_)

    return ret
