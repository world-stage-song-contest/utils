#!/usr/bin/env python3
from pathlib import Path
import xml.etree.ElementTree as ET
from dataclasses import dataclass
import csv
import multiprocessing as mp

import common
import svg

OFFSET = 25
MARGIN = 12
FONT_FAMILY_1 = "Aptos Display"
FONT_FAMILY_2 = "Compacta"

def convert_svg_to_png(svg_path: Path, png_path: Path, inkscape: str) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        inkscape,
        "--export-type=png",
        "--export-filename", str(png_path),
        "--export-background-opacity=0",
        str(svg_path)
    ]
    common.run(cmd, capture=False)

def make_70s_entry_svg(d: ET.Element, width: int, height: int, card_height: int,
                       v: common.Data, scheme: common.CS) -> ET.Element:
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
                        font_family=FONT_FAMILY_2)
    d.append(ro_text)

    country_text = svg.text(v.country, 60, line_offset + OFFSET, card_height // 2 + 70 + y_off,
                             fill=m[scheme.text], font_family=FONT_FAMILY_1)
    d.append(country_text)

    artist_text = svg.text(v.artist, 40, line_offset + OFFSET, card_height // 2 - 75 + y_off,
                            fill=m[scheme.text], font_family=FONT_FAMILY_1)
    d.append(artist_text)

    title_text = svg.text(v.title, 40, line_offset + OFFSET, card_height // 2 - 70 + 45 + y_off,
                           fill=m[scheme.text], font_weight="bold", font_family=FONT_FAMILY_1)
    d.append(title_text)

    return d

def make_90s_entry_svg(d: ET.Element, width: int, height: int, card_height: int,
                       v: common.Data, scheme: common.CS) -> ET.Element:
    style_el = svg.style(
        """
.number {
    font-family: "Source Han Sans VF";
    font-size: 54px;
    font-weight: bold;
    font-style: normal;
    text-anchor: end;
    dominant-baseline: auto;
    text-align: center;
}
.country    {
    font-family: "Aptos Narrow";
    text-transform: uppercase;
    font-size: 16px;
    font-style: normal;
    letter-spacing: 0.125em;
    text-anchor: end;
    dominant-baseline: auto;
    text-align: end;
}"""
    )
    d.append(style_el)

    top_rect = svg.rectangle(0, 0, 720, 90, "#000", opacity="0.72")
    d.append(top_rect)

    bottom_rect = svg.rectangle(0, 450, 720, 90, "#000", opacity="0.72")
    d.append(bottom_rect)

    ro_text = svg.text(f"{v.ro}", 0, 630, 504, fill="#fff", class_="number")
    d.append(ro_text)

    country_text = svg.text(v.country, 0, 630, 524, fill="#fff", class_="country")
    d.append(country_text)

    artist_text = svg.text(v.artist, 20, 90, 70, fill="#fff", font_weight="normal", font_family="Aptos Narrow")
    d.append(artist_text)

    title_text = svg.text(v.title, 36, 90, 45, fill="#fff", font_weight="bold", font_family="Aptos Narrow")
    d.append(title_text)

    return d

entry_functions = {
    "70s": make_70s_entry_svg,
    "90s": make_90s_entry_svg,
}

size_map = {
    "70s": (1920, 1080),
    "90s": (720, 540),
}

def process_entry(v: common.Data, img_width: int, img_height: int, style: str, outdir: Path, inkscape: str) -> None:
    base_name = f"{v.show}/{v.ro}_{v.cc}"
    svg_path = outdir / "svg" / f"{base_name}.svg"
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"{base_name}.png"
    if png_path.exists():
        print(f"[cards] {png_path} already exists, skipping.", file=common.OUT_HANDLE)
        return
    print(f"[cards] Processing {v.ro} {v.cc} ({v.show})", file=common.OUT_HANDLE)

    width, height = size_map[style]
    d = svg.svg(img_width, img_height, width, height, origin="top-left")

    if v.cc != 'XX':
        scheme = common.schemes[v.cc]

        make_entry_svg = entry_functions[style]
        make_entry_svg(d, width, height, height // 4, v, scheme)

    svg.save(d, svg_path)
    convert_svg_to_png(svg_path, png_path, inkscape)

def make_svgs(data: list[common.Data], size: tuple[int, int], style: str, outdir: Path, multi: bool, inkscape: str) -> None:
    if multi:
        with mp.Pool(mp.cpu_count()//2) as pool:
            pool.starmap(process_entry, [(v, size[0], size[1], style, outdir, inkscape) for v in data])
    else:
        for v in data:
            process_entry(v, size[0], size[1], style, outdir, inkscape)

def main(args: common.Args, data: list[common.Data]) -> None:
    args.cardsdir.mkdir(parents=True, exist_ok=True)
    make_svgs(data, args.size, args.style, Path(args.cardsdir), args.multiprocessing, args.inkscape)
