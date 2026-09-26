"""Lane Watch operator dashboard.

    make api          # in one terminal (mock mode serves data/mock/)
    make dashboard    # http://localhost:8501

Polls the API every 2 s inside a fragment, so only the data refreshes and the selected
alert survives each refresh.
"""

from __future__ import annotations

import time

import pydeck as pdk
import streamlit as st

from common.config import get_settings
from common.schemas import Camera, Event
from dashboard import data as d
from dashboard import theme

REFRESH_S = 2
LIVE_FRAME_EVERY_S = 5

st.set_page_config(page_title="Lane Watch", layout="wide", initial_sidebar_state="collapsed")
st.markdown(theme.CSS, unsafe_allow_html=True)


@st.cache_resource
def api() -> d.ApiClient:
    return d.ApiClient(get_settings().api_url)


@st.cache_data(ttl=30, show_spinner=False)
def rules() -> dict:
    return d.load_rules()


@st.cache_data(ttl=300, show_spinner=False, max_entries=64)
def targeted_snapshot(event_json: str) -> bytes | None:
    event = Event.model_validate_json(event_json)
    raw = api().snapshot(event.id)
    return d.draw_target(raw, event) if raw else None


def header(connected: bool, n_active: int, n_cams: int, mock: bool | None) -> None:
    dot = theme.CYAN if connected else theme.RED
    link = "API LINKED" if connected else "API OFFLINE"
    feed = "" if mock is None else (" // MOCK DATA" if mock else "")
    link_dot = f'<span class="lw-dot" style="background:{dot}"></span>'
    st.markdown(
        f"""<div class="lw-bar">
          <span class="lw-title">LANE WATCH // MIDTOWN</span>
          <span class="lw-stat lw-alerts">ACTIVE ALERTS <b>{n_active}</b></span>
          <span class="lw-stat">CAMERAS <b>{n_cams}</b></span>
          <span class="lw-stat">NYC <b>{d.local_time(d.utcnow())}</b></span>
          <span class="lw-stat">{link_dot}{link}{feed}</span>
        </div>""",
        unsafe_allow_html=True,
    )


def city_map(pins: list[dict], heat: list[dict], layers: list[str]) -> None:
    deck_layers = []
    if "Heat" in layers and heat:
        deck_layers.append(pdk.Layer(
            "HeatmapLayer", data=heat, get_position="[lon, lat]", get_weight="weight",
            radius_pixels=70, intensity=1.2, threshold=0.05, color_range=theme.HEAT_RANGE))
    if "Pins" in layers:
        alerts = [p for p in pins if p["alert"]]
        deck_layers.append(pdk.Layer(
            "ScatterplotLayer", data=alerts, get_position="[lon, lat]", get_radius=38,
            filled=False, stroked=True, get_line_color=theme.rgb(theme.RED),
            line_width_min_pixels=2))
        deck_layers.append(pdk.Layer(
            "ScatterplotLayer", data=pins, get_position="[lon, lat]", get_radius="radius",
            radius_min_pixels=4, get_fill_color="color", pickable=True))
    lat = sum(p["lat"] for p in pins) / len(pins) if pins else 40.7505
    lon = sum(p["lon"] for p in pins) / len(pins) if pins else -73.9910
    st.pydeck_chart(pdk.Deck(
        layers=deck_layers, map_provider="carto", map_style="dark",
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=15.3, pitch=40),
        tooltip={"text": "{name}\nactive alerts: {alerts}"}), height=430)


def feed(rows: list[d.FeedRow], selected: str | None) -> None:
    st.markdown('<div class="lw-label">Alert feed</div>', unsafe_allow_html=True)
    if not rows:
        st.markdown('<div class="lw-panel lw-muted">No alerts.</div>', unsafe_allow_html=True)
    for r in rows:
        cls = "lw-panel" + (" lw-active" if r.active else "") + (
            " lw-selected" if r.event_id == selected else "")
        card, button = st.columns([6, 1], vertical_alignment="center")
        card.markdown(
            f"""<div class="{cls}">
              <span class="lw-type" style="color:{r.color}">{r.label}</span>
              <span class="lw-muted"> // {r.camera_name}</span><br>
              <span class="lw-big">{r.clock}</span>
              <span class="lw-muted"> &nbsp;conf {r.confidence} &nbsp;since {r.started}
              {'' if r.active else ' &nbsp;ENDED'}</span>
            </div>""",
            unsafe_allow_html=True,
        )
        button.button("View", key=f"view-{r.event_id}", on_click=_select, args=(r.event_id,))


