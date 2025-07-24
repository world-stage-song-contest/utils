from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess as sp
import sys, ctypes

OUT_HANDLE = sys.stdout
ERR_HANDLE = sys.stderr

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() # type: ignore
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
        return sp.run(cmd, stdout=sp.PIPE if capture else None, stderr=sp.PIPE if capture else None, text=True, check=True)
    except sp.CalledProcessError as e:
        raise RuntimeError(f"\n[cmd] {' '.join(map(shlex.quote, cmd))}\n[stderr]\n{e.stderr or ''}") from None

class Clips:
    videos: dict[tuple[int, str], dict[str, Path]]
    opening: dict[tuple[int, str], dict[str, Path]]
    intervals: dict[tuple[int, str], dict[str, Path]]
    postcards: dict[tuple[int, str], dict[str, Path]]

    def __init__(self):
        self.videos = defaultdict(dict)
        self.opening = defaultdict(dict)
        self.intervals = defaultdict(dict)
        self.postcards = defaultdict(dict)

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
    yt_dlp: str
    inkscape: str
    straight: bool
    reverse: bool
    postcards: Path
    vidsdir: Path
    cardsdir: Path
    clipsdir: Path
    commondir: Path

@dataclass
class CS:
    name: str
    bg: str
    fg1: str
    fg2: str
    text: str

colours = {
    "default": {
        "black": "#000000",
        "white": "#FFFFFF",
        "red": "#FF0000",
        "orange": "#FF6F00",
        "yellow": "#FFDD00",
        "green": "#00DD00",
        "cyan": "#00DDFF",
        "blue": "#5555FF"
    },
    "70s": {
        "black": "#2D2D2D",
        "white": "#E6E6E6",
        "red": "#A64534",
        "orange": "#B7672B",
        "yellow": "#C59F30",
        "green": "#6AA556",
        "cyan": "#6A87A5",
        "blue": "#324561"
    }
}

