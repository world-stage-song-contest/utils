#!/usr/bin/env python3
import shlex
import argparse, json, math, os, re, sys
import subprocess as sp
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Union

base_url = 'https://media.world-stage.org'

cc_map = {
    "ab": "Scotland",
    "ad": "Andorra",
    "ae": "United Arab Emirates",
    "af": "Afghanistan",
    "ag": "Antigua and Barbuda",
    "ai": "Anguilla",
    "al": "Albania",
    "am": "Armenia",
    "ao": "Angola",
    "aq": "Antarctica",
    "ar": "Argentina",
    "as": "American Samoa",
    "at": "Austria",
    "au": "Australia",
    "aw": "Aruba",
    "ax": "Åland Islands",
    "az": "Azerbaijan",
    "ba": "Bosnia and Herzegovina",
    "bb": "Barbados",
    "bd": "Bangladesh",
    "be": "Belgium",
    "bf": "Burkina Faso",
    "bg": "Bulgaria",
    "bh": "Bahrain",
    "bi": "Burundi",
    "bj": "Benin",
    "bm": "Bermuda",
    "bn": "Brunei",
    "bo": "Bolivia",
    "br": "Brazil",
    "bs": "Bahamas",
    "bt": "Bhutan",
    "bv": "Bouvet Island",
    "bw": "Botswana",
    "by": "Belarus",
    "bz": "Belize",
    "ca": "Canada",
    "cc": "Cocos Islands",
    "cd": "Zaire",
    "cf": "Central African Republic",
    "cg": "Congo",
    "ch": "Switzerland",
    "ci": "Ivory Coast",
    "ck": "Cook Islands",
    "cl": "Chile",
    "cm": "Cameroon",
    "cn": "China",
    "co": "Colombia",
    "cr": "Costa Rica",
    "cs": "Czechoslovakia",
    "cu": "Cuba",
    "cv": "Cabo Verde",
    "cw": "Curaçao",
    "cx": "Christmas Island",
    "cy": "Cyprus",
    "cz": "Czechia",
    "dd": "East Germany",
    "de": "West Germany",
    "dj": "Djibouti",
    "dk": "Denmark",
    "dm": "Dominica",
    "do": "Dominican Republic",
    "dz": "Algeria",
    "ec": "Ecuador",
    "ee": "Estonia",
    "eg": "Egypt",
    "eh": "Western Sahara",
    "en": "England",
    "er": "Eritrea",
    "es": "Spain",
    "et": "Ethiopia",
    "eu": "European Union",
    "fi": "Finland",
    "fj": "Fiji",
    "fm": "Micronesia",
    "fo": "Faroe Islands",
    "fr": "France",
    "ga": "Gabon",
    "gb": "United Kingdom",
    "gd": "Grenada",
    "ge": "Georgia",
    "gf": "French Guiana",
    "gg": "Guernsey",
    "gh": "Ghana",
    "gi": "Gibraltar",
    "gl": "Greenland",
    "gm": "Gambia",
    "gn": "Guinea",
    "gp": "Guadeloupe",
    "gq": "Equatorial Guinea",
    "gr": "Greece",
    "gt": "Guatemala",
    "gu": "Guam",
    "gw": "Guinea-Bissau",
    "gy": "Guyana",
    "hk": "Hong Kong",
    "hn": "Honduras",
    "hr": "Croatia",
    "ht": "Haiti",
    "hu": "Hungary",
    "id": "Indonesia",
    "ie": "Ireland",
    "il": "Israel",
    "im": "Isle of Man",
    "in": "India",
    "iq": "Iraq",
    "ir": "Iran",
    "is": "Iceland",
    "it": "Italy",
    "je": "Jersey",
    "jm": "Jamaica",
    "jo": "Jordan",
    "jp": "Japan",
    "ke": "Kenya",
    "kg": "Kyrgyzstan",
    "kh": "Cambodia",
    "ki": "Kiribati",
    "km": "Comoros",
    "kn": "Saint Kitts and Nevis",
    "kp": "North Korea",
    "kr": "South Korea",
    "kw": "Kuwait",
    "ky": "Cayman Islands",
    "kz": "Kazakhstan",
    "la": "Laos",
    "lb": "Lebanon",
    "lc": "Saint Lucia",
    "li": "Liechtenstein",
    "lk": "Sri Lanka",
    "lr": "Liberia",
    "ls": "Lesotho",
    "lt": "Lithuania",
    "lu": "Luxembourg",
    "lv": "Latvia",
    "ly": "Libya",
    "ma": "Morocco",
    "mc": "Monaco",
    "md": "Moldova",
    "me": "Montenegro",
    "mg": "Madagascar",
    "mh": "Marshall Islands",
    "mk": "North Macedonia",
    "ml": "Mali",
    "mm": "Burma",
    "mn": "Mongolia",
    "mo": "Macao",
    "mq": "Martinique",
    "mr": "Mauritania",
    "ms": "Montserrat",
    "mt": "Malta",
    "mu": "Mauritius",
    "mv": "Maldives",
    "mw": "Malawi",
    "mx": "Mexico",
    "my": "Malaysia",
    "mz": "Mozambique",
    "na": "Namibia",
    "ne": "Niger",
    "ng": "Nigeria",
    "ni": "Nicaragua",
    "nl": "Netherlands",
    "no": "Norway",
    "np": "Nepal",
    "nr": "Nauru",
    "nu": "Niue",
    "nz": "New Zealand",
    "om": "Oman",
    "pa": "Panama",
    "pe": "Peru",
    "pg": "Papua New Guinea",
    "ph": "Philippines",
    "pk": "Pakistan",
    "pl": "Poland",
    "pm": "Saint Pierre and Miquelon",
    "pn": "Pitcairn",
    "pr": "Puerto Rico",
    "ps": "Palestine",
    "pt": "Portugal",
    "pv": "Basque Country",
    "pw": "Palau",
    "py": "Paraguay",
    "qa": "Qatar",
    "re": "Réunion",
    "ro": "Romania",
    "rs": "Serbia",
    "ru": "Russia",
    "rw": "Rwanda",
    "sa": "Saudi Arabia",
    "sb": "Solomon Islands",
    "sc": "Seychelles",
    "sd": "Sudan",
    "se": "Sweden",
    "sg": "Singapore",
    "si": "Slovenia",
    "sk": "Slovakia",
    "sl": "Sierra Leone",
    "sm": "San Marino",
    "sn": "Senegal",
    "so": "Somalia",
    "sr": "Suriname",
    "ss": "South Sudan",
    "st": "Sao Tome and Principe",
    "su": "Soviet Union",
    "sv": "El Salvador",
    "sy": "Syria",
    "sz": "Eswatini",
    "td": "Chad",
    "tg": "Togo",
    "th": "Thailand",
    "tj": "Tajikistan",
    "tk": "Tokelau",
    "tl": "Timor-Leste",
    "tm": "Turkmenistan",
    "tn": "Tunisia",
    "to": "Tonga",
    "tr": "Turkey",
    "tt": "Trinidad and Tobago",
    "tv": "Tuvalu",
    "tw": "Taiwan",
    "tz": "Tanzania",
    "ua": "Ukraine",
    "ug": "Uganda",
    "us": "United States",
    "uy": "Uruguay",
    "uz": "Uzbekistan",
    "va": "Vatican",
    "ve": "Venezuela",
    "vn": "Vietnam",
    "vu": "Vanuatu",
    "wa": "Wales",
    "ws": "Samoa",
    "xi": "Northern Ireland",
    "xk": "Kosovo",
    "xw": "Rest of the World",
    "xx": "Unknown",
    "ye": "Yemen",
    "yt": "Mayotte",
    "yu": "Yugoslavia",
    "za": "South Africa",
    "zm": "Zambia",
    "zw": "Zimbabwe",
}

