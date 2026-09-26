"""SUMO .net.xml helpers (no sumolib required)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path


def load(path: Path) -> ET.ElementTree:
    return ET.parse(path)


def write(tree: ET.ElementTree, path: Path) -> None:
    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    tree.write(path, encoding="utf-8", xml_declaration=True)


def children(parent: ET.Element, tag: str) -> list[ET.Element]:
    return [el for el in list(parent) if el.tag == tag]


def iter_tag(root: ET.Element, tag: str) -> Iterator[ET.Element]:
    for el in root.iter():
        if el.tag == tag:
            yield el


def junctions(root: ET.Element) -> dict[str, ET.Element]:
    return {el.get("id", ""): el for el in iter_tag(root, "junction") if el.get("id")}


def edges(root: ET.Element) -> dict[str, ET.Element]:
    return {
        el.get("id", ""): el
        for el in iter_tag(root, "edge")
        if el.get("id") and not el.get("id", "").startswith(":")
    }


def connections(root: ET.Element) -> list[ET.Element]:
    return list(iter_tag(root, "connection"))


def tl_logics(root: ET.Element) -> list[ET.Element]:
    return list(iter_tag(root, "tlLogic"))


def phase_duration_sum(logic: ET.Element) -> float:
    return sum(float(p.get("duration") or 0) for p in children(logic, "phase"))


def heading_of_edge(edge: ET.Element, juncs: dict[str, ET.Element]) -> str | None:
    frm, to = juncs.get(edge.get("from", "")), juncs.get(edge.get("to", ""))
    if frm is None or to is None:
        return None
    dx = float(to.get("x", 0)) - float(frm.get("x", 0))
    dy = float(to.get("y", 0)) - float(frm.get("y", 0))
    if dx == 0 and dy == 0:
        return None
    from sim.network.names import heading

    return heading(dx, dy)
