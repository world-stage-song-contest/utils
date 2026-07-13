#!/usr/bin/env python3
from pathlib import Path
import xml.etree.ElementTree as ET
from dataclasses import dataclass
import hashlib
import json
import multiprocessing as mp
import sqlite3
import struct

import common
import country_schemes
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
FONT_FAMILY_1 = "Aptos Display"
FONT_FAMILY_2 = "Compacta"

CARD_RENDER_VERSION = 1


def convert_svg_to_png(svg_path: Path, png_path: Path, renderer: str, inkscape: str, resvg: str) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    if renderer == "inkscape":
        cmd = [inkscape, "--export-type=png", "--export-filename", str(png_path), str(svg_path)]
    elif renderer == "resvg":
        cmd = [resvg, "-o", str(png_path), str(svg_path)]
    else:
        raise ValueError(f"Unsupported card renderer: {renderer}")
    common.run(cmd, capture=False)

def make_70s_entry_svg(d: ET.Element, width: int, height: int, card_height: int,
                       v: Data, scheme: country_schemes.CS) -> ET.Element:
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

    country_text = svg.text(v.country_name, 60, line_offset + OFFSET, card_height // 2 + 70 + y_off,
                             fill=m[scheme.text], font_family=FONT_FAMILY_1)
    d.append(country_text)

    artist_text = svg.text(v.artist, 40, line_offset + OFFSET, card_height // 2 - 75 + y_off,
                            fill=m[scheme.text], font_family=FONT_FAMILY_1)
    d.append(artist_text)

    title_text = svg.text(v.title, 40, line_offset + OFFSET, card_height // 2 - 70 + 45 + y_off,
                           fill=m[scheme.text], font_weight="bold", font_family=FONT_FAMILY_1)
    d.append(title_text)

    return d

entry_functions = {
    "70s": make_70s_entry_svg,
}

def read_input(path: Path) -> list[Data]:
    shows = []
    for row in common.load_rows(path):
        typ = row["type"]
        if typ not in {"v", "a"}:
            continue
        rro = row["ro"].strip()
        try:
            ro = f"{int(rro):02d}"
        except ValueError:
            ro = rro
        show = row["show"].strip()
        country = row["cc"].strip().upper()
        country_name = row["country"].strip()
        artist = row["artist"].strip()
        title = row["title"].strip()
        shows.append(Data(show, country, country_name, artist, title, ro))
    return shows

width, height = 1980, 1080


def png_size(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as f:
        header = f.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", header[16:24])


def cache_database_path(cards_dir: Path) -> Path:
    return cards_dir / "card-cache.sqlite3"


def initialize_cache(database: Path) -> None:
    with sqlite3.connect(database, timeout=30) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS cards (path TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)")


def card_fingerprint(v: Data, size: tuple[int, int], style: str, renderer: str) -> str:
    value = {
        "version": CARD_RENDER_VERSION, "show": v.show, "country": v.country,
        "country_name": v.country_name, "artist": v.artist, "title": v.title,
        "ro": v.ro, "size": size, "style": style, "renderer": renderer,
    }
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def cached_fingerprint(database: Path, path: Path) -> str | None:
    with sqlite3.connect(database, timeout=30) as conn:
        row = conn.execute("SELECT fingerprint FROM cards WHERE path = ?", (str(path.absolute()),)).fetchone()
    return None if row is None else row[0]


def store_fingerprint(database: Path, path: Path, fingerprint: str) -> None:
    with sqlite3.connect(database, timeout=30) as conn:
        conn.execute("""
            INSERT INTO cards (path, fingerprint) VALUES (?, ?)
            ON CONFLICT(path) DO UPDATE SET fingerprint = excluded.fingerprint
        """, (str(path.absolute()), fingerprint))


def process_entry(
    v: Data, img_width: int, img_height: int, style: str, outdir: Path,
    renderer: str, inkscape: str, resvg: str,
) -> None:
    base_name = f"{v.show}/{v.ro}_{v.country}"
    svg_path = outdir / "svg" / f"{base_name}.svg"
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    png_path = outdir / f"{base_name}.png"
    expected_size = (round(img_width * 0.925), round(img_height * 0.925))
    database = cache_database_path(outdir)
    fingerprint = card_fingerprint(v, (img_width, img_height), style, renderer)
    if (
        png_path.exists() and png_size(png_path) == expected_size
        and cached_fingerprint(database, png_path) == fingerprint
    ):
        print(f"[cards] {png_path} already exists, skipping.", file=common.OUT_HANDLE)
        return
    if png_path.exists():
        print(f"[cards] {png_path} has the wrong size; regenerating.", file=common.OUT_HANDLE)
    print(f"[cards] Processing {v.ro:02} {v.country} ({v.show})", file=common.OUT_HANDLE)
    d = svg.svg(img_width * 0.925, img_height * 0.925, width, height, origin="top-left")

    if v.country != 'XXX':
        scheme = country_schemes.schemes[v.country]

        make_entry_svg = entry_functions[style]
        make_entry_svg(d, width, height, height // 4, v, scheme)

    svg.save(d, svg_path)
    convert_svg_to_png(svg_path, png_path, renderer, inkscape, resvg)
    store_fingerprint(database, png_path, fingerprint)

def make_svgs(
    data: list[Data], size: tuple[int, int], style: str, outdir: Path, multi: bool,
    renderer: str, inkscape: str, resvg: str,
) -> None:
    if multi:
        with mp.Pool(mp.cpu_count()//2) as pool:
            pool.starmap(process_entry, [
                (v, size[0], size[1], style, outdir, renderer, inkscape, resvg) for v in data
            ])
    else:
        for v in data:
            process_entry(v, size[0], size[1], style, outdir, renderer, inkscape, resvg)

def main(args: common.Args) -> None:
    if args.size is None:
        raise RuntimeError("Output size must be resolved before generating cards")
    args.cardsdir.mkdir(parents=True, exist_ok=True)
    initialize_cache(cache_database_path(args.cardsdir))
    data = read_input(Path(args.csv))
    make_svgs(
        data, args.size, args.style, Path(args.cardsdir), args.multiprocessing,
        args.card_renderer, args.inkscape, args.resvg,
    )
