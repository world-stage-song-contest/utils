from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess as sp
import sys, ctypes
from typing import Any

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

def run(cmd: list[str] | str, *, capture: bool = True) -> sp.CompletedProcess:
    print(shlex.join(cmd), file=OUT_HANDLE)
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    try:
        return sp.run(
            cmd,
            stdout=sp.PIPE if capture else None,
            stderr=sp.PIPE if capture else None,
            text=True,
            check=True,
        )
    except sp.CalledProcessError as e:
        raise RuntimeError(
            f"\n[cmd] {' '.join(map(shlex.quote, cmd))}\n[stderr]\n{e.stderr or ''}"
        ) from None

# show, ro
Clips = dict[tuple[str, str], dict[str, Path]]

@dataclass
class Args:
    csv: Path
    style: str
    tmpdir: Path
    browser: str | None
    po_token: str | None
    size: tuple[int, int]
    fps: int
    fade_duration: float
    output: Path
    multiprocessing: bool
    cleanup: bool
    ffmpeg: str
    ffprobe: str
    yt_dlp: str
    inkscape: str
    only_straight: bool
    only_reverse: bool
    vidsdir: Path
    cardsdir: Path
    clipsdir: Path

@dataclass
class CS:
    name: str
    bg: str
    fg1: str
    fg2: str
    text: str

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

