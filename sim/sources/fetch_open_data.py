"""Fetch NYC DOT signal treatments inside the network bbox from NYC Open Data.

    python -m sim.sources.fetch_open_data

Writes (committed):
    sim/sources/lpi.json            leading pedestrian intervals (VZV, dataset xc4v-ntf4)
    sim/sources/exclusive_ped.json  exclusive pedestrian ("Barnes dance") and mid-block
                                    pedestrian signals (dataset 8kuj-2n3u)
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import httpx

from sim.network.bbox import BBOX

HERE = Path(__file__).parent
BASE = "https://data.cityofnewyork.us/resource"
LPI = "xc4v-ntf4"
EXCLUSIVE = "8kuj-2n3u"


def _inside(lat: float, lon: float) -> bool:
    s, w, n, e = BBOX
    return s <= lat <= n and w <= lon <= e


def _norm(street: str) -> str:
    s = re.sub(r"\b(West|East|W|E)\s+", "", street.strip(), flags=re.I)
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.I)
    s = re.sub(r"\bAvenue\b", "Ave", s, flags=re.I)
    s = re.sub(r"\bStreet\b", "St", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def fetch_lpi(client: httpx.Client) -> list[dict]:
    s, w, n, e = BBOX
    rows = client.get(f"{BASE}/{LPI}.json", params={
        "$where": f"within_box(the_geom,{n},{w},{s},{e})", "$limit": 5000}).json()
    out = [{"main_street": _norm(r["main_street"]), "cross_street": _norm(r["cross_stree"]),
            "lat": float(r["lat"]), "lon": float(r["long"]),
            "installed": (r.get("install_da") or "")[:10] or None} for r in rows]
    return sorted(out, key=lambda r: (r["main_street"], r["cross_street"]))


def fetch_exclusive(client: httpx.Client) -> list[dict]:
    rows = client.get(f"{BASE}/{EXCLUSIVE}.json", params={"$limit": 5000}).json()
    out = []
    for r in rows:
        lon, lat = r["the_geom"]["coordinates"]
        if not _inside(lat, lon):
            continue
        out.append({"main_street": _norm(r["main_stree"]), "cross_street": r["cross_stre"],
                    "mid_block": r.get("mid_block_") == "X", "lat": lat, "lon": lon})
    return sorted(out, key=lambda r: (r["main_street"], r["cross_street"]))


def main() -> int:
    with httpx.Client(timeout=60) as client:
        lpi, excl = fetch_lpi(client), fetch_exclusive(client)
    meta = {"fetched": date.today().isoformat(), "bbox": BBOX}
    (HERE / "lpi.json").write_text(json.dumps({"meta": {**meta, "dataset": LPI,
        "url": f"https://data.cityofnewyork.us/d/{LPI}"}, "rows": lpi}, indent=1) + "\n")
    (HERE / "exclusive_ped.json").write_text(json.dumps({"meta": {**meta, "dataset": EXCLUSIVE,
        "url": f"https://data.cityofnewyork.us/d/{EXCLUSIVE}"}, "rows": excl}, indent=1) + "\n")
    print(f"LPI: {len(lpi)}; exclusive/mid-block ped signals: {len(excl)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
