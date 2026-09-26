"""ctOS-style look (inspired by Watch Dogs 1; original design, no game assets).

Colors are shared by the CSS, the map layers and the snapshot overlays, so an alert is
the same red everywhere. Keep contrast high: this runs on a projector for judges.
"""

from __future__ import annotations

from common.schemas import EventType

BG = "#0a0c0f"
PANEL = "#12161b"
TEXT = "#e6edf3"
MUTED = "#8b98a5"
CYAN = "#00d8ff"
ORANGE = "#ff8a00"
RED = "#ff3344"

EVENT_COLORS: dict[EventType, str] = {
    EventType.DOUBLE_PARKED: RED,
    EventType.STOPPED_IN_LANE: ORANGE,
    EventType.BLOCKED_BOX: "#ffd400",
    EventType.FROZEN_FEED: MUTED,
}


def rgb(hex_color: str, alpha: int = 255) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [alpha]


# Transparent -> cyan -> orange -> red, for the stopped-vehicle heat layer.
HEAT_RANGE = [rgb(CYAN, 0), rgb(CYAN, 90), rgb(CYAN, 160), rgb(ORANGE, 200), rgb(RED, 230),
              rgb("#ff6677", 255)]

CSS = f"""
<style>
.stApp {{ background: {BG}; }}
.stApp::before {{
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 1000;
  background: repeating-linear-gradient(0deg, rgba(255,255,255,0.025) 0 1px, transparent 1px 3px);
}}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.2rem; max-width: 100%; }}
h1, h2, h3, h4, .lw-label {{
  text-transform: uppercase; letter-spacing: 0.14em; font-weight: 600;
}}
.lw-bar {{
  display: flex; align-items: center; gap: 1.6rem; padding: 0.55rem 1rem;
  border: 1px solid {CYAN}55; background: {PANEL}; margin-bottom: 0.8rem;
}}
.lw-title {{
  font-size: 1.25rem; letter-spacing: 0.3em; color: {TEXT};
  text-shadow: 0 0 6px {CYAN}88;
}}
.lw-title:hover {{ animation: lw-glitch 0.35s steps(2) 2; }}
@keyframes lw-glitch {{
  0% {{ text-shadow: 2px 0 {RED}, -2px 0 {CYAN}; }}
  50% {{ text-shadow: -2px 0 {RED}, 2px 0 {CYAN}; }}
  100% {{ text-shadow: 0 0 6px {CYAN}88; }}
}}
.lw-stat {{ color: {MUTED}; font-size: 0.85rem; letter-spacing: 0.12em; }}
.lw-stat b {{ color: {TEXT}; font-size: 1.05rem; text-shadow: 0 0 6px {CYAN}66; }}
.lw-alerts b {{ color: {RED}; animation: lw-pulse 1.6s ease-in-out infinite; }}
@keyframes lw-pulse {{ 50% {{ text-shadow: 0 0 14px {RED}; opacity: 0.75; }} }}
.lw-dot {{ display: inline-block; width: 0.6rem; height: 0.6rem; border-radius: 50%;
  margin-right: 0.4rem; vertical-align: middle; }}
.lw-panel {{
  position: relative; background: {PANEL}; border: 1px solid {CYAN}33;
  padding: 0.7rem 0.9rem; margin-bottom: 0.6rem;
}}
.lw-panel::before, .lw-panel::after {{
  content: ""; position: absolute; width: 12px; height: 12px; border-color: {CYAN};
  border-style: solid;
}}
.lw-panel::before {{ top: -1px; left: -1px; border-width: 2px 0 0 2px; }}
.lw-panel::after {{ bottom: -1px; right: -1px; border-width: 0 2px 2px 0; }}
.lw-panel.lw-active {{ border-color: {RED}66; }}
.lw-panel.lw-selected {{ border-color: {CYAN}; box-shadow: 0 0 12px {CYAN}44; }}
.lw-label {{ color: {MUTED}; font-size: 0.72rem; }}
.lw-type {{ font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }}
.lw-big {{ font-size: 1.5rem; color: {TEXT}; text-shadow: 0 0 8px {CYAN}55; }}
.lw-reason {{ color: {TEXT}; border-left: 2px solid {CYAN}; padding-left: 0.6rem; }}
.lw-muted {{ color: {MUTED}; }}
.lw-good {{ color: {CYAN}; }}
.lw-bad {{ color: {RED}; }}
div[data-testid="stImage"] img {{ border: 1px solid {CYAN}44; }}
.stButton button {{
  border-radius: 0; border: 1px solid {CYAN}66; background: transparent;
  text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.75rem;
}}
.stButton button:hover {{ border-color: {CYAN}; color: {CYAN}; box-shadow: 0 0 8px {CYAN}55; }}
</style>
"""
