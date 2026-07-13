#!/usr/bin/env python3
# pyright: reportMissingImports=false

import shlex
import argparse
import json
import os
import re
import sys
import subprocess as sp
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Union

import boto3
from botocore.exceptions import BotoCoreError, ClientError

import app_cache
import app_config
import ffmpeg_tools

base_url = 'https://media.world-stage.org'
OUT_HANDLE = sys.stdout
ERR_HANDLE = sys.stderr


@dataclass(frozen=True)
class S3Config:
    endpoint_url: str
    bucket: str
    profile: str


@dataclass(frozen=True)
class PrepareRequest:
    """The GUI- and CLI-independent description of one preparation job."""

    mode: str
    media_file: Path
    image_type: str | None
    artist: str
    title: str
    language: str
    output_directory: Path | None
    upload: bool
    subtitles: bool
    overwrite_existing: bool
    ffmpeg: str
    ffprobe: str
    clear_upload_cache: bool = False
    dry_run_mode: bool = False
    quiet_mode: bool = False


def save_s3_config(config: S3Config) -> Path:
    return app_config.update_s3_settings(config.__dict__)


def load_s3_config() -> S3Config:
    data = app_config.s3_settings()
    if data is None:
        raise RuntimeError(
            f"S3 configuration not found at {app_config.config_path()}. "
            "Run 'prepare.py configure-s3 --endpoint-url URL' first."
        )
    config = S3Config(data["endpoint_url"], data["bucket"], data["profile"])
    if not all((config.endpoint_url, config.bucket, config.profile)):
        raise RuntimeError(f"Invalid S3 configuration in {app_config.config_path()}: values must not be empty")
    return config


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
    "de": "Germany",
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
    image_type: str | None
    artist: str
    title: str
    language: str
    subtitles: bool

    def __post_init__(self):
        if not re.fullmatch(r"[a-z]{3}", self.language):
            raise ValueError(f"invalid ISO 639-3 language code: {self.language!r}")

        if not self.audio_path.exists():
            raise FileNotFoundError(self.audio_path)
        if (p := self.image_path()) is not None and not p.exists():
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
        ext = '.mov' if self.image_type is None else '.m4a'

        if self.output_directory is not None:
            return self.output_directory / f"{self.audio_path.stem}{ext}"
        else:
            return self.audio_path.with_suffix(ext)

    def image_path(self) -> Path | None:
        if self.image_type is not None:
            return self.audio_path.with_suffix(self.image_type)

        return None

    def subtitles_path(self) -> Path | None:
        if not self.subtitles:
            return None

        return self.audio_path.with_suffix('.vtt')

    def base_name(self) -> str:
        return self.audio_path.stem

    def json_path(self) -> Path:
        return self.output_path().with_suffix('.json')

    def image_name(self) -> str:
        ip = self.image_path()
        if not ip:
            return ''

        return ip.name

    def subtitles_name(self) -> str:
        sp = self.subtitles_path()
        if not sp:
            return ''

        return sp.name

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

    def media_tags(self) -> ffmpeg_tools.MediaTags:
        year, cc = self.year_cc()
        country = cc_map.get(cc)
        if not country:
            raise ValueError(f"unknown country code '{cc}' for file {self.audio_path}")
        return ffmpeg_tools.MediaTags(
            title=self.title,
            artist=self.artist,
            album=f"{country} {year}",
            keywords=f"{country};{year}",
            date=year,
            location=country,
            language=self.language,
        )

quiet = ContextVar("quiet", default=False)
dry_run = ContextVar("dry_run", default=False)
overwrite = ContextVar("overwrite", default=False)

def cmd_str(cmd: list[str]) -> str:
    return shlex.join(cmd) if os.name != 'nt' else sp.list2cmdline(cmd)

