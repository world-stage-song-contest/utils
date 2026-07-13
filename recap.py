#!/usr/bin/env python3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import hashlib
import json
import multiprocessing as mp
import re
import time
from urllib.parse import urlparse

import app_cache
import common

RECAP_MEDIA_TYPES = {"v", "a"}


@dataclass(frozen=True)
class Data:
    ro: str
    show: str
    country: str
    artist: str
    title: str
    path: Path
    snippet_start: float
    snippet_end: float
    media_type: str
    cover_path: Path | None

    def make_straight(self, start: float, end: float) -> "Data":
        return Data(
            ro=self.ro,
            show=self.show,
            country=self.country,
            artist=self.artist,
            title=self.title,
            path=self.path,
            snippet_start=start,
            snippet_end=end,
            media_type=self.media_type,
            cover_path=self.cover_path,
        )


@dataclass(frozen=True)
class MediaProbe:
    has_audio: bool
    has_picture: bool
    has_video: bool


@dataclass(frozen=True)
class RenderJob:
    key: str
    rows: list[Data]
    metadata: Path
    graph: Path
    output: Path
    reverse: bool
    fingerprint: str


def file_identity(path: Path) -> tuple[str, int, int]:
    stat = path.resolve().stat()
    return (str(path.resolve()), stat.st_size, stat.st_mtime_ns)


