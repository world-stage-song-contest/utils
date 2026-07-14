"""High-level FFmpeg and FFprobe operations used by the application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json
import math
import re
import subprocess as sp


CommandRunner = Callable[..., sp.CompletedProcess[Any]]


@dataclass(frozen=True)
class MediaProbe:
    has_audio: bool
    has_picture: bool
    has_video: bool


@dataclass(frozen=True)
class VideoProperties:
    display_aspect: float
    height: int


@dataclass(frozen=True)
class StreamCodecs:
    video: str
    audio: str


@dataclass(frozen=True)
class MediaTags:
    title: str
    artist: str
    album: str
    keywords: str
    date: str
    location: str
    language: str
    album_artist: str = "World Stage"

    def arguments(self) -> list[str]:
        return [
            "-metadata", f"title={self.title}",
            "-metadata", f"artist={self.artist}",
            "-metadata", f"album={self.album}",
            "-metadata", f"keywords={self.keywords}",
            "-metadata", f"date={self.date}",
            "-metadata", f"location={self.location}",
            "-metadata:s:a:0", f"language={self.language}",
            "-metadata", f"album_artist={self.album_artist}",
        ]


@dataclass(frozen=True)
class RecapEncoding:
    av1_preset: int
    av1_crf: int
    av1_threads: int
    opus_bitrate: str


def timestamp(seconds: float) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


@dataclass(frozen=True)
class FFmpeg:
    """A small facade for the media operations this application needs."""

    executable: str
    probe_executable: str
    run: CommandRunner

    def probe_media(self, path: Path) -> MediaProbe:
        result = self.run([
            self.probe_executable, "-v", "error", "-show_entries",
            "stream=codec_type:stream_disposition=attached_pic", "-of", "json", str(path),
        ])
        streams = json.loads(_text(result.stdout)).get("streams", [])

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

    def video_properties(self, path: Path) -> VideoProperties:
        result = self.run([
            self.probe_executable, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,sample_aspect_ratio", "-of", "json", str(path),
        ])
        streams = json.loads(_text(result.stdout)).get("streams", [])
        if not streams:
            raise RuntimeError(f"No video stream found while detecting aspect ratio: {path}")
        stream = streams[0]
        width = int(stream["width"])
        height = int(stream["height"])
        sar_width, sar_height = map(int, stream["sample_aspect_ratio"].split(":"))
        if sar_width <= 0 or sar_height <= 0:
            raise ValueError(f"Invalid sample aspect ratio for {path}: {stream['sample_aspect_ratio']!r}")
        return VideoProperties((width * sar_width) / (height * sar_height), height)

    def stream_codecs(self, path: Path) -> StreamCodecs:
        """Return the primary video and audio codec names from a media file."""
        result = self.run([
            self.probe_executable, "-v", "error", "-show_entries",
            "stream=codec_type,codec_name", "-of", "json", str(path),
        ], capture=True)
        streams = json.loads(_text(result.stdout)).get("streams", [])
        codecs = {
            str(stream["codec_type"]): str(stream["codec_name"])
            for stream in streams
            if stream.get("codec_type") in {"video", "audio"} and "codec_name" in stream
        }
        try:
            return StreamCodecs(video=codecs["video"], audio=codecs["audio"])
        except KeyError as exc:
            raise RuntimeError(f"Expected video and audio streams in {path}") from exc

    def display_aspect(self, path: Path) -> float:
        return self.video_properties(path).display_aspect

    def duration(self, path: Path) -> int:
        result = self.run([
            self.probe_executable, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ], capture=True)
        return math.ceil(float(_text(result.stdout).strip()))

    def loudnorm_filter(self, path: Path, start: float, duration: float, mode: str) -> str:
        if mode == "none":
            return ""
        base = "loudnorm=I=-14:TP=-1.5:LRA=11"
        if mode == "one-pass":
            return f",{base}"
        if mode != "two-pass":
            raise ValueError(f"Unknown audio normalization mode: {mode}")

        result = self.run([
            self.executable, "-hide_banner", "-loglevel", "info", "-ss", timestamp(start),
            "-t", timestamp(duration), "-i", str(path), "-map", "0:a:0",
            "-af", f"{base}:print_format=json", "-f", "null", "-",
        ])
        matches = re.findall(r"\{\s*\"input_i\".*?\}", _text(result.stderr), flags=re.DOTALL)
        if not matches:
            raise RuntimeError(f"Could not measure loudness for {path}")
        measured = json.loads(matches[-1])
        values = ":".join(
            f"{target}={measured[source]}"
            for target, source in [
                ("measured_I", "input_i"), ("measured_TP", "input_tp"),
                ("measured_LRA", "input_lra"), ("measured_thresh", "input_thresh"),
                ("offset", "target_offset"),
            ]
        )
        return f",{base}:{values}:linear=true:print_format=summary"

    def make_audio(self, cover: Path, audio: Path, output: Path, tags: MediaTags) -> None:
        self.run([
            self.executable, "-y", "-hide_banner", "-i", str(cover), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mjpeg", "-c:a", "copy",
            "-disposition:v:0", "attached_pic", "-metadata:s:v:0", "title=Album cover",
            "-metadata:s:v:0", "comment=Cover (front)", *tags.arguments(),
            "-movflags", "+faststart", "-f", "mp4", str(output),
        ])

    def make_video(
        self, video: Path, subtitles: Path | None, output: Path, tags: MediaTags,
    ) -> None:
        command = [self.executable, "-y", "-hide_banner", "-i", str(video)]
        if subtitles is not None:
            command.extend([
                "-i", str(subtitles), "-map", "0:v", "-map", "0:a", "-map", "1",
                "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
                "-metadata:s:s:0", "language=eng",
            ])
        else:
            command.extend(["-c:v", "copy", "-c:a", "copy"])
        command.extend([
            "-map_metadata", "-1", *tags.arguments(), "-movflags", "+faststart",
            "-f", "mp4", str(output),
        ])
        self.run(command)

    def make_av1_opus_video(
        self,
        source: Path,
        output: Path,
        tags: MediaTags,
        encoding: RecapEncoding,
        preserve_flac: bool,
    ) -> StreamCodecs:
        """Tag a source video, encoding only streams outside the batch policy."""
        codecs = self.stream_codecs(source)
        video_args = ["-c:v", "copy"]
        if codecs.video != "av1":
            video_args = [
                "-c:v", "libsvtav1", "-preset", str(encoding.av1_preset),
                "-crf", str(encoding.av1_crf), "-pix_fmt", "yuv420p",
            ]
            if encoding.av1_threads > 0:
                video_args.extend(["-svtav1-params", f"lp={encoding.av1_threads}"])

        keep_flac = preserve_flac and codecs.audio == "flac"
        audio_args = ["-c:a", "copy"] if codecs.audio == "opus" or keep_flac else [
            "-c:a", "libopus", "-b:a", encoding.opus_bitrate,
        ]
        experimental_args = ["-strict", "-2"] if keep_flac else []
        self.run([
            self.executable, "-y", "-hide_banner", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0", *video_args, *audio_args,
            "-map_metadata", "-1", *tags.arguments(), *experimental_args,
            "-movflags", "+faststart", "-f", "mp4", str(output),
        ])
        return codecs

    def render_recap(
        self,
        *,
        inputs: list[str],
        metadata: Path,
        graph: Path,
        output: Path,
        title: str,
        metadata_input: int,
        encoding: RecapEncoding,
    ) -> Path:
        temporary_output = output.with_suffix(".temp.mp4")
        thread_args = ["-svtav1-params", f"lp={encoding.av1_threads}"] if encoding.av1_threads > 0 else []
        self.run([
            self.executable, "-hide_banner", "-y", "-loglevel", "error", *inputs,
            "-f", "ffmetadata", "-i", str(metadata), "-filter_complex_script", str(graph),
            "-map", "[vout]", "-map", "[aout]", "-map_metadata", str(metadata_input),
            "-metadata", f"title={title}", "-c:v", "libsvtav1",
            "-preset", str(encoding.av1_preset), "-crf", str(encoding.av1_crf), *thread_args,
            "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", encoding.opus_bitrate,
            "-movflags", "+faststart", "-f", "mp4", str(temporary_output),
        ])
        temporary_output.replace(output)
        return output