def qprint(*args: object) -> None:
    if not quiet.get():
        print(*args, file=ERR_HANDLE)

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

    parser.add_argument("--dry-run", "-n", action="store_true", help="Only output the commands that will be run")
    parser.add_argument("--quiet", "-q", action="store_true", help="Do not print commands that are executed")
    parser.add_argument("--overwrite", "-y", action="store_true", help="Overwrite files without asking")
    parser.add_argument("--output-directory", "-o", type=Path, help="Output destination")
    parser.add_argument("--upload", "-u", dest="upload", action="store_true", help="Upload the files (default)")
    parser.add_argument("--no-upload", "-U", dest="upload", action="store_false", help="Do not upload the files")
    parser.add_argument("--subtitles", "-s", action="store_true", help="Add a subtitle track. Must be in the same directory as the video file and have a .vtt extension")
    parser.add_argument("--clear-upload-cache", action="store_true", help="Forget cached upload records before processing")

    subparsers = parser.add_subparsers(dest="mode", required=True)

    audio = subparsers.add_parser("audio", help="Process an audio file with an associated image")
    audio.add_argument("media_file", type=Path, help="Audio file in the format wsYEARcc.TYPE")
    audio.add_argument("image_type", type=str, help="Image format (jpg, png, webp, etc.)")
    audio.add_argument("artist", type=str, help="The name of the song's artist")
    audio.add_argument("title", type=str, help="The title of the song")
    audio.add_argument("language", type=str, help="ISO 639-3 language code of the song")

    video = subparsers.add_parser("video", help="Process a video file and only generate JSON")
    video.add_argument("media_file", type=Path, help="Video file in the format wsYEARcc.TYPE")
    video.add_argument("artist", type=str, help="The name of the song's artist")
    video.add_argument("title", type=str, help="The title of the song")
    video.add_argument("language", type=str, help="ISO 639-3 language code of the song")

    configure_s3 = subparsers.add_parser("configure-s3", help="Save S3 upload settings for future runs")
    configure_s3.add_argument("--endpoint-url", required=True, help="S3-compatible endpoint URL")
    configure_s3.add_argument("--bucket", default="worldstage", help="Bucket name (default: worldstage)")
    configure_s3.add_argument("--profile", default="r2", help="AWS CLI profile name (default: r2)")

    parser.set_defaults(upload=True)

    return parser

def confirm_overwrite(path: Path) -> bool:
    if overwrite.get():
        return True
    if not path.exists():
        return True
    inp = input(f"File {path} already exists. Overwrite? [y/N]") or 'n'
    return inp.lower().startswith('y')

def make_json(song: SongData, duration: int, mode: str) -> Path:
    json_path = song.json_path()

    if not quiet.get():
        print(f"Creating the json file at {json_path}", file=OUT_HANDLE)

    if dry_run.get():
        return json_path

    if not confirm_overwrite(json_path):
        return json_path

    if mode == 'video':
        ext = 'mov'
        ct = 'video/mp4'
    elif mode == 'audio':
        ext = 'm4a'
        ct = 'audio/mp4'
    else:
        raise ValueError(f"Unknown mode: {mode}")

    data = {
        "title": f"{song.formatted_artist()} – {song.title}",
        "duration": duration,
        "sources": [
            {
                "url": f"{base_url}/{song.base_name()}.{ext}",
                "contentType": ct,
                "quality": 1080
            }
        ]
    }

    if mode == 'audio':
        data['thumbnail'] = f"{base_url}/{song.image_name()}"

    if song.subtitles:
        data['textTracks'] = [{
            "default": True,
            "name": "Subtitles",
            "contentType": "text/vtt",
            "url": f"{base_url}/{song.subtitles_name()}"
        }]

    with json_path.open('w') as f:
        json.dump(data, f, ensure_ascii=True, indent=4)

    return json_path

def create_s3_client(config: S3Config):
    """Create an S3-compatible client using the configured AWS profile."""
    try:
        session = boto3.Session(profile_name=config.profile)
        return session.client("s3", endpoint_url=config.endpoint_url)
    except BotoCoreError as exc:
        raise RuntimeError(f"Could not initialize S3 profile {config.profile!r}: {exc}") from exc


