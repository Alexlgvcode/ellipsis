"""Extract calibration targets and crosswalk lengths from the Penn Station Area FEIS.

Source: Pennsylvania Station Area Civic and Land Use Improvement Project FEIS (ESD, 2022),
Appendix H "Transportation". Its 2019 existing-conditions traffic analysis used official
DOT signal timings (FEIS ch. 14, "Traffic Conditions").

    python -m sim.sources.extract_feis            # downloads the PDF (~60 MB) if missing

Writes (committed):
    sim/sources/ta_t7_2019.json   Table TA-T7: v/c, delay, LOS, 95th queue per lane group
    sim/sources/crosswalks.json   crosswalk lengths per intersection and leg
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

APPENDIX_H_URL = "https://esd.ny.gov/sites/default/files/PSACLUIP-FEIS-Appendix-H.pdf"
HERE = Path(__file__).parent
CACHE = Path("/tmp/lanewatch-sources")

PERIODS = ("am", "midday", "pm")
ORDINAL = r"\d+(?:st|nd|rd|th)"
INTERSECTION_RE = re.compile(
    rf"^((?:Fifth|Sixth|Seventh|Eighth|Ninth|Tenth) Ave|Broadway|Dyer Ave)"
    rf"/((?:W|E) {ORDINAL} St)$")
APPROACH_RE = re.compile(r"^(Eastbound|Westbound|Northbound|Southbound)\s+(.*)$")
GROUP_RE = re.compile(r"([A-Z]{1,3})\s+([\d.]+)\s+([\d.]+)\s+([A-F]|0\.0)\s+(\d+)")
TOTAL_RE = re.compile(r"^([\d.]+)\s+([A-F])\s+([\d.]+)\s+([A-F])\s+([\d.]+)\s+([A-F])$")

AVENUES = {"Fifth": "5 Ave", "Sixth": "6 Ave", "Seventh": "7 Ave", "Eighth": "8 Ave",
           "Ninth": "9 Ave", "Tenth": "10 Ave"}


def pdf_text(url: str = APPENDIX_H_URL) -> str:
    from pypdf import PdfReader

    CACHE.mkdir(parents=True, exist_ok=True)
    pdf, txt = CACHE / "appendix_h.pdf", CACHE / "appendix_h.txt"
    if not txt.exists():
        if not pdf.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            pdf.write_bytes(urllib.request.urlopen(req, timeout=300).read())
        pages = PdfReader(str(pdf)).pages
        txt.write_text("\n".join(f"=====PAGE {i + 1}=====\n{p.extract_text() or ''}"
                                 for i, p in enumerate(pages)))
    return txt.read_text()


def short_name(avenue: str, street: str) -> str:
    """'Eighth Ave', 'W 33rd St' -> '8 Ave @ 33 St' (matches camera naming)."""
    ave = AVENUES.get(avenue.split()[0], avenue)
    num = re.search(r"\d+", street).group()
    return f"{ave} @ {num} St"


def parse_ta_t7(text: str) -> list[dict]:
    """Rows of the 2019 existing-conditions signalized LOS table."""
    lines = text.splitlines()
    out, cur, approach, in_2019 = [], None, None, False
    for raw in lines:
        line = raw.strip()
        if line.startswith("2019 Existing Condition Level of Service Analysis"):
            in_2019 = True
            continue
        if re.match(r"^20\d\d (No Action|With Action)", line):
            in_2019 = False
        if not in_2019 or not line:
            continue
        m = INTERSECTION_RE.match(line)
        if m:
            cur = {"name": short_name(m.group(1), m.group(2)), "feis_name": line,
                   "lane_groups": [], "intersection": None}
            out.append(cur)
            approach = None
            continue
        if cur is None:
            continue
        m = TOTAL_RE.match(line)
        if m:
            cur["intersection"] = {p: {"delay_s": float(m.group(2 * i + 1)),
                                       "los": m.group(2 * i + 2)}
                                   for i, p in enumerate(PERIODS)}
            cur = None
            continue
        m = APPROACH_RE.match(line)
        rest = line
        if m:
            approach, rest = m.group(1).lower(), m.group(2)
        groups = GROUP_RE.findall(rest)
        if approach and len(groups) == 3:
            names = {g[0] for g in groups}
            if len(names) != 1:
                continue
            vals = {p: {"v_c": float(g[1]), "delay_s": float(g[2]),
                        "los": g[3] if g[3] != "0.0" else None, "queue95_ft": int(g[4])}
                    for p, g in zip(PERIODS, groups, strict=True)}
            if all(v["v_c"] == 0 for v in vals.values()):
                continue
            cur["lane_groups"].append({"approach": approach, "group": groups[0][0], **vals})
    return [r for r in out if r["lane_groups"]]


CROSSWALK_HEAD_RE = re.compile(
    r"^((?:Fifth|Sixth|Seventh|Eighth|Ninth|Tenth) Avenue(?:/Broadway)?|Broadway) and "
    r"West (\d+)(?:st|nd|rd|th) Street\s*(.*)$")
LEG_RE = re.compile(r"(North|South|East|West)\s+([\d.]+)\s+([\d.]+)\s+(\d+)")


def parse_crosswalks(text: str) -> dict[str, dict]:
    """Crosswalk length (ft) per leg, from the existing-conditions crosswalk tables.

    Lengths are the same in every peak-hour table, so the first value per leg wins.
    """
    start = text.find("Existing Condition Crosswalk Analysis")
    end = text.find("No Action Condition Crosswalk Analysis", start)
    block = text[start:end if end > 0 else None]
    out: dict[str, dict] = {}
    cur = None
    for raw in block.splitlines():
        line = raw.strip()
        m = CROSSWALK_HEAD_RE.match(line)
        if m:
            ave = m.group(1).split()[0]
            cur = f"{AVENUES.get(ave, ave)} @ {m.group(2)} St"
            if "Broadway" in m.group(1) and ave != "Broadway":
                cur = f"{AVENUES[ave]} / Broadway @ {m.group(2)} St"
            out.setdefault(cur, {})
            line = m.group(3)
        if cur is None:
            continue
        for leg, length, width, _vol in LEG_RE.findall(line):
            out[cur].setdefault(leg.lower(), {"length_ft": float(length),
                                              "width_ft": float(width)})
    return {k: v for k, v in out.items() if v}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args(argv)
    text = pdf_text()
    rows = parse_ta_t7(text)
    crosswalks = parse_crosswalks(text)
    meta = {"source": APPENDIX_H_URL, "document": "Penn Station Area FEIS (ESD 2022), "
            "Appendix H", "table": "TA-T7 2019 Existing Condition Level of Service Analysis"}
    (args.out / "ta_t7_2019.json").write_text(
        json.dumps({"meta": meta, "intersections": rows}, indent=1) + "\n")
    (args.out / "crosswalks.json").write_text(json.dumps(
        {"meta": {**meta, "table": "Existing Condition Crosswalk Analysis"},
         "intersections": crosswalks}, indent=1) + "\n")
    print(f"TA-T7: {len(rows)} intersections, "
          f"{sum(len(r['lane_groups']) for r in rows)} lane groups; "
          f"crosswalks: {len(crosswalks)} intersections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