def output_fingerprint(rows: list[Data], args: common.Args, reverse: bool) -> str:
    value = {
        # Version 2 fixes audio artwork: attached pictures are now opened as
        # an unseeked visual input, rather than being discarded by the audio
        # snippet seek that starts after their timestamp-zero frame.
        "version": 2,
        "reverse": reverse,
        "size": args.size,
        "fps": args.fps,
        "fade": args.fade_duration,
        "av1": [args.av1_preset, args.av1_crf, args.av1_threads],
        "opus": args.opus_bitrate,
        "normalization": args.audio_normalization,
        "rows": [
            {
                "ro": row.ro, "country": row.country, "artist": row.artist, "title": row.title,
                "range": [row.snippet_start, row.snippet_end], "type": row.media_type,
                "source": file_identity(row.path),
                "cover": file_identity(row.cover_path) if row.cover_path and row.cover_path.exists() else None,
                "card": file_identity(args.cardsdir / row.show / f"{row.ro}_{row.country}.png"),
            }
            for row in rows
        ],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def hms(seconds: float) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def parse_seconds(value: str | None) -> float | None:
    """Parse a string in the form SS, M:SS, or H:MM:SS."""
    if not value or not value.strip():
        return None
    parts = [float(part) for part in value.strip().split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"Invalid timestamp: {value!r}")


def split_key(key: str) -> tuple[str, str]:
    return key[0:4], key[4:]


def clip_range(row: Data, fade_duration: float) -> tuple[float, float]:
    """Return the source range used by the legacy per-clip renderer."""
    start = row.snippet_start - fade_duration
    end = row.snippet_end + fade_duration
    if start < 0:
        start = 0
        end += fade_duration
    if end <= start:
        raise ValueError(f"Empty recap range for {row.show} #{row.ro} {row.country}")
    if fade_duration > end - start:
        raise ValueError(f"Fade is longer than recap range for {row.show} #{row.ro} {row.country}")
    return start, end


def probe_media(path: Path, args: common.Args) -> MediaProbe:
    proc = common.run([
        args.ffprobe, "-v", "error", "-show_entries",
        "stream=codec_type:stream_disposition=attached_pic", "-of", "json", str(path),
    ])
    try:
        streams = json.loads(proc.stdout).get("streams", [])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Cannot read stream data from {path}") from exc

    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    has_picture = any(
        stream.get("codec_type") == "video"
        and stream.get("disposition", {}).get("attached_pic", 0)
        for stream in streams
    )
    has_video = any(
        stream.get("codec_type") == "video"
        and not stream.get("disposition", {}).get("attached_pic", 0)
        for stream in streams
    )
    return MediaProbe(has_audio=has_audio, has_picture=has_picture, has_video=has_video)


def validate_media(row: Data, probe: MediaProbe) -> None:
    if not probe.has_audio:
        raise RuntimeError(f"Source has no audio stream: {row.path}")
    if row.media_type == "v" and not probe.has_video:
        raise RuntimeError(f"Video entry has no non-attached video stream: {row.path}")
    if row.media_type == "a" and not probe.has_picture and not (
        row.cover_path is not None and row.cover_path.exists()
    ):
        raise RuntimeError(f"Audio entry needs attached artwork or an image_link cover: {row.path}")


def video_normalizer(width: int, height: int) -> str:
    """Fit the input in the output frame with one high-quality scale operation."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
        f"force_divisible_by=2:flags=lanczos,setsar=1,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih):color=black,setsar=1"
    )


def loudnorm_filter(row: Data, start: float, duration: float, args: common.Args) -> str:
    if args.audio_normalization == "none":
        return ""
    base = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if args.audio_normalization == "one-pass":
        return f",{base}"

    probe = common.run([
        args.ffmpeg, "-hide_banner", "-loglevel", "info", "-ss", hms(start), "-t", hms(duration),
        "-i", str(row.path), "-map", "0:a:0", "-af", f"{base}:print_format=json", "-f", "null", "-",
    ])
    match = re.findall(r"\{\s*\"input_i\".*?\}", probe.stderr, flags=re.DOTALL)
    if not match:
        raise RuntimeError(f"Could not measure loudness for {row.path}")
    measured = json.loads(match[-1])
    values = ":".join(
        f"{target}={measured[source]}"
        for target, source in [
            ("measured_I", "input_i"), ("measured_TP", "input_tp"),
            ("measured_LRA", "input_lra"), ("measured_thresh", "input_thresh"),
            ("offset", "target_offset"),
        ]
    )
    return f",{base}:{values}:linear=true:print_format=summary"


def build_graph(rows: list[Data], args: common.Args) -> tuple[list[str], str, int]:
    """Create all FFmpeg inputs and a graph that emits one recap A/V pair."""
    if not rows:
        raise ValueError("Cannot render an empty recap")

    if args.size is None:
        raise RuntimeError("Output size must be resolved before building a recap graph")
    width, height = args.size
    input_args: list[str] = []
    filters: list[str] = []
    concat_inputs: list[str] = []
    probes: dict[Path, MediaProbe] = {}
    input_count = 0

    for entry_number, row in enumerate(rows):
        if not row.path.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Source media not found: {row.path}")
        card = args.cardsdir / row.show / f"{row.ro}_{row.country}.png"
        if not card.exists():
            raise FileNotFoundError(f"Overlay card not found: {card}")

        probe = probes.get(row.path)
        if probe is None:
            probe = probe_media(row.path, args)
            probes[row.path] = probe
        validate_media(row, probe)
        start, end = clip_range(row, args.fade_duration)
        duration = end - start
        media_input = input_count
        input_count += 1
        duration_text = f"{duration:.6f}"
        fade_start = f"{duration - args.fade_duration:.6f}"

        # Seek each occurrence independently.  That preserves fast seeking for
        # short snippets, even when the same source appears more than once.
        input_args.extend([
            "-ss", hms(start), "-t", hms(duration), "-i", str(row.path),
        ])

        if row.media_type == "a" and row.cover_path is not None and row.cover_path.exists():
            visual_input_index = input_count
            input_count += 1
            input_args.extend([
                "-loop", "1", "-framerate", str(args.fps), "-t", hms(duration), "-i", str(row.cover_path),
            ])
            visual_input = f"[{visual_input_index}:v:0]trim=duration={duration_text},setpts=PTS-STARTPTS"
        elif row.media_type == "a":
            visual_input_index = input_count
            input_count += 1
            input_args.extend(["-i", str(row.path)])
            visual_input = (
                f"[{visual_input_index}:v:0]loop=loop=-1:size=1:start=0,"
                f"trim=duration={duration_text},setpts=PTS-STARTPTS"
            )
        else:
            visual_input = (
                f"[{media_input}:v:0]trim=duration={duration_text},setpts=PTS-STARTPTS"
            )

        card_input = input_count
        input_count += 1
        input_args.extend([
            "-loop", "1", "-framerate", str(args.fps), "-t", hms(duration), "-i", str(card),
        ])

        filters.extend([
            f"{visual_input},{video_normalizer(width, height)}[base{entry_number}]",
            f"[{card_input}:v:0]trim=duration={duration_text},setpts=PTS-STARTPTS[card{entry_number}]",
            f"[base{entry_number}][card{entry_number}]"
            f"overlay=(W-w)/2:(H-h)/2:format=auto,"
            f"fade=t=in:st=0:d={args.fade_duration:.6f},"
            f"fade=t=out:st={fade_start}:d={args.fade_duration:.6f},"
            f"fps=fps={args.fps},format=yuv420p[v{entry_number}]",
            f"[{media_input}:a:0]atrim=duration={duration_text},asetpts=PTS-STARTPTS"
            f"{loudnorm_filter(row, start, duration, args)},"
            f"afade=t=in:st=0:d={args.fade_duration:.6f},"
            f"afade=t=out:st={fade_start}:d={args.fade_duration:.6f}[a{entry_number}]",
        ])
        concat_inputs.extend([f"[v{entry_number}]", f"[a{entry_number}]"])

    filters.append(
        "".join(concat_inputs) + f"concat=n={len(rows)}:v=1:a=1[vout][aout]"
    )
    return input_args, ";\n".join(filters) + "\n", input_count


def make_chapter_data(rows: Iterable[Data], args: common.Args, out_path: Path, reverse: bool) -> None:
    ordered_rows = list(reversed(list(rows))) if reverse else list(rows)
    elapsed = 0.0
    chapters = [";FFMETADATA1\n"]
    for row in ordered_rows:
        start, end = clip_range(row, args.fade_duration)
        duration = end - start
        country = common.schemes.get(row.country)
        country_name = country.name if country else row.country
        chapters.append(
            "\n[CHAPTER]\n"
            "TIMEBASE=1/1000\n"
            f"START={elapsed * 1000:.0f}\n"
            f"END={(elapsed + duration) * 1000:.0f}\n"
            f"title={country_name}: {row.artist} - {row.title}\n"
        )
        elapsed += duration
    out_path.write_text("".join(chapters), encoding="utf-8")


def render(job: RenderJob, args: common.Args) -> tuple[str, Path]:
    rows = list(reversed(job.rows)) if job.reverse else job.rows
    input_args, graph, input_count = build_graph(rows, args)
    job.graph.write_text(graph, encoding="utf-8")
    temp_out = job.output.with_suffix(".temp.mp4")
    metadata_input = input_count
    year, show_code = split_key(job.key)
    show_name = common.show_name_map.get(show_code, "NF")
    direction = "Reverse" if job.reverse else "Direct"

    av1_thread_args = ["-svtav1-params", f"lp={args.av1_threads}"] if args.av1_threads > 0 else []
    common.run([
        args.ffmpeg, "-hide_banner", "-y", "-loglevel", "error",
        *input_args, "-f", "ffmetadata", "-i", str(job.metadata),
        "-filter_complex_script", str(job.graph),
        "-map", "[vout]", "-map", "[aout]", "-map_metadata", str(metadata_input),
        "-metadata", f"title={year} {show_name} {direction} Recap",
        "-c:v", "libsvtav1", "-preset", str(args.av1_preset), "-crf", str(args.av1_crf), *av1_thread_args,
        "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", args.opus_bitrate,
        "-movflags", "+faststart", "-f", "mp4", str(temp_out),
    ])
    temp_out.rename(job.output)
    app_cache.store_recap_fingerprint(job.output, job.fingerprint)
    return job.key, job.output


def worker_count(args: common.Args, job_count: int) -> int:
    if args.jobs > 0:
        return min(job_count, args.jobs)
    if not args.multiprocessing:
        return 1
    # SVT-AV1 is already multithreaded.  A small process count avoids the severe
    # oversubscription caused by the old half-of-all-CPUs setting.
    return min(job_count, max(1, mp.cpu_count() // 4))


def main(all_clips: common.Clips, args: common.Args) -> dict[str, list[Path]]:
    direct: dict[str, list[Data]] = defaultdict(list)
    reverse: dict[str, list[Data]] = defaultdict(list)
    source_count = 0

    for row in common.load_rows(args.csv):
        media_type = row["type"]
        if media_type not in RECAP_MEDIA_TYPES:
            continue
        source_count += 1
        raw_ro = row["ro"].strip()
        try:
            ro = f"{int(raw_ro):02d}"
        except ValueError:
            ro = raw_ro
        show = row["show"].strip()
        country = row["cc"].strip().upper()
        try:
            path = all_clips[(show, ro)][country]
        except KeyError as exc:
            raise KeyError(f"No downloaded source for {show} #{ro} {country}") from exc
        parsed_start = parse_seconds(row.get("snippet_start"))
        parsed_end = parse_seconds(row.get("snippet_end"))
        first_start = 50.0 if parsed_start is None else parsed_start
        first_end = first_start + 20.0 if parsed_end is None else parsed_end
        if first_end <= first_start:
            raise ValueError(f"snippet_end must be after snippet_start for {show} #{ro} {country}")

        value = Data(
            ro=ro,
            show=show,
            country=country,
            artist=row["artist"].strip(),
            title=row["title"].strip(),
            path=path,
            snippet_start=first_start,
            snippet_end=first_end,
            media_type=media_type,
            cover_path=(
                args.vidsdir / show / f"{ro}_{country}.cover"
                f"{Path(urlparse(row.get('image_link', '')).path).suffix.lower() or '.jpg'}"
            ) if row.get("image_link", "") else None,
        )
        reverse[show].append(value)
        direct_start = parse_seconds(row.get("snippet2_start"))
        direct_end = parse_seconds(row.get("snippet2_end"))
        actual_direct_start = first_start if direct_start is None else direct_start
        direct[show].append(value.make_straight(
            actual_direct_start,
            actual_direct_start + 10 if direct_end is None else direct_end,
        ))

    args.output.mkdir(parents=True, exist_ok=True)
    scratch = args.tmpdir / "metadata"
    scratch.mkdir(parents=True, exist_ok=True)
    app_cache.initialize_database()
    jobs: list[RenderJob] = []
    available: list[tuple[str, Path]] = []

    def add_jobs(data: dict[str, list[Data]], is_reverse: bool) -> None:
        suffix = "" if is_reverse else "s"
        for key, rows in data.items():
            output = args.output / f"{key}{suffix}.mov"
            fingerprint = output_fingerprint(rows, args, is_reverse)
            if output.exists() and app_cache.cached_recap_fingerprint(output) == fingerprint:
                print(f"[recap] {output} exists, skipping", file=common.OUT_HANDLE)
                available.append((key, output))
                continue
            metadata = scratch / f"{output.stem}.meta.txt"
            graph = scratch / f"{output.stem}.ffscript"
            make_chapter_data(rows, args, metadata, is_reverse)
            jobs.append(RenderJob(key, rows, metadata, graph, output, is_reverse, fingerprint))

    if not args.only_reverse:
        add_jobs(direct, is_reverse=False)
    if not args.only_straight:
        add_jobs(reverse, is_reverse=True)

    print(f"[recap] Rendering {len(jobs)} recaps from {source_count} entries...", file=common.OUT_HANDLE)
    start = time.time()
    if jobs:
        count = worker_count(args, len(jobs))
        if count > 1:
            with mp.Pool(count) as pool:
                rendered = pool.starmap(render, [(job, args) for job in jobs])
        else:
            rendered = [render(job, args) for job in jobs]
    else:
        rendered = []

    result: dict[str, list[Path]] = defaultdict(list)
    for key, output in [*available, *rendered]:
        result[key].append(output)
    print(f"[recap] Rendered {len(rendered)} recaps in {time.time() - start:.2f} seconds", file=common.OUT_HANDLE)
    return result