def upload(path: Path | None, config: S3Config, client, object_name: str | None = None) -> None:
    if path is None:
        return
    object_name = object_name or path.name

    if not dry_run.get() and app_cache.is_cached_upload(path, config.endpoint_url, config.bucket, object_name):
        qprint(f"Skipping unchanged upload: {path}")
        return

    suffix = path.suffix.lower()
    extra_args: dict[str, str] = {}
    if suffix == '.mov':
        extra_args['ContentType'] = 'video/mp4'
    elif suffix == '.m4a':
        extra_args['ContentType'] = 'audio/mp4'

    qprint(f"Uploading {path} to s3://{config.bucket}/{object_name}")
    if dry_run.get():
        return
    if client is None:
        raise RuntimeError("S3 client was not initialized")
    try:
        if extra_args:
            client.upload_file(str(path), config.bucket, object_name, ExtraArgs=extra_args)
        else:
            client.upload_file(str(path), config.bucket, object_name)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise RuntimeError(f"Could not upload {path} to s3://{config.bucket}/{object_name}: {exc}") from exc
    app_cache.store_upload(path, config.endpoint_url, config.bucket, object_name)

def execute(request: PrepareRequest) -> None:
    """Prepare one audio or video item, optionally uploading its artifacts."""
    if request.mode not in {"audio", "video"}:
        raise ValueError(f"Unknown mode: {request.mode}")

    quiet.set(request.quiet_mode)
    dry_run.set(request.dry_run_mode)
    overwrite.set(request.overwrite_existing)

    if request.clear_upload_cache:
        if request.dry_run_mode:
            qprint(f"Would clear upload records in {app_cache.database_path()}")
        else:
            app_cache.initialize_database()
            app_cache.clear_upload_cache()
            print(f"Cleared upload cache records in {app_cache.database_path()}", file=ERR_HANDLE)

    s3_config = None
    s3_client = None
    if request.upload:
        s3_config = load_s3_config()
        if not request.dry_run_mode:
            app_cache.initialize_database()
            s3_client = create_s3_client(s3_config)

    img_type = f'.{request.image_type.lstrip(".")}' if request.mode == "audio" and request.image_type else None
    if request.mode == "audio" and img_type is None:
        raise ValueError("Audio preparation requires an image type, such as jpg or png")

    song = SongData(audio_path=request.media_file,
                    image_type=img_type,
                    output_directory=request.output_directory,
                    artist=request.artist,
                    title=request.title,
                    language=request.language.lower(),
                    subtitles=request.subtitles)

    song.output_path().parent.mkdir(parents=True, exist_ok=True)

    media = ffmpeg_tools.FFmpeg(request.ffmpeg, request.ffprobe, run)
    media_path = song.output_path()
    if confirm_overwrite(media_path):
        if request.mode == "audio":
            cover = song.image_path()
            assert cover is not None
            media.make_audio(cover, song.audio_path, media_path, song.media_tags())
        else:
            media.make_video(song.audio_path, song.subtitles_path(), media_path, song.media_tags())
    duration = 0 if dry_run.get() else media.duration(media_path)
    json_path = make_json(song, duration, request.mode)

    if request.upload:
        assert s3_config is not None
        upload(media_path, s3_config, s3_client)
        upload(json_path, s3_config, s3_client)
        upload(song.image_path(), s3_config, s3_client)
        upload(song.subtitles_path(), s3_config, s3_client)


def main() -> None:
    args = setup_args().parse_args()

    if args.mode == "configure-s3":
        path = save_s3_config(S3Config(args.endpoint_url, args.bucket, args.profile))
        print(f"Saved S3 configuration to {path}", file=OUT_HANDLE)
        return

    settings = app_config.recap_settings()
    request = PrepareRequest(
        mode=args.mode,
        media_file=args.media_file,
        image_type=args.image_type if args.mode == "audio" else None,
        artist=args.artist,
        title=args.title,
        language=args.language,
        output_directory=args.output_directory,
        upload=args.upload,
        subtitles=args.subtitles,
        overwrite_existing=args.overwrite,
        ffmpeg=str(settings["ffmpeg"]),
        ffprobe=str(settings["ffprobe"]),
        clear_upload_cache=args.clear_upload_cache,
        dry_run_mode=args.dry_run,
        quiet_mode=args.quiet,
    )
    try:
        execute(request)
    except (OSError, RuntimeError, ValueError) as exc:
        print(exc, file=ERR_HANDLE)
        sys.exit(2)

if __name__ == '__main__':
    main()