@dataclass
class SongData:
    audio_path: Path
    output_directory: Path | None
    image_type: str
    artist: str
    title: str
    language: str

    def __post_init__(self):
        if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", self.language):
            raise ValueError(f"invalid language tag: {self.language!r}")

        if not self.audio_path.exists():
            raise FileNotFoundError(self.audio_path)
        if not self.image_path().exists():
            raise FileNotFoundError(self.image_path())

        # must look like wsYYYYcc.*
        pattern = re.compile(r"^ws(?P<year>\d{4})(?P<cc>[a-z]{2})\.[^.]+$")
        name = self.audio_path.name.lower()
        m = pattern.match(name)
        if not m:
            raise ValueError(f"invalid filename {self.audio_path.name!r}, expected wsYYYYcc")
        self._year = m.group("year")
        self._cc = m.group("cc")

    def output_path(self) -> Path:
        if self.output_directory is not None:
            return self.output_directory / f"{self.audio_path.stem}.m4a"
        else:
            return self.audio_path.with_suffix('.m4a')

    def image_path(self) -> Path:
        return self.audio_path.with_suffix(self.image_type)

    def base_name(self) -> str:
        return self.audio_path.stem

    def json_path(self) -> Path:
        return self.output_path().with_suffix('.json')

    def year_cc(self) -> tuple[str, str]:
        return self._year, self._cc

    def formatted_artist(self) -> str:
        parts = self.artist.split(";")
        if len(parts) == 1:
            return self.artist
        elif len(parts) == 2:
            return " & ".join(parts)
        else:
            return ", ".join(parts[:-1]) + " & " + parts[-1]

