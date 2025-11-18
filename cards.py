#!/usr/bin/env python3
from pathlib import Path
import xml.etree.ElementTree as ET
from dataclasses import dataclass
import csv
import multiprocessing as mp

import common
import svg

@dataclass
class Data:
    show: str
    country: str
    country_name: str
    artist: str
    title: str
    ro: str

    def __init__(self, show: str, country: str, country_name: str, artist: str, title: str, ro: str):
        self.show = show
        self.country = country
        self.country_name = country_name
        self.artist = artist
        self.title = title
        self.ro = ro

OFFSET = 25
MARGIN = 12
FONT_FAMILY = "Eurostile Next LT Pro"

def convert_svg_to_png(svg_path: Path, png_path: Path, inkscape: str) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        inkscape,
        "--export-type=png",
        "--export-filename", str(png_path),
        str(svg_path)
    ]
    common.run(cmd, capture=False)

def make_70s_entry_svg(d: ET.Element, width: int, height: int, card_height: int,
                       v: Data, scheme: common.CS) -> ET.Element:
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

    ro_text = svg.text(f"{v.ro}", 120, card_height // 2 + OFFSET, card_height // 2 + y_off + 15,
                        fill=m[scheme.text], text_anchor="middle", dominant_baseline="middle",
                        alignment_baseline="middle", text_align="center",
                        font_family=FONT_FAMILY)
    d.append(ro_text)

    country_text = svg.text(v.country_name, 60, line_offset + OFFSET, card_height // 2 + 70 + y_off,
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

def read_input(path: Path) -> list[Data]:
    shows = []
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            typ = (row.get("type", '') or 'v').strip()
            if typ != "v":
                continue
            rro = row["running_order"].strip()
            try:
                ro = f"{int(rro):02d}"
            except ValueError:
                ro = rro
            show = row["show"]
            ro = ro
            country = row["country"]
            country_name = row["country_name"]
            artist = row["artist"]
            title = row["title"]
            shows.append(Data(show, country, country_name, artist, title, ro))
    return shows

width, height = 1980, 1080

def process_entry(v: Data, img_width: int, img_height: int, style: str, outdir: Path, inkscape: str) -> None:
    base_name = f"{v.show}/{v.ro}_{v.country}"
    svg_path = outdir / "svg" / f"{base_name}.svg"
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"{base_name}.png"
    if png_path.exists():
        print(f"[cards] {png_path} already exists, skipping.", file=common.OUT_HANDLE)
        return
    print(f"[cards] Processing {v.ro:02} {v.country} ({v.show})", file=common.OUT_HANDLE)
    d = svg.svg(img_width * 0.925, img_height * 0.925, width, height, origin="top-left")

    if v.country != 'XXX':
        scheme = common.schemes[v.country]

        make_entry_svg = entry_functions[style]
        make_entry_svg(d, width, height, height // 4, v, scheme)

    svg.save(d, svg_path)
    convert_svg_to_png(svg_path, png_path, inkscape)

def make_svgs(data: list[Data], size: tuple[int, int], style: str, outdir: Path, multi: bool, inkscape: str) -> None:
    if multi:
        with mp.Pool(mp.cpu_count() - 2) as pool:
            pool.starmap(process_entry, [(v, size[0], size[1], style, outdir, inkscape) for v in data])
    else:
        for v in data:
            process_entry(v, size[0], size[1], style, outdir, inkscape)

def main(args: common.Args) -> None:
    args.cardsdir.mkdir(parents=True, exist_ok=True)
    data = read_input(Path(args.csv))
    make_svgs(data, args.size, args.style, Path(args.cardsdir), args.multiprocessing, args.inkscape)
