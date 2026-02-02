#!/usr/bin/env python3
import argparse
from collections import defaultdict
from dataclasses import dataclass
import time
import csv
import multiprocessing as mp
from pathlib import Path
from typing import List, Tuple
import itertools as it

import common

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
    filt.append(f"[fo]fps=fps={fps},format=yuv420p10le[v]")
    return ";".join(filt)

def build_af(dur: float, fade_dur: float) -> str:
    """
    loudnorm → optional afade-in/out   ==> label [a]
    """
    chain = ("[0:a:0]"
             f"afade=t=in:st=0:d={fade_dur:.3f}"
             f",afade=t=out:st={dur-fade_dur:.3f}:d={fade_dur:.3f}[a]")
    return chain


def process_mov(out_: Path, src: Path, overlay: Path,
                start: float, end: float, args: common.Args) -> None:
    if not overlay.exists():
        raise FileNotFoundError(f"Overlay not found: {overlay}")

    w, h = args.size
    dur = end - start
    if dur <= 0:
        raise ValueError(f"Invalid clip range: start={start}, end={end}")

    temp_out = out_.with_suffix(".temp.mov")

    filter_complex = (
        f"color=color=black:size={w}x{h}[black];"
        "[0:v:0]scale="
        "w='ceil(iw*sar/2)*2':h='ceil(ih/2)*2':"
        "sws_dither=x_dither:"
        "sws_flags='spline+print_info+bitexact+full_chroma_int+accurate_rnd':"
        "out_range=tv,"
        "setsar=1[fg];"
        f"[fg]scale=w={w}:h={h}:force_original_aspect_ratio=increase"
        f",crop={w}:{h}"
        ",setsar=1[fg];"
        "[black][fg]overlay[v];"
        f"[v]fps=fps={args.fps}[v]"
    )

    common.run([
        args.ffmpeg, "-hide_banner",
        "-i", str(src),
        "-i", str(overlay),
        "-ss", hms(start),
        "-t", hms(dur),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a:0",
        "-map_metadata", "-1",
        "-ar", "48000",
        "-c:v", "prores",
        "-c:a", "pcm_s24le",
        "-pix_fmt", "yuv422p10le",
        "-color_range", "tv",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        str(temp_out),
        "-n",
    ])

    temp_out.rename(out_)

def process_m4a(row: common.AudioData, args: common.Args) -> None:
    if not row.vpath().exists():
        raise FileNotFoundError(f"Audio not found: {row.vpath()}")

    w, h = args.size
    dur = row.snippet_end - row.snippet_start
    if dur <= 0:
        raise ValueError(f"Invalid clip range: start={row.snippet_start}, end={row.snippet_end}")

    temp_out = out_.with_suffix(".temp.mov")

    filter_complex = (
        f"color=color=black@0.2:size={w}x{h}[black];"
        "[0:v:0]scale="
        "w='ceil(iw*sar/2)*2':h='ceil(ih/2)*2':"
        "sws_dither=x_dither:"
        "sws_flags='spline+print_info+bitexact+full_chroma_int+accurate_rnd':"
        "out_range=tv,"
        "setsar=1[fg];"
        "[fg]scale=w=270:h=270"
        ":force_original_aspect_ratio=decrease"
        f",pad={w}:{h}:-1:-1"
        ":color=#00000000"
        ",setsar=1[fg];"
        f"[0:v:0]scale=w={w}:h={h}"
        ":sws_dither=x_dither"
        ":sws_flags='spline+print_info+bitexact+full_chroma_int+accurate_rnd'"
        ":out_range=tv"
        ",setsar=1"
        ",gblur=sigma=64"
        ",eq=gamma=4/5:saturation=4/5[bg];"
        "[bg][black]overlay[bg];"
        "[bg][fg]overlay[v];"
        f"[v]fps=fps={args.fps}[v]"
    )

    common.run([
        args.ffmpeg, "-hide_banner",
        "-loop", "1",
        "-i", str(row.image_link),
        "-i", str(row.vpath()),
        "-ss", hms(row.snippet_start),
        "-t", hms(dur),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "1:a:0",
        "-map_metadata", "-1",
        "-ar", "48000",
        "-c:v", "prores",
        "-c:a", "pcm_s24le",
        "-pix_fmt", "yuv422p10le",
        "-color_range", "tv",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
        "-loglevel", "verbose",
        str(temp_out),
        "-n",
    ])

    temp_out.rename(out_)

def process_clip():
    pass

def make_country_data(data: common.Data, prev_duration: float, fade_duration: float) -> str:
    end = prev_duration + int(data.snippet_end - data.snippet_start) + fade_duration
    return f"""
[CHAPTER]
TIMEBASE=1/1000
START={prev_duration * 1000:.0f}
END={end * 1000:.0f}
title={common.schemes[data.country].name}: {data.artist} - {data.title}
"""

def make_chapter_data(data: List[common.Data], args: common.Args, out_: Path, reverse: bool):
    prev_duration = 1.0
    chapters = [';FFMETADATA1\n']

    if reverse:
        for d in reversed(data):
            chapters.append(make_country_data(d, prev_duration, args.fade_duration))
            prev_duration += int(d.snippet_end - d.snippet_start) + args.fade_duration * 2
    else:
        for d in data:
            chapters.append(make_country_data(d, prev_duration, args.fade_duration))
            prev_duration += int(d.snippet_end - d.snippet_start) + args.fade_duration * 2

    out_.write_text(''.join(chapters), encoding='utf-8')

