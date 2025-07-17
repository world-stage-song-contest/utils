#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
import csv
import argparse
import multiprocessing as mp

import common
import svg

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
    inkscape: str

OFFSET = 25
MARGIN = 12
FONT_FAMILY = "Eurostile Next LT Pro"

def convert_svg_to_png(svg_path: Path, png_path: Path, inkscape: str) -> None:
    cmd = [
        inkscape,
        "--export-type=png",
        "--export-filename", str(png_path),
        str(svg_path)
    ]
    common.run(cmd, capture=False)

def make_70s_entry_svg(d: ET.Element, width: int, height: int, card_height: int,
                       v: V, scheme: common.CS) -> ET.Element:
    m = common.colours["70s"]
    y_off = height - card_height
    c1_diameter = card_height - 2 * MARGIN
    c2_diameter = c1_diameter - 3.5 * MARGIN
    line_offset = c1_diameter + OFFSET + MARGIN

    rect = svg.rectangle(0, y_off, width, card_height, fill=m[scheme.bg])
    d.append(rect)
    circle1 = svg.circle(card_height // 2 + OFFSET, card_height // 2 + y_off, c1_diameter // 2, stroke=m[scheme.fg1], stroke_width=MARGIN, fill="none")
    d.append(circle1)
    circle2 = svg.circle(card_height // 2 + OFFSET, card_height // 2 + y_off, c2_diameter // 2, stroke=m[scheme.fg2], stroke_width=MARGIN, fill="none")
    d.append(circle2)
    line = svg.line(line_offset, card_height // 2 + y_off, width, card_height // 2 + y_off, stroke=m[scheme.fg1], stroke_width=MARGIN)
    d.append(line)

    ro_text = svg.text(f"{v.ro:02}", 120, card_height // 2 + OFFSET, card_height // 2 + y_off + 15,
                        fill=m[scheme.text], text_anchor="middle", dominant_baseline="middle",
                        font_family=FONT_FAMILY)
    d.append(ro_text)

    country_text = svg.text(v.display_name, 60, line_offset + OFFSET, card_height // 2 + 70 + y_off,
                             fill=m[scheme.text], font_family=FONT_FAMILY)
    d.append(country_text)

    artist_text = svg.text(v.artist, 40, line_offset + OFFSET, card_height // 2 - 75 + y_off,
                            fill=m[scheme.text], font_family=FONT_FAMILY)
    d.append(artist_text)

    title_text = svg.text(v.title, 40, line_offset + OFFSET, card_height // 2 - 70 + 45 + y_off,
                           fill=m[scheme.text], font_weight="bold", font_family=FONT_FAMILY)
    d.append(title_text)

    return d

entry_functions = {
    "70s": make_70s_entry_svg,
}

def read_input(path: Path) -> list[V]:
    shows = []
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            year = int(row["year"])
            show = row["show"]
            ro = int(row["running_order"])
            country = row["country"]
            artist = row["artist"]
            title = row["title"]
            display_name = row["display_name"]
            shows.append(V(year, show, country, artist, title, ro, display_name))
    return shows

def process_entry(v: V, width: int, height: int, style: str, outdir: Path, inkscape: str) -> None:
    base_name = f"{v.year}_{v.show}_{v.ro:02}_{v.country}"
    svg_path = outdir / "svg" / f"{base_name}.svg"
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"{base_name}.png"
    if png_path.exists():
        print(f"[cards] {png_path} already exists, skipping.", file=common.OUT_HANDLE)
        return
    print(f"[cards] Processing {v.ro:02} {v.country} ({v.year} {v.show})", file=common.OUT_HANDLE)
    d = svg.svg(1920, 1080, origin="top-left")

    scheme = common.schemes[v.country]

    make_entry_svg = entry_functions[style]
    make_entry_svg(d, width, height, height // 4, v, scheme)

    svg.save(d, svg_path)
    convert_svg_to_png(svg_path, png_path, inkscape)

def make_svgs(data: list[V], size: tuple[int, int], style: str, outdir: Path, multi: bool, inkscape: str) -> None:
    if multi:
        with mp.Pool() as pool:
            pool.starmap(process_entry, [(v, size[0], size[1], style, outdir, inkscape) for v in data])
    else:
        for v in data:
            process_entry(v, size[0], size[1], style, outdir, inkscape)

def main(args: Args) -> None:
    args.outdir.mkdir(parents=True, exist_ok=True)
    data = read_input(Path(args.csv))
    make_svgs(data, args.size, args.style, Path(args.outdir), args.multiprocessing, args.inkscape)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Make recap cards"
    )
    ap.add_argument("csv", type=Path, help="CSV file with show data")
    ap.add_argument("outdir", type=Path, default="output", nargs="?",
                    help="Output directory for the cards")
    ap.add_argument("--size", default="1920x1080", type=common.parse_size,
                    help="target frame size WxH")
    ap.add_argument("--style", required=True, choices=entry_functions.keys(),
                    help="Style to use for the cards")
    ap.add_argument("--multiprocessing", action="store_true",
                    help="Use multiprocessing to speed up the processing of cards")
    ap.add_argument("--inkscape", default="inkscape", help="Path to the inkscape executable")
    args = ap.parse_args()

    if not shutil.which(args.inkscape):
        print(f"Error: {args.inkscape} not found", file=common.ERR_HANDLE)
        sys.exit(1)

    ar = Args(
        csv=args.csv,
        outdir=args.outdir,
        multiprocessing=args.multiprocessing,
        style=args.style,
        size=args.size,
        inkscape=args.inkscape
    )

    if ar.style not in entry_functions:
        print(f"Error: Style '{ar.style}' is not supported.", file=common.ERR_HANDLE)
        sys.exit(1)

    try:
        main(ar)
    except KeyboardInterrupt as e:
        sys.exit(1)