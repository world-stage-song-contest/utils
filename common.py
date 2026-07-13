from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess as sp
import sys
import ctypes
import csv
import json
from typing import cast

OUT_HANDLE = sys.stdout
ERR_HANDLE = sys.stderr

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()  # type: ignore
    except Exception:
        return False

def parse_size(arg: str) -> tuple[int, int]:
    w, h = map(int, arg.lower().split("x"))
    return w, h


def media_type(value: object) -> str:
    """Normalise the legacy and JSON media-type spellings."""
    text = str(value or "v").strip().lower()
    return {"video": "v", "audio": "a"}.get(text, text)


def load_rows(path: Path) -> list[dict[str, str]]:
    """Load CSV or JSON metadata into the canonical JSON field schema.

    Both formats require the same fields: ``ro``, ``cc``, ``country``, and
    ``media_link``.
    """
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            source_rows: list[dict[str, object]] = [
                cast(dict[str, object], dict(row)) for row in csv.DictReader(f)
            ]
    elif path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise ValueError(f"JSON input must be a list of metadata objects: {path}")
        source_rows = [cast(dict[str, object], row) for row in value]
    else:
        raise ValueError(f"Unsupported input format for {path}; expected .csv or .json")

    rows: list[dict[str, str]] = []
    for source in source_rows:
        row = {key: "" if value is None else str(value) for key, value in source.items()}
        row["type"] = media_type(row.get("type", "v"))
        rows.append(row)
    return rows

def run(cmd: list[str] | str, *, capture: bool = True) -> sp.CompletedProcess[str]:
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    print(shlex.join(cmd), file=OUT_HANDLE)
    try:
        return sp.run(
            cmd,
            stdout=sp.PIPE if capture else None,
            stderr=sp.PIPE if capture else None,
            text=True,
            check=True,
        )
    except sp.CalledProcessError as e:
        message = f"\n[cmd] {' '.join(map(shlex.quote, cmd))}\n[stderr]\n{e.stderr or ''}"
        print(message, file=ERR_HANDLE)
        raise RuntimeError(message) from e

# show, ro
Clips = dict[tuple[str, str], dict[str, Path]]

@dataclass
class Args:
    csv: Path
    style: str
    tmpdir: Path
    browser: str | None
    po_token: str | None
    size: tuple[int, int] | None
    default_height: int
    fps: int
    fade_duration: float
    av1_preset: int
    av1_crf: int
    av1_threads: int
    opus_bitrate: str
    audio_normalization: str
    jobs: int
    output: Path
    multiprocessing: bool
    cleanup: bool
    ffmpeg: str
    ffprobe: str
    inkscape: str
    card_renderer: str
    resvg: str
    only_straight: bool
    only_reverse: bool
    vidsdir: Path
    cardsdir: Path
    clipsdir: Path
    upload_recaps: bool = True

from country_schemes import CS, schemes


colours = {
    "70s": {
        "white": "#EEEEEE",
        "grey": "#C0C0C0",
        "black": "#111111",
        "red": "#D21034",
        "maroon": "#8A1538",
        "orange": "#FF7900",
        "yellow": "#FEDD00",
        "gold": "#C69214",
        "green": "#008751",
        "darkgreen": "#004225",
        "blue": "#0052B4",
        "navy": "#00205B",
        "cyan": "#77B5FE",
        "turquoise": "#0095B6",
        "purple": "#522D80",
        "brown": "#7C4A0E",
    }
}


show_name_map = {
    "sf": "Semi-Final",
    "sf1": "Semi-Final 1",
    "sf2": "Semi-Final 2",
    "sf3": "Semi-Final 3",
    "sf4": "Semi-Final 4",
    "dtf": "Direct Qualifiers",
    "sc": "Repechage",
    "f": "Final",
}