quiet = ContextVar("quiet", default=False)
dry_run = ContextVar("dry_run", default=False)
overwrite = ContextVar("overwrite", default=False)

def cmd_str(cmd: list[str]) -> str:
    return shlex.join(cmd) if os.name != 'nt' else sp.list2cmdline(cmd)

def qprint(*args: object) -> None:
    if not quiet.get():
        print(*args, file=sys.stderr)

Std = Union[int, None, IO[bytes]]

def run(cmd: list[str], capture: bool = False) -> sp.CompletedProcess:
    qprint("$", cmd_str(cmd))
    if dry_run.get():
        return sp.CompletedProcess(cmd, 0, b"", b"")

    stdout: Std
    stderr: Std

    if quiet.get():
        stdout = sp.PIPE if capture else sp.DEVNULL
        stderr = sp.PIPE if capture else sp.DEVNULL
    else:
        stdout = sp.PIPE if capture else None
        stderr = sp.PIPE if capture else None

    try:
        return sp.run(cmd, check=True, stdout=stdout, stderr=stderr)
    except sp.CalledProcessError as e:
        out = (e.stdout or b"").decode("utf-8", "replace")
        err = (e.stderr or b"").decode("utf-8", "replace")
        raise RuntimeError(f"command failed: {cmd}\nstdout:\n{out}\nstderr:\n{err}")

def setup_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare files for the CDN.")

    parser.add_argument("audio_file", type=Path, help="The base name of the file in the format wsYEARcc.TYPE")
    parser.add_argument("image_type", type=str, help="The format of the image, e.g., jpg, png, webp")
    parser.add_argument("artist", type=str, help="The name of the song's artist")
    parser.add_argument("title", type=str, help="The title of the song")
    parser.add_argument("language", type=str, help="The language code of the song")

    parser.add_argument("--dry-run", '-n', action='store_true', help="Only output the commands that will be run")
    parser.add_argument("--quiet", '-q', action='store_true', help="Do not print commands that are executed")
    parser.add_argument("--overwrite", '-y', action='store_true', help="Overwrite files without asking")
    parser.add_argument("--output-directory", '-o', type=Path, action='store', help='Output destination')

    return parser

def confirm_overwrite(path: Path) -> bool:
    if overwrite.get():
        return True
    if not path.exists():
        return True
    inp = input(f"File {path} already exists. Overwrite? [y/N]") or 'n'
    return inp.lower().startswith('y')

