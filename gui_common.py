"""Toolkit-independent behaviour shared by the recap-maker GUIs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import json
import traceback

import common
import main
import prepare


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

    def write(self, message: str) -> None:
        if message:
            self.output_queue.put((self.tag, message))

    def flush(self) -> None:
        pass


def run_recap_process(args: common.Args, output_queue) -> None:
    """Run the maker while forwarding its output through ``output_queue``."""
    common.OUT_HANDLE = QueueWriter(output_queue, "stdout")
    common.ERR_HANDLE = QueueWriter(output_queue, "stderr")
    try:
        main.exec(args)
    except BaseException:
        traceback.print_exc(file=common.ERR_HANDLE)


def build_prepare_request(values: Mapping[str, object]) -> prepare.PrepareRequest:
    """Convert canonical prepare-tab values into a preparation request."""
    def text(name: str) -> str:
        value = values[name]
        return value.strip() if isinstance(value, str) else str(value).strip()

    mode = text("mode").lower()
    if mode not in {"audio", "video"}:
        raise ValueError("Mode must be audio or video")
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
    )


def run_prepare_process(request: prepare.PrepareRequest, output_queue) -> None:
    """Run one preparation request while forwarding application output."""
    prepare.OUT_HANDLE = QueueWriter(output_queue, "stdout")
    prepare.ERR_HANDLE = QueueWriter(output_queue, "stderr")
    try:
        prepare.execute(request)
    except BaseException:
        traceback.print_exc(file=prepare.ERR_HANDLE)


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
        tmpdir=tmpdir,
        browser=text("browser").lower() or None,
        po_token=text("po_token") or None,
        style=text("style"),
        size=common.parse_size(size_text) if size_text else None,
        auto_height=int(text("auto_height")),
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
        yt_dlp=text("yt_dlp"),
        inkscape=text("inkscape"),
        card_renderer=text("card_renderer"),
        resvg=text("resvg"),
        only_straight=recap_mode == "direct",
        only_reverse=recap_mode == "reverse",
        vidsdir=tmpdir / "sources",
        cardsdir=tmpdir / "cards",
        clipsdir=tmpdir / "clips",
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
