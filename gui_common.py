"""Toolkit-independent behaviour shared by the recap-maker GUIs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
import json
import traceback
from typing import Literal, cast

import common
import main
import prepare
import app_config
import batch
import recap_api


SHOW_FIELDS = (
    ("show", "Show"), ("ro", "Running order"), ("cc", "Country code"),
    ("country", "Country"), ("artist", "Artist"), ("title", "Title"),
    ("media_link", "Media link"), ("type", "Type"), ("image_link", "Image link"),
    ("snippet_start", "Snippet start"), ("snippet_end", "Snippet end"),
    ("snippet2_start", "Direct start"), ("snippet2_end", "Direct end"),
    ("language", "Language"),
)
SHOW_TABLE_COLUMNS = ("ro", "cc", "country", "artist", "title", "type", "snippet_start", "snippet_end")
SHOW_REQUIRED_FIELDS = ("show", "ro", "cc", "country", "artist", "title", "media_link", "type")
RECAP_MODES = (
    ("both", "Both recaps"),
    ("direct", "Only direct recap"),
    ("reverse", "Only reverse recap"),
)


class QueueWriter:
    """Pickle-safe stdout/stderr bridge for a recap-maker worker process."""

    def __init__(self, output_queue, tag: str):
        self.output_queue = output_queue
        self.tag = tag

    def write(self, message: str) -> int:
        if message:
            self.output_queue.put((self.tag, message))
        return len(message)

    def flush(self) -> None:
        pass


@dataclass(frozen=True)
class GuiWorkerJob:
    """One GUI operation run through the single multiprocessing entry point."""

    kind: Literal["recap", "prepare", "batch"]
    request: common.Args | prepare.PrepareRequest | batch.BatchDownloadRequest


def _run_gui_process(
    output_queue,
    operation: Callable[[], None],
    *,
    use_common_handles: bool,
    use_prepare_handles: bool,
    redirect_standard_streams: bool,
) -> None:
    """Run one operation with the selected application streams sent to the GUI."""
    stdout = QueueWriter(output_queue, "stdout")
    stderr = QueueWriter(output_queue, "stderr")
    if use_common_handles:
        common.OUT_HANDLE = stdout
        common.ERR_HANDLE = stderr
    if use_prepare_handles:
        prepare.OUT_HANDLE = stdout
        prepare.ERR_HANDLE = stderr
    try:
        stdout_context = redirect_stdout(stdout) if redirect_standard_streams else nullcontext()
        stderr_context = redirect_stderr(stderr) if redirect_standard_streams else nullcontext()
        with stdout_context, stderr_context:
            operation()
    except BaseException:
        traceback.print_exc(file=stderr)
        raise


def run_gui_process(job: GuiWorkerJob, output_queue) -> None:
    """Dispatch every GUI worker through one picklable multiprocessing target."""
    if job.kind == "recap":
        if not isinstance(job.request, common.Args):
            raise TypeError("Recap GUI jobs require common.Args")
        request = cast(common.Args, job.request)
        _run_gui_process(
            output_queue, lambda: main.exec(request), use_common_handles=True,
            use_prepare_handles=False, redirect_standard_streams=False,
        )
        return
    if job.kind == "prepare":
        if not isinstance(job.request, prepare.PrepareRequest):
            raise TypeError("Prepare GUI jobs require PrepareRequest")
        request = cast(prepare.PrepareRequest, job.request)
        _run_gui_process(
            output_queue, lambda: prepare.execute(request), use_common_handles=False,
            use_prepare_handles=True, redirect_standard_streams=False,
        )
        return
    if job.kind == "batch":
        if not isinstance(job.request, batch.BatchDownloadRequest):
            raise TypeError("Batch GUI jobs require BatchDownloadRequest")
        request = cast(batch.BatchDownloadRequest, job.request)
        _run_gui_process(
            output_queue, lambda: batch.download_videos(request), use_common_handles=True,
            use_prepare_handles=True, redirect_standard_streams=True,
        )
        return
    raise ValueError(f"Unsupported GUI job kind: {job.kind}")


def build_prepare_request(values: Mapping[str, object]) -> prepare.PrepareRequest:
    """Convert canonical prepare-tab values into a preparation request."""
    def text(name: str) -> str:
        value = values[name]
        return value.strip() if isinstance(value, str) else str(value).strip()

    mode = text("mode").lower()
    if mode not in {"audio", "video"}:
        raise ValueError("Mode must be audio or video")
    settings = app_config.recap_settings()
    return prepare.PrepareRequest(
        mode=mode,
        media_file=Path(text("media_file")),
        image_type=text("image_type") or None,
        artist=text("artist"),
        title=text("title"),
        language=text("language"),
        output_directory=Path(text("output_directory")) if text("output_directory") else None,
        upload=bool(values["upload"]),
        subtitles=bool(values["subtitles"]),
        overwrite_existing=bool(values["overwrite_existing"]),
        clear_upload_cache=bool(values["clear_upload_cache"]),
        ffmpeg=str(settings["ffmpeg"]),
        ffprobe=str(settings["ffprobe"]),
    )


def build_batch_download_request(values: Mapping[str, object]) -> batch.BatchDownloadRequest:
    """Convert Batch download tab values into a batch request."""
    def text(name: str) -> str:
        value = values[name]
        return value.strip() if isinstance(value, str) else str(value).strip()

    input_path = text("input")
    if not input_path:
        raise ValueError("Choose a JSON or CSV input file")
    output_directory = text("output_directory")
    if not output_directory:
        raise ValueError("Choose an output directory")
    temporary_directory = text("temporary_directory")
    jobs = int(text("jobs"))
    if jobs < 0:
        raise ValueError("Concurrent downloads cannot be negative")
    return batch.BatchDownloadRequest(
        input=Path(input_path),
        api_query=None,
        output_directory=Path(output_directory),
        temporary_directory=Path(temporary_directory) if temporary_directory else None,
        browser=None,
        ffmpeg=None,
        ffprobe=None,
        jobs=jobs,
        upload=bool(values["upload"]),
        update_song_links=bool(values["update_song_links"]),
        overwrite=bool(values["overwrite"]),
        dry_run=bool(values["dry_run"]),
    )


def recap_mode_from_label(label: str) -> str:
    for value, display_name in RECAP_MODES:
        if label == display_name:
            return value
    raise ValueError(f"Unknown recap mode: {label}")


def build_args(values: Mapping[str, object]) -> common.Args:
    """Convert canonical GUI values into the command-line argument model."""
    def text(name: str) -> str:
        value = values[name]
        return value.strip() if isinstance(value, str) else str(value).strip()

    tmpdir = Path(text("temp_dir"))
    size_text = text("size")
    recap_mode = text("recap_mode")
    if recap_mode not in {value for value, _label in RECAP_MODES}:
        recap_mode = recap_mode_from_label(recap_mode)

    return common.Args(
        csv=Path(text("input_file")),
        api_query=None,
        tmpdir=tmpdir,
        browser=text("browser").lower() or None,
        youtube_attestation_mode=text("youtube_attestation_mode"),
        po_token=text("po_token") or None,
        bgutil_url=text("bgutil_url") or None,
        style=text("style"),
        size=common.parse_size(size_text) if size_text else None,
        default_height=int(text("default_height")),
        output=Path(text("output")),
        fps=int(text("fps")),
        fade_duration=float(text("fade")),
        av1_preset=int(text("av1_preset")),
        av1_crf=int(text("av1_crf")),
        av1_threads=int(text("av1_threads")),
        opus_bitrate=text("opus_bitrate"),
        audio_normalization=text("audio_normalization"),
        jobs=int(text("jobs")),
        multiprocessing=bool(values["multiprocessing"]),
        cleanup=bool(values["cleanup"]),
        ffmpeg=text("ffmpeg"),
        ffprobe=text("ffprobe"),
        inkscape=text("inkscape"),
        card_renderer=text("card_renderer"),
        resvg=text("resvg"),
        only_straight=recap_mode == "direct",
        only_reverse=recap_mode == "reverse",
        vidsdir=tmpdir / "sources",
        cardsdir=tmpdir / "cards",
        clipsdir=tmpdir / "clips",
        upload_recaps=bool(values.get("upload_recaps", True)),
    )


def normalise_show_entry(values: Mapping[str, object]) -> tuple[dict[str, str] | None, list[str]]:
    """Validate and normalize one editable show entry."""
    entry = {
        field: "" if values.get(field) is None else str(values.get(field, "")).strip()
        for field, _label in SHOW_FIELDS
    }
    missing = [field for field in SHOW_REQUIRED_FIELDS if not entry[field]]
    if missing:
        return None, missing
    entry["cc"] = entry["cc"].lower()
    entry["type"] = entry["type"].lower()
    return {field: value for field, value in entry.items() if value}, []


def load_show(path: Path) -> list[dict[str, str]]:
    """Read a canonical JSON show file."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        raise ValueError("expected a list of show entries")
    return [
        {
            field: str(entry.get(field, ""))
            for field, _label in SHOW_FIELDS
            if entry.get(field) is not None
        }
        for entry in value
    ]


def save_show(path: Path, entries: list[dict[str, str]]) -> Path:
    """Write a canonical JSON show file, ensuring its extension is JSON."""
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