def convert_to_m4a(song: SongData) -> Path:
    image_path = song.image_path()
    audio_path = song.audio_path
    out_path = song.output_path()
    year, cc = song.year_cc()
    country = cc_map.get(cc)
    if not country:
        raise ValueError(f"unknown country code '{cc}' for file {audio_path}")

    if not confirm_overwrite(out_path):
        return out_path

    cmd = ['ffmpeg', '-y', '-hide_banner',
        '-i', str(image_path),
        '-i', str(audio_path),
        '-map', '0:v:0', '-map', '1:a:0',
        '-c:v', 'copy', '-c:a', 'copy',
        '-map_metadata', '-1',
        '-metadata:s:v', 'title=Album cover',
        '-metadata:s:v', 'comment=Cover (front)',
        '-disposition:v', 'attached_pic',
        '-metadata', f'title={song.title}',
        '-metadata', f'artist={song.artist}',
        '-metadata', f'album={country} {year}',
        '-metadata', f'keywords={country};{year}',
        '-metadata', f'date={year}',
        '-metadata:s:a:0', f'language={song.language}',
        '-metadata', 'album_artist=World Stage',
        '-movflags', '+use_metadata_tags',
        '-brand', 'M4A ',
        '-f', 'mp4',
        str(out_path)]

    run(cmd)
    return out_path

def get_song_duration(path: Path) -> int:
    if dry_run.get():
        return 0

    cmd = ['ffprobe', '-v', 'error',
           '-show_entries', 'format=duration',
           '-of', 'default=noprint_wrappers=1:nokey=1',
           str(path)]

    proc = run(cmd, capture=True)

    if proc is None:
        raise RuntimeError("This should never happen, but I need to check for it anyway (duration).")

    s = proc.stdout.decode("utf-8", "replace").strip()
    try:
        runtime = float(s)
        return math.ceil(runtime)
    except ValueError as e:
        raise RuntimeError(f"ffprobe returned non-float duration: {s!r}") from e

def make_json(song: SongData, duration: int) -> Path:
    json_path = song.json_path()

    if not quiet.get():
        print(f"Creating the json file at {json_path}")

    if dry_run.get():
        return json_path

    if not confirm_overwrite(json_path):
        return json_path

    data = {
        "title": f"{song.formatted_artist()} – {song.title}",
        "duration": duration,
        "sources": [
            {
                "url": f"{base_url}/{song.base_name()}.m4a",
                "contentType": "audio/mp4",
                "quality": 1080
            }
        ],
        "thumbnail": f"{base_url}/{song.image_path().name}"
    }

    with json_path.open('w') as f:
        json.dump(data, f, ensure_ascii=True)

    return json_path

def upload(path: Path, endpoint_url: str):
    cmd = ['aws', 's3', 'cp',
        str(path),
        f's3://worldstage/{path.name}',
        '--endpoint-url', endpoint_url,
        '--profile', 'r2']
    run(cmd)

def main() -> None:
    args = setup_args().parse_args()

    endpoint_url = os.getenv('R2_ENDPOINT_URL')

    if endpoint_url is None:
        print('R2_ENDPOINT_URL not set', file=sys.stderr)
        sys.exit(2)

    song = SongData(audio_path=args.audio_file,
                    image_type=f'.{args.image_type}',
                    output_directory=args.output_directory,
                    artist=args.artist,
                    title=args.title,
                    language=args.language.lower())

    song.output_path().parent.mkdir(parents=True, exist_ok=True)

    quiet.set(args.quiet)
    dry_run.set(args.dry_run)
    overwrite.set(args.overwrite)

    m4a_path = convert_to_m4a(song)
    duration = get_song_duration(m4a_path)
    json_path = make_json(song, duration)

    upload(m4a_path, endpoint_url)
    upload(json_path, endpoint_url)
    upload(song.image_path(), endpoint_url)

if __name__ == '__main__':
    main()