schemes = {
    "AL": CS(name="Albania", bg="red", fg1="black", fg2="black", text="black"),
    "DZ": CS(name="Algeria", bg="green", fg1="red", fg2="white", text="white"),
    "AD": CS(name="Andorra", bg="yellow", fg1="blue", fg2="red", text="red"),
    "AO": CS(name="Angola", bg="black", fg1="red", fg2="red", text="yellow"),
    "AG": CS(name="Antigua and Barbuda", bg="black", fg1="red", fg2="blue", text="yellow"),
    "AR": CS(name="Argentina", bg="cyan", fg1="white", fg2="white", text="white"),
    "AM": CS(name="Armenia", bg="red", fg1="white", fg2="yellow", text="yellow"),
    "AU": CS(name="Australia", bg="blue", fg1="red", fg2="white", text="white"),
    "AT": CS(name="Austria", bg="white", fg1="red", fg2="red", text="red"),
    "AZ": CS(name="Azerbaijan", bg="cyan", fg1="green", fg2="red", text="red"),
    "BY": CS(name="Belarus", bg="white", fg1="red", fg2="red", text="red"),
    "BE": CS(name="Belgium", bg="red", fg1="yellow", fg2="black", text="black"),
    "BA": CS(name="Bosnia and Herzegovina", bg="blue", fg1="yellow", fg2="yellow", text="yellow"),
    "BO": CS(name="Bolivia", bg="yellow", fg1="green", fg2="red", text="red"),
    "BR": CS(name="Brazil", bg="green", fg1="yellow", fg2="blue", text="yellow"),
    "BN": CS(name="Brunei", bg="yellow", fg1="white", fg2="red", text="black"),
    "BD": CS(name="Bangladesh", bg="green", fg1="red", fg2="red", text="red"),
    "BG": CS(name="Bulgaria", bg="green", fg1="red", fg2="white", text="white"),
    "CV": CS(name="Cabo Verde", bg="blue", fg1="white", fg2="red", text="white"),
    "KH": CS(name="Cambodia", bg="blue", fg1="red", fg2="red", text="red"),
    "CM": CS(name="Cameroon", bg="green", fg1="red", fg2="yellow", text="yellow"),
    "CA": CS(name="Canada", bg="red", fg1="white", fg2="white", text="white"),
    "CL": CS(name="Chile", bg="blue", fg1="red", fg2="white", text="white"),
    "CN": CS(name="China", bg="red", fg1="yellow", fg2="yellow", text="yellow"),
    "CO": CS(name="Colombia", bg="red", fg1="yellow", fg2="yellow", text="yellow"),
    "CR": CS(name="Costa Rica", bg="red", fg1="blue", fg2="white", text="white"),
    "HR": CS(name="Croatia", bg="blue", fg1="red", fg2="white", text="white"),
    "CU": CS(name="Cuba", bg="blue", fg1="red", fg2="white", text="white"),
    "CY": CS(name="Cyprus", bg="white", fg1="orange", fg2="orange", text="orange"),
    "CZ": CS(name="Czechia", bg="blue", fg1="red", fg2="white", text="white"),
    "CS": CS(name="Czechoslovakia", bg="blue", fg1="red", fg2="white", text="white"),
    "DK": CS(name="Denmark", bg="red", fg1="white", fg2="white", text="white"),
    "DO": CS(name="Dominican Republic", bg="blue", fg1="red", fg2="white", text="white"),
    "CD": CS(name="Zaire", bg="blue", fg1="red", fg2="yellow", text="yellow"),
    "DD": CS(name="East Germany", bg="black", fg1="red", fg2="yellow", text="grey"),
    "EC": CS(name="Ecuador", bg="blue", fg1="red", fg2="yellow", text="black"),
    "EG": CS(name="Egypt", bg="red", fg1="white", fg2="black", text="black"),
    "EN": CS(name="England", bg="red", fg1="white", fg2="white", text="white"),
    "EE": CS(name="Estonia", bg="cyan", fg1="black", fg2="white", text="black"),
    "ET": CS(name="Ethiopia", bg="blue", fg1="green", fg2="red", text="yellow"),
    "FO": CS(name="Faroe Islands", bg="white", fg1="blue", fg2="blue", text="red"),
    "FI": CS(name="Finland", bg="white", fg1="blue", fg2="blue", text="blue"),
    "FR": CS(name="France", bg="blue", fg1="red", fg2="white", text="white"),
    "GE": CS(name="Georgia", bg="white", fg1="red", fg2="red", text="red"),
    "DE": CS(name="West Germany", bg="black", fg1="red", fg2="yellow", text="yellow"),
    "GY": CS(name="Guyana", bg="green", fg1="yellow", fg2="red", text="white"),
    "GH": CS(name="Ghana", bg="yellow", fg1="green", fg2="red", text="red"),
    "GR": CS(name="Greece", bg="blue", fg1="white", fg2="white", text="white"),
    "GL": CS(name="Greenland", bg="white", fg1="red", fg2="white", text="red"),
    "GN": CS(name="Guinea", bg="yellow", fg1="red", fg2="green", text="green"),
    "HT": CS(name="Haiti", bg="red", fg1="blue", fg2="blue", text="white"),
    "HK": CS(name="Hong Kong", bg="red", fg1="white", fg2="white", text="white"),
    "HU": CS(name="Hungary", bg="red", fg1="green", fg2="green", text="white"),
    "IS": CS(name="Iceland", bg="blue", fg1="red", fg2="white", text="white"),
    "IN": CS(name="India", bg="orange", fg1="green", fg2="blue", text="white"),
    "ID": CS(name="Indonesia", bg="white", fg1="red", fg2="red", text="red"),
    "IR": CS(name="Iran", bg="green", fg1="red", fg2="white", text="white"),
    "IE": CS(name="Ireland", bg="green", fg1="orange", fg2="white", text="white"),
    "IQ": CS(name="Iraq", bg="black", fg1="red", fg2="white", text="white"),
    "IL": CS(name="Israel", bg="white", fg1="blue", fg2="blue", text="blue"),
    "CI": CS(name="Ivory Coast", bg="orange", fg1="green", fg2="white", text="white"),
    "IT": CS(name="Italy", bg="green", fg1="red", fg2="white", text="white"),
    "JM": CS(name="Jamaica", bg="green", fg1="yellow", fg2="yellow", text="black"),
    "JP": CS(name="Japan", bg="white", fg1="red", fg2="red", text="red"),
    "KZ": CS(name="Kazakhstan", bg="turquoise", fg1="yellow", fg2="yellow", text="yellow"),
    "KE": CS(name="Kenya", bg="red", fg1="black", fg2="darkgreen", text="white"),
    "XK": CS(name="Kosovo", bg="blue", fg1="yellow", fg2="white", text="white"),
    "KG": CS(name="Kyrgyzstan", bg="red", fg1="yellow", fg2="yellow", text="yellow"),
    "LA": CS(name="Laos", bg="red", fg1="navy", fg2="navy", text="white"),
    "LV": CS(name="Latvia", bg="maroon", fg1="white", fg2="white", text="white"),
    "LB": CS(name="Lebanon", bg="white", fg1="green", fg2="red", text="red"),
    "LI": CS(name="Liechtenstein", bg="red", fg1="blue", fg2="blue", text="blue"),
    "LK": CS(name="Sri Lanka", bg="brown", fg1="yellow", fg2="green", text="yellow"),
    "LT": CS(name="Lithuania", bg="green", fg1="red", fg2="yellow", text="yellow"),
    "LU": CS(name="Luxembourg", bg="cyan", fg1="red", fg2="white", text="white"),
    "MG": CS(name="Madagascar", bg="green", fg1="red", fg2="white", text="white"),
    "MY": CS(name="Malaysia", bg="blue", fg1="red", fg2="yellow", text="white"),
    "MT": CS(name="Malta", bg="red", fg1="white", fg2="white", text="white"),
    "MX": CS(name="Mexico", bg="green", fg1="white", fg2="red", text="brown"),
    "MD": CS(name="Moldova", bg="blue", fg1="red", fg2="yellow", text="yellow"),
    "MC": CS(name="Monaco", bg="red", fg1="white", fg2="white", text="white"),
    "MM": CS(name="Burma", bg="green", fg1="yellow", fg2="red", text="white"),
    "MN": CS(name="Mongolia", bg="blue", fg1="red", fg2="red", text="yellow"),
    "ME": CS(name="Montenegro", bg="red", fg1="yellow", fg2="yellow", text="purple"),
    "MA": CS(name="Morocco", bg="red", fg1="green", fg2="green", text="green"),
    "NI": CS(name="Nicaragua", bg="cyan", fg1="white", fg2="white", text="white"),
    "NL": CS(name="Netherlands", bg="blue", fg1="red", fg2="white", text="white"),
    "NZ": CS(name="New Zealand", bg="blue", fg1="red", fg2="white", text="white"),
    "NG": CS(name="Nigeria", bg="green", fg1="white", fg2="white", text="white"),
    "MK": CS(name="North Macedonia", bg="red", fg1="yellow", fg2="yellow", text="yellow"),
    "NO": CS(name="Norway", bg="red", fg1="blue", fg2="white", text="white"),
    "PK": CS(name="Pakistan", bg="green", fg1="white", fg2="white", text="white"),
    "PH": CS(name="Philippines", bg="blue", fg1="yellow", fg2="red", text="white"),
    "PE": CS(name="Peru", bg="red", fg1="white", fg2="white", text="white"),
    "PL": CS(name="Poland", bg="red", fg1="white", fg2="white", text="white"),
    "PT": CS(name="Portugal", bg="green", fg1="red", fg2="yellow", text="white"),
    "PR": CS(name="Puerto Rico", bg="blue", fg1="red", fg2="white", text="white"),
    "PY": CS(name="Paraguay", bg="white", fg1="blue", fg2="blue", text="red"),
    "RO": CS(name="Romania", bg="blue", fg1="red", fg2="yellow", text="yellow"),
    "RU": CS(name="Russia", bg="blue", fg1="red", fg2="white", text="white"),
    "SM": CS(name="San Marino", bg="cyan", fg1="white", fg2="white", text="white"),
    "ST": CS(name="São Tomé and Príncipe", bg="green", fg1="red", fg2="yellow", text="black"),
    "AB": CS(name="Scotland", bg="blue", fg1="white", fg2="white", text="white"),
    "SV": CS(name="El Salvador", bg="blue", fg1="white", fg2="white", text="yellow"),
    "RS": CS(name="Serbia", bg="blue", fg1="red", fg2="white", text="white"),
    "SG": CS(name="Singapore", bg="red", fg1="white", fg2="white", text="white"),
    "SK": CS(name="Slovakia", bg="blue", fg1="red", fg2="white", text="white"),
    "SI": CS(name="Slovenia", bg="blue", fg1="red", fg2="white", text="white"),
    "ZA": CS(name="South Africa", bg="green", fg1="red", fg2="blue", text="yellow"),
    "KR": CS(name="South Korea", bg="white", fg1="blue", fg2="red", text="black"),
    "SU": CS(name="Soviet Union", bg="red", fg1="yellow", fg2="yellow", text="yellow"),
    "ES": CS(name="Spain", bg="red", fg1="gold", fg2="gold", text="gold"),
    "SR": CS(name="Suriname", bg="green", fg1="yellow", fg2="red", text="white"),
    "SE": CS(name="Sweden", bg="blue", fg1="yellow", fg2="yellow", text="yellow"),
    "CH": CS(name="Switzerland", bg="red", fg1="white", fg2="white", text="white"),
    "TW": CS(name="Taiwan", bg="blue", fg1="red", fg2="white", text="white"),
    "TJ": CS(name="Tajikistan", bg="green", fg1="red", fg2="yellow", text="white"),
    "TH": CS(name="Thailand", bg="blue", fg1="red", fg2="white", text="white"),
    "TN": CS(name="Tunisia", bg="red", fg1="white", fg2="white", text="white"),
    "TR": CS(name="Turkey", bg="red", fg1="white", fg2="white", text="white"),
    "UA": CS(name="Ukraine", bg="blue", fg1="yellow", fg2="yellow", text="yellow"),
    "GB": CS(name="United Kingdom", bg="navy", fg1="red", fg2="white", text="white"),
    "US": CS(name="United States", bg="navy", fg1="red", fg2="white", text="white"),
    "UY": CS(name="Uruguay", bg="white", fg1="blue", fg2="blue", text="blue"),
    "UZ": CS(name="Uzbekistan", bg="cyan", fg1="white", fg2="green", text="red"),
    "VE": CS(name="Venezuela", bg="blue", fg1="red", fg2="yellow", text="white"),
    "VN": CS(name="Vietnam", bg="red", fg1="yellow", fg2="yellow", text="yellow"),
    "XX": CS(name="Winner", bg="blue", fg1="green", fg2="white", text="white"),
    "WA": CS(name="Wales", bg="white", fg1="green", fg2="green", text="red"),
    "YU": CS(name="Yugoslavia", bg="blue", fg1="yellow", fg2="red", text="white"),
    "ZW": CS(name="Zimbabwe", bg="yellow", fg1="green", fg2="red", text="black"),
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
