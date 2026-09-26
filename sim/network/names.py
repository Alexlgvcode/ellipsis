"""Street-name parsing, expected one-way rules, and lat/lon helpers."""

from __future__ import annotations

import math
import re
from typing import Literal

Kind = Literal["avenue", "street", "other"]

# OSM / FEIS aliases -> "8 Ave" / "34 St" / "Broadway"
_ALIASES = {
    "avenue of the americas": "6 Ave",
    "ave of the americas": "6 Ave",
    "americas": "6 Ave",
    "sixth avenue": "6 Ave",
    "sixth ave": "6 Ave",
    "7th avenue south": "7 Ave",
    "fashion avenue": "7 Ave",
    "central park south": "59 St",
}

AVENUE_NB = frozenset({"6 Ave", "8 Ave"})
AVENUE_SB = frozenset({"5 Ave", "7 Ave", "9 Ave", "Broadway"})
STREET_TWOWAY = frozenset({"34 St"})

# Broadway plaza: closed to vehicles from 33rd to 36th (2009 + spring 2026 plaza).
BROADWAY_CLOSED_LAT = (40.7490, 40.7518)

CHOSEN_CAMERAS: list[tuple[str, float, float]] = [
    ("8 Ave @ 34 St", 40.752197, -73.993456),
    ("8 Ave @ 31 St", 40.750297, -73.994830),
    ("8 Ave @ 33 St", 40.751512, -73.993913),
    ("7 Ave @ 32 St", 40.749508, -73.991493),
    ("7 Ave @ 34 St", 40.751020, -73.990629),
    ("7 Ave @ 36 St", 40.752128, -73.989657),
    ("6 Ave @ 30 St", 40.747287, -73.989615),
    ("6 Ave @ 34 St", 40.749808, -73.987746),
    ("Broadway @ 6 Ave / 33 St", 40.749412, -73.988060),
    ("Broadway @ 38 St", 40.752453, -73.987123),
]


def utm_to_lonlat(easting: float, northing: float, zone: int = 18) -> tuple[float, float]:
    """WGS84 UTM (northern hemisphere) -> (lon, lat) in degrees."""
    a = 6378137.0
    e = 0.08181919084262149
    e2 = e * e
    k0 = 0.9996
    x = easting - 500_000.0
    y = northing
    ecc_prime2 = e2 / (1 - e2)
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
            + (151 * e1**3 / 96) * math.sin(6 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = ecc_prime2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ecc_prime2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ecc_prime2 - 3 * c1**2) * d**6 / 720
    )
    lon = (d - (1 + 2 * t1 + c1) * d**3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ecc_prime2 + 24 * t1**2) * d**5 / 120
           ) / math.cos(phi1)
    lon += math.radians(zone * 6 - 183)
    return math.degrees(lon), math.degrees(lat)


def local_xy_to_lonlat(net_offset: tuple[float, float], x: float, y: float,
                       zone: int = 18) -> tuple[float, float]:
    """SUMO local metres + netOffset -> (lon, lat)."""
    ox, oy = net_offset
    return utm_to_lonlat(x - ox, y - oy, zone=zone)


def net_offset_and_zone(root) -> tuple[tuple[float, float], int]:
    loc = None
    for el in root.iter():
        if el.tag == "location":
            loc = el
            break
    if loc is None:
        return (0.0, 0.0), 18
    ox, oy = (0.0, 0.0)
    raw = loc.get("netOffset") or "0,0"
    parts = raw.split(",")
    if len(parts) == 2:
        ox, oy = float(parts[0]), float(parts[1])
    zone = 18
    proj = loc.get("projParameter") or ""
    m = re.search(r"\+zone=(\d+)", proj)
    if m:
        zone = int(m.group(1))
    return (ox, oy), zone


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _squash(name: str) -> str:
    s = name.casefold()
    s = s.replace("’", "'")
    s = re.sub(r"[./,&]+", " ", s)
    s = re.sub(r"\b(west|east|north|south|w|e|n|s)\b", " ", s)
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", s)
    s = re.sub(r"\bavenue\b", "ave", s)
    s = re.sub(r"\bstreet\b", "st", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_street(name: str | None) -> str | None:
    """'8th Avenue' / 'West 34th Street' / 'Avenue of the Americas' -> '8 Ave' / '34 St'."""
    if not name:
        return None
    raw = name.strip()
    folded = raw.casefold()
    if folded in _ALIASES:
        return _ALIASES[folded]
    key = _squash(raw)
    if key in _ALIASES:
        return _ALIASES[key]
    if "broadway" in key:
        return "Broadway"
    if "dyer" in key:
        return "Dyer Ave"
    m = re.search(r"\b(\d+)\s+ave\b", key)
    if m:
        return f"{int(m.group(1))} Ave"
    m = re.search(r"\b(\d+)\s+st\b", key)
    if m:
        return f"{int(m.group(1))} St"
    m = re.search(r"\b(fifth|sixth|seventh|eighth|ninth|tenth)\s+ave\b", key)
    words = {
        "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    }
    if m:
        return f"{words[m.group(1)]} Ave"
    return None


def kind(street: str | None) -> Kind:
    if not street:
        return "other"
    if street.endswith(" St"):
        return "street"
    if street.endswith(" Ave") or street in {"Broadway"}:
        return "avenue"
    return "other"


def street_number(street: str | None) -> int | None:
    if not street:
        return None
    m = re.match(r"(\d+) ", street)
    return int(m.group(1)) if m else None


def expected_direction(street: str) -> str | None:
    """One-way rule from 15 Penn FEIS ch. 16. 34th St is two-way (None)."""
    if street in STREET_TWOWAY:
        return None
    if street in AVENUE_NB:
        return "northbound"
    if street in AVENUE_SB:
        return "southbound"
    n = street_number(street)
    if street.endswith(" St") and n is not None:
        return "eastbound" if n % 2 == 0 else "westbound"
    return None


def heading(dx: float, dy: float) -> str:
    if abs(dx) >= abs(dy):
        return "eastbound" if dx >= 0 else "westbound"
    return "northbound" if dy >= 0 else "southbound"


def intersection_name(streets: list[str]) -> str | None:
    aves = [s for s in streets if kind(s) == "avenue"]
    sts = [s for s in streets if kind(s) == "street"]
    if aves and sts:
        return f"{aves[0]} @ {sts[0]}"
    if len(aves) >= 2:
        return f"{aves[0]} / {aves[1]}"
    if streets:
        return " / ".join(streets[:2])
    return None


def is_intersection_name(name: str | None) -> bool:
    if not name:
        return False
    return kind(parse_intersection(name)[0]) == "avenue" and bool(parse_intersection(name)[1])


def same_intersection(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return parse_intersection(a) == parse_intersection(b) and parse_intersection(a)[0]


def parse_intersection(name: str) -> tuple[str | None, str | None]:
    """'8 Ave @ 34 St' -> ('8 Ave', '34 St')."""
    parts = re.split(r"\s*[@/]\s*", name)
    streets = [normalize_street(p) or p.strip() for p in parts if p.strip()]
    aves = [s for s in streets if kind(s) == "avenue"]
    sts = [s for s in streets if kind(s) == "street"]
    return (aves[0] if aves else None, sts[0] if sts else None)
