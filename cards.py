#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys
import drawsvg as draw # type: ignore
from dataclasses import dataclass
import csv
import argparse
import multiprocessing as mp

import common

@dataclass
class V:
    year: int
    show: str
    country: str
    artist: str
    title: str
    ro: int
    display_name: str

    def __init__(self, year: int, show: str, country: str, artist: str, title: str, ro: int, display_name: str | None = None):
        self.year = year
        self.show = show
        self.country = country
        self.artist = artist
        self.title = title
        self.ro = ro
        self.display_name = display_name or common.schemes[country].name

@dataclass
class Args:
    csv: Path
    outdir: Path
    style: str
    size: tuple[int, int]
    multiprocessing: bool

offset = 25
margin = 12
font_family = "Eurostile Next LT Pro"

def convert_svg_to_png(svg_path: Path, png_path: Path) -> None:
    cmd = [
        "inkscape",
        "--export-type=png",
        "--export-filename", str(png_path),
        str(svg_path)
    ]
    common.run(cmd, capture=False)

def make_70s_entry_svg(d: draw.Drawing, width: int, height: int, card_height: int,
                       v: V, scheme: common.CS) -> draw.Drawing:
    m = common.colours["70s"]
    y_off = height - card_height
    c1_diameter = card_height - 2 * margin
    c2_diameter = c1_diameter - 3.5 * margin
    line_offset = c1_diameter + offset + margin

    rect = draw.Rectangle(0, y_off, width, card_height, fill=m[scheme.bg])
    d.append(rect)
    circle1 = draw.Circle(card_height // 2 + offset, card_height // 2 + y_off, c1_diameter // 2, stroke=m[scheme.fg1], stroke_width=margin, fill="none")
    d.append(circle1)
    circle2 = draw.Circle(card_height // 2 + offset, card_height // 2 + y_off, c2_diameter // 2, stroke=m[scheme.fg2], stroke_width=margin, fill="none")
    d.append(circle2)
    line = draw.Line(line_offset, card_height // 2 + y_off, width, card_height // 2 + y_off, stroke=m[scheme.fg1], stroke_width=margin)
    d.append(line)

    ro_text = draw.Text(f"{v.ro:02}", 120, card_height // 2 + offset, card_height // 2 + y_off + 15,
                        fill=m[scheme.text], text_anchor="middle", dominant_baseline="middle",
                        font_family=font_family)
    d.append(ro_text)

    country_text = draw.Text(v.display_name, 60, line_offset + offset, card_height // 2 + 70 + y_off,
                             fill=m[scheme.text], font_family=font_family)
    d.append(country_text)

    artist_text = draw.Text(v.artist, 40, line_offset + offset, card_height // 2 - 75 + y_off,
                            fill=m[scheme.text], font_family=font_family)
    d.append(artist_text)

    title_text = draw.Text(v.title, 40, line_offset + offset, card_height // 2 - 70 + 45 + y_off,
                           fill=m[scheme.text], font_weight="bold", font_family=font_family)
    d.append(title_text)

    return d

entry_functions = {
    "70s": make_70s_entry_svg,
}

def read_input(path: Path) -> list[V]:
    shows = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            year = int(row["year"])
            show = row["show"]
            ro = int(row["running_order"])
            country = row["country"]
            artist = row["artist"]
            title = row["title"]
            display_name = row["display_name"] or country
            shows.append(V(year, show, country, artist, title, ro, display_name))
    return shows


def process_entry(v: V, width: int, height: int, style: str, outdir: Path) -> None:
    base_name = f"{v.year}_{v.show}_{v.ro:02}_{v.country}"
    svg_path = outdir / "svg" / f"{base_name}.svg"
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"{base_name}.png"
    if png_path.exists():
        common.write(f"[cards] {png_path} already exists, skipping.")
        return
    common.write(f"[cards] Processing {v.ro:02} {v.country} ({v.year} {v.show})")
    d = draw.Drawing(1920, 1080, origin="top-left")

    scheme = common.schemes[v.country]

    make_entry_svg = entry_functions[style]
    make_entry_svg(d, width, height, height // 4, v, scheme)

    d.save_svg(svg_path)
    convert_svg_to_png(svg_path, png_path)

def make_svgs(data: list[V], size: tuple[int, int], style: str, outdir: Path, multi: bool) -> None:
    if multi:
        with mp.Pool() as pool:
            pool.starmap(process_entry, [(v, size[0], size[1], style, outdir) for v in data])
    else:
        for v in data:
            process_entry(v, size[0], size[1], style, outdir)

def main(args: Args) -> None:
    args.outdir.mkdir(parents=True, exist_ok=True)
    data = read_input(Path(args.csv))
    make_svgs(data, args.size, args.style, Path(args.outdir), args.multiprocessing)

if __name__ == "__main__":
    if not shutil.which("inkscape"):
        common.error("Error: Inkscape is not installed or not found in PATH.", file=sys.stderr)
        sys.exit(1)

    ap = argparse.ArgumentParser(
        description="Make recap cards"
    )
    ap.add_argument("csv", type=Path, help="CSV file with show data")
    ap.add_argument("outdir", type=Path, default="output", nargs="?",
                    help="Output directory for the cards")
    ap.add_argument("--size", default="1920x1080", type=common.parse_size,
                    help="target frame size WxH")
    ap.add_argument("--style", default="70s", help="Style to use for the cards")
    ap.add_argument("--multiprocessing", action="store_true",
                    help="Use multiprocessing to speed up the processing of cards")
    args = ap.parse_args()

    ar = Args(
        csv=args.csv,
        outdir=args.outdir,
        multiprocessing=args.multiprocessing,
        style=args.style,
        size=args.size
    )

    if ar.style not in entry_functions:
        common.error(f"Error: Style '{ar.style}' is not supported.", file=sys.stderr)
        sys.exit(1)

    try:
        main(ar)
    except KeyboardInterrupt as e:
        sys.exit(1)