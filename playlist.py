#!/usr/bin/env python3
import argparse
from pathlib import Path

header = "#EXTM3U"
line1 = "#EXTINF:0"
line2 = "#EXTVLCOPT:network-caching=3000"
video_url = "https://media.world-stage.org"
postc_url = "https://yghj.eu/worldstage"
recap_url = "https://funcall.me/data/recaps"

def main() -> None:
    parser = argparse.ArgumentParser(description="Process recap videos.")

    parser.add_argument("file", type=Path, help="File with country codes")

    args = parser.parse_args()
    path: Path = args.file

    base = path.stem
    year = base[0:4]
    show = base[4:]
    cards = path.with_name(f"{base}.m3u")
    nocards = path.with_name(f"{base}x.m3u")

    with (path.open() as f,
          cards.open("w+") as o,
          nocards.open("w+") as ox):
        print(header, file=o)
        print(header, file=ox)
        for line in f:
            cc, *extt = line.strip().split('.', maxsplit=2)
            if not extt:
                ext = 'mov'
            else:
                ext = extt[0]
            print(line1, file=o)
            print(line2, file=o)
            print(f"{postc_url}/postcards/{cc}.mov", file=o)
            print(line1, file=o)
            print(line2, file=o)
            print(f"{video_url}/ws{year}{cc}.mov", file=o)

            print(line1, file=ox)
            print(line2, file=ox)
            print(f"{video_url}/ws{year}{cc}.{ext}", file=ox)

        print(line1, file=o)
        print(line2, file=o)
        print(f"{recap_url}/{year}{show}.mov", file=o)

if __name__ == '__main__':
    main()