def concat(clips: List[Path], metadata: Path, manifest: Path, out_: Path, ffmpeg: str, key: str, show_name: str, reverse: bool) -> tuple[str, Path]:
    if reverse:
        manifest.write_text("\n".join(f"file '{c.absolute()}'" for c in reversed(clips)), encoding='utf-8')
    else:
        manifest.write_text("\n".join(f"file '{c.absolute()}'" for c in clips), encoding='utf-8')

    temp_out = out_.with_suffix(".temp.mp4")
    common.run([ffmpeg,
         "-hide_banner", "-y", "-f", "concat",
         "-safe", "0", "-i", str(manifest),
         "-f", "ffmetadata", "-i", str(metadata),
         "-map", "0", "-map_metadata", "1",
         "-c", "copy", "-metadata", f"title={show_name}",
         "-f", "mp4", "-movflags", "faststart",
         str(temp_out)])

    temp_out.rename(out_)

    return (key, out_)

def process_row(row: common.Data, args: common.Args) -> tuple[str, Path]:
    out_clip = args.clipsdir / row.show / f"{row.ro}_{row.cc}.mp4"
    out_clip.parent.mkdir(parents=True, exist_ok=True)
    if out_clip.exists():
        print(f"[recap] {out_clip} already exists, skipping.", file=common.OUT_HANDLE)
        return (row.show, out_clip)

    snippet_end = row.snippet_end + args.fade_duration

    snippet_start = row.snippet_start - args.fade_duration
    if snippet_start < 0:
        snippet_start = 0
        snippet_end = snippet_end + args.fade_duration

    src = row.video_path
    assert src is not None

    if not src.exists(follow_symlinks=False):
        raise FileNotFoundError(f"Source video not found: {src}")
    overlay = args.cardsdir / f"{row.show}/{row.ro}_{row.cc}.png"
    if not overlay.exists():
        raise FileNotFoundError(f"Overlay card not found: {overlay}")

    # TODO: add silence snapping, maybe
    s0, s1 = snippet_start, snippet_end
    if s1 <= s0:
        raise RuntimeError(f"Snapping produced empty clip (order={row.ro}).")

    process_clip(out_clip, src, overlay, s0, s1, args)
    return (row.show, out_clip)

def parse_seconds(td: str | None) -> int | None:
    """Parse a string in the format M:SS into seconds."""
    if not td:
        return None
    parts = list(map(int, td.strip().split(':')))
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    else:
        return int(td)

def split_key(key: str) -> tuple[str, str]:
    return key[0:4], key[4:]

def main(input_data: common.Data, args: common.Args) -> dict[str, list[Path]]:
    ret = defaultdict(list)
    data: dict[str, list[common.Data]] = defaultdict(list)
    rdata: dict[str, list[common.Data]] = defaultdict(list)
    n = 0

    sz = len(data)

    args.tmpdir.mkdir(parents=True, exist_ok=True)

    print(f"Processing {sz} clips...", file=common.OUT_HANDLE)
    start1 = time.time()

    def process_rows(rows: dict[str, list[common.Data]]) -> dict[str, list[Path]]:
        clips: dict[str, list[Path]] = defaultdict(list)
        items = (
            (v, args)
            for row in rows.values()
            for v in row
        )

        if args.multiprocessing:
            with mp.Pool(mp.cpu_count()//2) as pool:
                results = pool.starmap(process_row, items)
        else:
            results = [process_row(*item) for item in items]

        for key, clip in results:
            clips[key].append(clip)

        return clips

    if not args.only_reverse:
        clips = process_rows(data)

    if not args.only_straight:
        rclips = process_rows(rdata)

    end1 = time.time()

    print(f"Concatenating clips...", file=common.OUT_HANDLE)
    start2 = time.time()
    scratch = args.tmpdir / "metadata"
    args.output.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)

    def process_clips(clips: dict[str, list[Path]], data: dict[str, list[common.Data]], reverse: bool) -> list[common.Data]:
        values = []
        suffix = ''
        if not reverse:
            suffix = 's'

        for key, clip_list in clips.items():
            yr, sh = split_key(key)
            sn = common.show_name_map.get(sh, 'NF')
            vs = data[key]
            output = args.output / f"{key}{suffix}.mov"
            if not output.exists():
                manifest = scratch / output.with_suffix(".manifest.txt").name
                metadata = scratch / output.with_suffix(".meta.txt").name
                make_chapter_data(vs, args, metadata, reverse)
                show_name = f"{yr} {sn} Direct Recap"
                values.append((clip_list, metadata, manifest, output, args.ffmpeg, key, show_name, reverse))
            else:
                print(f"[recap] {output} exists, skipping", file=common.OUT_HANDLE)

        return values

    if not args.only_reverse:
        values = process_clips(clips, data, reverse=False) # type: ignore

    if not args.only_straight:
        rvalues = process_clips(rclips, rdata, reverse=True) # type: ignore

    def concat_clips(values: list[common.Data]) -> list[tuple[str, Path]]:
        if args.multiprocessing:
            return mp.Pool(mp.cpu_count()//2).starmap(
                concat, values
            )
        else:
            vals = []
            for vss in values:
                vals.append(concat(*vss))
            return vals

    vals = []
    if not args.only_reverse:
        vals.extend(concat_clips(values)) # type: ignore

    if not args.only_straight:
        vals.extend(concat_clips(rvalues)) # type: ignore

    end2 = time.time()
    print(f"Processed {sz} shows and {n} clips in {end1 - start1:.2f} seconds", file=common.OUT_HANDLE)
    print(f"Concatenated clips in {end2 - start2:.2f} seconds", file=common.OUT_HANDLE)
    print(f"Total processing time: {end2 - start1:.2f} seconds", file=common.OUT_HANDLE)

    for key, out_ in vals:
        ret[key].append(out_)

    return ret