def _select(event_id: str) -> None:
    st.session_state.selected = event_id


def detail(event: Event, row: d.FeedRow, camera: Camera | None) -> None:
    st.markdown(
        f"""<div class="lw-panel lw-selected">
          <div class="lw-label">Target</div>
          <span class="lw-type" style="color:{row.color}">{row.label}</span>
          <span class="lw-muted"> // {row.camera_name}</span><br>
          <span class="lw-big">{row.duration}</span>
          <span class="lw-muted"> &nbsp;confidence {row.confidence}
            &nbsp;zone {event.lane_zone.value} &nbsp;since {row.started}</span>
          <p class="lw-reason">{row.reason}</p>
        </div>""",
        unsafe_allow_html=True,
    )
    snap, live = st.columns(2)
    with snap:
        st.markdown('<div class="lw-label">Snapshot at alert</div>', unsafe_allow_html=True)
        img = targeted_snapshot(event.model_dump_json())
        if img:
            st.image(img, width="stretch")
        else:
            st.markdown('<div class="lw-panel lw-muted">No snapshot.</div>',
                        unsafe_allow_html=True)
    with live:
        st.markdown('<div class="lw-label">Live camera</div>', unsafe_allow_html=True)
        if camera:
            bucket = int(time.time() // LIVE_FRAME_EVERY_S)
            st.image(f"{camera.image_url}?t={bucket}", width="stretch")
        else:
            st.markdown('<div class="lw-panel lw-muted">Camera not in the list.</div>',
                        unsafe_allow_html=True)
    recommendation(event.id)


def recommendation(event_id: str) -> None:
    card = d.recommendation_card(api().recommendation(event_id))
    st.markdown('<div class="lw-label">Signal recommendation (simulation only)</div>',
                unsafe_allow_html=True)
    if card.status == "none":
        st.markdown('<div class="lw-panel lw-muted">No recommendation yet.</div>',
                    unsafe_allow_html=True)
        return
    changes = "<br>".join(card.changes)
    if card.status == "pending":
        sim = '<span class="lw-muted">Simulation running...</span>'
    else:
        (dd, dn), (qd, qn) = card.delay, card.queue
        sim = (f'<span class="lw-label">Delay / vehicle</span> '
               f'<span class="lw-bad">{dd:g} s</span> &rarr; <span class="lw-good">{dn:g} s</span>'
               f' &nbsp; <span class="lw-label">Max queue</span> '
               f'<span class="lw-bad">{qd:g}</span> &rarr; <span class="lw-good">{qn:g}</span>'
               f' <span class="lw-muted">(default &rarr; recommended)</span>')
    st.markdown(f'<div class="lw-panel">{changes}<br><br>{sim}</div>', unsafe_allow_html=True)


@st.fragment(run_every=REFRESH_S)
def live_view() -> None:
    try:
        health = api().health()
        cameras, events = api().cameras(), api().events()
    except d.ApiUnavailable as e:
        header(False, 0, 0, None)
        st.warning(f"Can't reach the API ({e}). Retrying every {REFRESH_S} s.")
        return

    now, mock = d.utcnow(), bool(health.get("mock_mode"))
    rows = d.feed_rows(events, cameras, now, mock, rules())
    header(True, sum(r.active for r in rows), len(cameras), mock)

    by_id = {e.id: e for e in events}
    if st.session_state.get("selected") not in by_id:
        st.session_state.selected = rows[0].event_id if rows else None
    selected = st.session_state.selected

    left, right = st.columns([3, 2], gap="medium")
    with left:
        layers = st.segmented_control("Layers", ["Pins", "Heat"], selection_mode="multi",
                                      default=["Pins", "Heat"], key="layers",
                                      label_visibility="collapsed") or []
        city_map(d.map_pins(cameras, events, now, mock),
                 d.heat_points(events, cameras, rules(), now, mock), layers)
        feed(rows, selected)
    with right:
        if selected:
            row = next(r for r in rows if r.event_id == selected)
            camera = next((c for c in cameras if c.id == row.camera_id), None)
            detail(by_id[selected], row, camera)
        else:
            st.markdown('<div class="lw-panel lw-muted">Select an alert.</div>',
                        unsafe_allow_html=True)


live_view()