schemes = {
    'ALB': CS(name='Albania', bg='red', fg1='black', fg2='black', text='black'),
    'DZA': CS(name='Algeria', bg='green', fg1='red', fg2='white', text='white'),
    'AND': CS(name='Andorra', bg='yellow', fg1='blue', fg2='red', text='red'),
    'ATG': CS(name='Antigua and Barbuda', bg='black', fg1='red', fg2='blue', text='yellow'),
    'ARG': CS(name='Argentina', bg='cyan', fg1='white', fg2='white', text='white'),
    'ARM': CS(name='Armenia', bg='red', fg1='white', fg2='yellow', text='yellow'),
    'AUS': CS(name='Australia', bg='blue', fg1='red', fg2='white', text='white'),
    'AUT': CS(name='Austria', bg='white', fg1='red', fg2='red', text='red'),
    'AZE': CS(name='Azerbaijan', bg='cyan', fg1='green', fg2='red', text='red'),
    'BLR': CS(name='Belarus', bg='green', fg1='red', fg2='red', text='red'),
    'BEL': CS(name='Belgium', bg='red', fg1='yellow', fg2='black', text='black'),
    'BIH': CS(name='Bosnia and Herzegovina', bg='blue', fg1='yellow', fg2='yellow', text='yellow'),
    'BRA': CS(name='Brazil', bg='green', fg1='yellow', fg2='blue', text='blue'),
    'BGR': CS(name='Bulgaria', bg='green', fg1='red', fg2='white', text='white'),
    'CPV': CS(name='Cabo Verde', bg='blue', fg1='white', fg2='red', text='white'),
    'KHM': CS(name='Cambodia', bg='blue', fg1='red', fg2='red', text='red'),
    'CMR': CS(name='Cameroon', bg='green', fg1='red', fg2='yellow', text='yellow'),
    'CAN': CS(name='Canada', bg='red', fg1='white', fg2='white', text='white'),
    'CHL': CS(name='Chile', bg='blue', fg1='red', fg2='white', text='white'),
    'CHN': CS(name='China', bg='red', fg1='yellow', fg2='yellow', text='yellow'),
    'COL': CS(name='Colombia', bg='red', fg1='yellow', fg2='yellow', text='yellow'),
    'HRV': CS(name='Croatia', bg='blue', fg1='red', fg2='white', text='white'),
    'CUB': CS(name='Cuba', bg='blue', fg1='red', fg2='white', text='white'),
    'CYP': CS(name='Cyprus', bg='white', fg1='orange', fg2='orange', text='orange'),
    'CZE': CS(name='Czechia', bg='blue', fg1='red', fg2='white', text='white'),
    'CSK': CS(name='Czechoslovakia', bg='blue', fg1='red', fg2='white', text='white'),
    'DNK': CS(name='Denmark', bg='red', fg1='white', fg2='white', text='white'),
    'DOM': CS(name='Dominican Republic', bg='blue', fg1='red', fg2='white', text='white'),
    'COD': CS(name='Zaire', bg='blue', fg1='red', fg2='yellow', text='yellow'),
    'DDR': CS(name='East Germany', bg='black', fg1='red', fg2='yellow', text='yellow'),
    'EGY': CS(name='Egypt', bg='yellow', fg1='red', fg2='white', text='white'),
    'ENG': CS(name='England', bg='red', fg1='white', fg2='white', text='white'),
    'EST': CS(name='Estonia', bg='cyan', fg1='black', fg2='black', text='white'),
    'ETH': CS(name='Ethiopia', bg='blue', fg1='green', fg2='red', text='yellow'),
    'FIN': CS(name='Finland', bg='white', fg1='blue', fg2='blue', text='blue'),
    'FRA': CS(name='France', bg='blue', fg1='red', fg2='white', text='white'),
    'GEO': CS(name='Georgia', bg='white', fg1='red', fg2='red', text='red'),
    'DEU': CS(name='West Germany', bg='black', fg1='red', fg2='yellow', text='yellow'),
    'GHA': CS(name='Ghana', bg='yellow', fg1='green', fg2='red', text='red'),
    'GRC': CS(name='Greece', bg='blue', fg1='white', fg2='white', text='white'),
    'GIN': CS(name='Guinea', bg='yellow', fg1='red', fg2='green', text='green'),
    'HTI': CS(name='Haiti', bg='red', fg1='blue', fg2='blue', text='white'),
    'HKG': CS(name='Hong Kong', bg='red', fg1='white', fg2='white', text='white'),
    'HUN': CS(name='Hungary', bg='red', fg1='green', fg2='green', text='white'),
    'ISL': CS(name='Iceland', bg='blue', fg1='red', fg2='white', text='white'),
    'IND': CS(name='India', bg='orange', fg1='green', fg2='blue', text='white'),
    'IDN': CS(name='Indonesia', bg='white', fg1='red', fg2='red', text='red'),
    'IRN': CS(name='Iran', bg='green', fg1='red', fg2='white', text='white'),
    'IRL': CS(name='Ireland', bg='green', fg1='orange', fg2='white', text='white'),
    'IRQ': CS(name='Iraq', bg='black', fg1='red', fg2='white', text='white'),
    'ISR': CS(name='Israel', bg='white', fg1='blue', fg2='blue', text='blue'),
    'ITA': CS(name='Italy', bg='green', fg1='red', fg2='white', text='white'),
    'JAM': CS(name='Jamaica', bg='green', fg1='yellow', fg2='yellow', text='black'),
    'JPN': CS(name='Japan', bg='white', fg1='red', fg2='red', text='red'),
    'KAZ': CS(name='Kazakhstan', bg='cyan', fg1='yellow', fg2='yellow', text='yellow'),
    'KEN': CS(name='Kenya', bg='red', fg1='black', fg2='green', text='white'),
    'XKK': CS(name='Kosovo', bg='blue', fg1='yellow', fg2='white', text='white'),
    'KGZ': CS(name='Kyrgyzstan', bg='red', fg1='yellow', fg2='yellow', text='yellow'),
    'LVA': CS(name='Latvia', bg='red', fg1='white', fg2='white', text='white'),
    'LBN': CS(name='Lebanon', bg='green', fg1='red', fg2='white', text='white'),
    'LIE': CS(name='Liechtenstein', bg='red', fg1='blue', fg2='blue', text='blue'),
    'LTU': CS(name='Lithuania', bg='green', fg1='red', fg2='yellow', text='yellow'),
    'LUX': CS(name='Luxembourg', bg='cyan', fg1='red', fg2='white', text='white'),
    'MDG': CS(name='Madagascar', bg='green', fg1='red', fg2='white', text='white'),
    'MYS': CS(name='Malaysia', bg='blue', fg1='red', fg2='yellow', text='white'),
    'MLT': CS(name='Malta', bg='red', fg1='white', fg2='white', text='white'),
    'MEX': CS(name='Mexico', bg='green', fg1='white', fg2='red', text='white'),
    'MDA': CS(name='Moldova', bg='blue', fg1='red', fg2='yellow', text='yellow'),
    'MCO': CS(name='Monaco', bg='red', fg1='white', fg2='white', text='white'),
    'MNG': CS(name='Mongolia', bg='blue', fg1='red', fg2='red', text='yellow'),
    'MNE': CS(name='Montenegro', bg='red', fg1='yellow', fg2='yellow', text='yellow'),
    'MAR': CS(name='Morocco', bg='red', fg1='green', fg2='green', text='green'),
    'NLD': CS(name='Netherlands', bg='blue', fg1='red', fg2='white', text='white'),
    'NZL': CS(name='New Zealand', bg='blue', fg1='red', fg2='white', text='white'),
    'NGA': CS(name='Nigeria', bg='green', fg1='white', fg2='white', text='white'),
    'MKD': CS(name='North Macedonia', bg='red', fg1='yellow', fg2='yellow', text='yellow'),
    'NOR': CS(name='Norway', bg='red', fg1='blue', fg2='white', text='white'),
    'PAK': CS(name='Pakistan', bg='green', fg1='white', fg2='white', text='white'),
    'PHL': CS(name='Philippines', bg='blue', fg1='yellow', fg2='red', text='white'),
    'PER': CS(name='Peru', bg='red', fg1='white', fg2='white', text='white'),
    'POL': CS(name='Poland', bg='red', fg1='white', fg2='white', text='white'),
    'PRT': CS(name='Portugal', bg='green', fg1='red', fg2='yellow', text='white'),
    'PRI': CS(name='Puerto Rico', bg='blue', fg1='red', fg2='white', text='white'),
    'ROU': CS(name='Romania', bg='blue', fg1='red', fg2='yellow', text='yellow'),
    'RUS': CS(name='Russia', bg='blue', fg1='red', fg2='white', text='white'),
    'SMR': CS(name='San Marino', bg='cyan', fg1='white', fg2='white', text='white'),
    'SCT': CS(name='Scotland', bg='blue', fg1='white', fg2='white', text='white'),
    'SCG': CS(name='Serbia and Montenegro', bg='blue', fg1='red', fg2='white', text='white'),
    'SRB': CS(name='Serbia', bg='blue', fg1='red', fg2='white', text='white'),
    'SGP': CS(name='Singapore', bg='red', fg1='white', fg2='white', text='white'),
    'SVK': CS(name='Slovakia', bg='blue', fg1='red', fg2='white', text='white'),
    'SVN': CS(name='Slovenia', bg='blue', fg1='red', fg2='white', text='white'),
    'ZAF': CS(name='South Africa', bg='green', fg1='red', fg2='blue', text='yellow'),
    'KOR': CS(name='South Korea', bg='white', fg1='blue', fg2='red', text='black'),
    'SUN': CS(name='Soviet Union', bg='red', fg1='yellow', fg2='yellow', text='yellow'),
    'ESP': CS(name='Spain', bg='red', fg1='yellow', fg2='yellow', text='yellow'),
    'SUR': CS(name='Suriname', bg='green', fg1='yellow', fg2='red', text='white'),
    'SWE': CS(name='Sweden', bg='blue', fg1='yellow', fg2='yellow', text='yellow'),
    'CHE': CS(name='Switzerland', bg='red', fg1='white', fg2='white', text='white'),
    'TWN': CS(name='Taiwan', bg='blue', fg1='red', fg2='white', text='white'),
    'TJK': CS(name='Tajikistan', bg='green', fg1='red', fg2='yellow', text='white'),
    'THA': CS(name='Thailand', bg='blue', fg1='red', fg2='white', text='white'),
    'TUN': CS(name='Tunisia', bg='red', fg1='white', fg2='white', text='white'),
    'TUR': CS(name='Turkey', bg='red', fg1='white', fg2='white', text='white'),
    'UKR': CS(name='Ukraine', bg='blue', fg1='yellow', fg2='yellow', text='yellow'),
    'GBR': CS(name='United Kingdom', bg='blue', fg1='red', fg2='white', text='white'),
    'USA': CS(name='United States', bg='blue', fg1='red', fg2='white', text='white'),
    'URY': CS(name='Uruguay', bg='white', fg1='blue', fg2='blue', text='blue'),
    'UZB': CS(name='Uzbekistan', bg='cyan', fg1='white', fg2='green', text='red'),
    'VEN': CS(name='Venezuela', bg='blue', fg1='red', fg2='yellow', text='white'),
    'VNM': CS(name='Vietnam', bg='red', fg1='yellow', fg2='yellow', text='yellow'),
    'WIN': CS(name='Winner', bg='blue', fg1='green', fg2='white', text='white'),
    'WLS': CS(name='Wales', bg='white', fg1='green', fg2='green', text='red'),
    'YUG': CS(name='Yugoslavia', bg='blue', fg1='yellow', fg2='red', text='white'),
    'ZWE': CS(name='Zimbabwe', bg='yellow', fg1='green', fg2='red', text='black')
}
