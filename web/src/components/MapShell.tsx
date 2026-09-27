import { Map as MLMap, Marker, type GeoJSONSource, type StyleSpecification } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { Camera } from "../api/types";
import { METERS_PER_VEHICLE } from "../lib/rules";
import { along, bearing, offsetPath, parseCameraName, parseSignalId, queuePath, toLngLat, type LngLat } from "../lib/grid";
import { HEATMAP_COLOR, heatFeatures, heatPoints, hotCameras, type HeatStretch } from "../lib/heat";
import type { Incident } from "../lib/incidents";
import { luminance, type Theme } from "../lib/palettes";
import { HEALTHY, STATUS_COLOR, roadColor } from "../lib/semantic";
import { HEAVY_QUEUE } from "../lib/scenario";
import { CAR_COLOR, carState, type CarState } from "../lib/traffic";
import { MapLayerControls, MapNavigationControls, type Layers } from "./MapControls";

type MapColors = Theme["map"];

/** Free vector tiles, no key. Repainted below to the ellipsis map palette (§8). */
const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const fallbackStyle = (c: MapColors): StyleSpecification => ({
  version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": c.ground } }],
});

// Midtown, rotated so the avenues run up the screen (the grid is ~29° off true north).
const HOME = { center: [-73.9905, 40.7512] as LngLat, zoom: 14.9, pitch: 48, bearing: 29 };

export interface SimOverlay {
  incident: Incident;
  targetVehicles: number;       // queue the animation eases toward
  signals: { lngLat: LngLat; text: string; changed: boolean }[];
  flowing: boolean;             // vehicle particles running
}

interface Props {
  incidents: Incident[];
  cameras: Camera[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Camera opened from the map (its panel shows the live feed), and how to open one. */
  selectedCameraId?: string | null;
  onSelectCamera?: (id: string) => void;
  layers: Layers;
  onLayers: (l: Layers) => void;
  sim: SimOverlay | null;
  insetLeft: number;
  insetRight: number;
  insetBottom?: number;
  colors: MapColors;
  /** Screen position (viewport px) of the simulated incident, for the scenario connectors. */
  onAnchor?: (pt: { x: number; y: number } | null) => void;
  /** Slow / congested street stretches (lib/heat.ts), shown as a heat glow with the Traffic
   * layer. Their cameras' incident queue lines aren't drawn: the heat replaces them. */
  heat?: HeatStretch[];
}

const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features });
const point = (c: LngLat, props: Record<string, unknown>): GeoJSON.Feature => ({ type: "Feature", properties: props, geometry: { type: "Point", coordinates: c } });
const line = (c: LngLat[], props: Record<string, unknown>): GeoJSON.Feature => ({ type: "Feature", properties: props, geometry: { type: "LineString", coordinates: c } });

function repaint(map: MLMap, PALETTE: MapColors) {
  const style = map.getStyle();
  let buildingSource: { source: string; layer: string } | null = null;
  let firstSymbol: string | undefined;
  for (const l of style.layers) {
    const id = l.id.toLowerCase();
    const set = (prop: string, v: unknown) => { try { (map.setPaintProperty as (id: string, p: string, v: unknown) => void).call(map, l.id, prop, v); } catch { /* layer lacks prop */ } };
    if (l.type === "background") set("background-color", PALETTE.background);
    else if (l.type === "fill" && /water|ocean|river|lake/.test(id)) set("fill-color", PALETTE.water);
    else if (l.type === "line" && /water|river|waterway/.test(id)) set("line-color", PALETTE.water);
    else if (l.type === "line" && /rail/.test(id)) {
      // Rail is geographic context only: muted, thin, low opacity, never a focal line (§58).
      if (/dash/.test(id)) { map.setLayoutProperty(l.id, "visibility", "none"); continue; }
      set("line-color", /service|transit/.test(id) ? PALETTE.rail2 : PALETTE.rail);
      set("line-opacity", PALETTE.railOpacity);
      set("line-width", 0.8);
    }
    else if (l.type === "line" && /boundary/.test(id)) set("line-color", PALETTE.minorLabel);
    else if (/aeroway|pier/.test(id)) set(l.type === "fill" ? "fill-color" : "line-color", PALETTE.road);
    else if (l.type === "fill" && /park|grass|wood|forest|garden|pitch|cemetery/.test(id)) set("fill-color", PALETTE.park);
    else if (l.type === "fill" && /building/.test(id)) {
      if ("source-layer" in l && l["source-layer"]) buildingSource = { source: l.source as string, layer: l["source-layer"] as string };
      map.setLayoutProperty(l.id, "visibility", "none");
    } else if (l.type === "fill" && /landuse|landcover|residential|industrial|commercial/.test(id)) set("fill-color", PALETTE.ground);
    else if (l.type === "line" && /casing/.test(id)) set("line-color", PALETTE.road2);
    else if (l.type === "line" && /road|highway|street|bridge|tunnel|motorway|trunk|primary|secondary|tertiary|minor|service|path/.test(id)) {
      set("line-color", /minor|service|path|track|pedestrian|footway/.test(id) ? PALETTE.road2 : PALETTE.road);
    } else if (l.type === "symbol") {
      firstSymbol ??= l.id;
      if (/poi|housenumber|transit|rail|aerodrome|shield/.test(id)) map.setLayoutProperty(l.id, "visibility", "none");
      set("text-color", /minor|path|service/.test(id) ? PALETTE.minorLabel : PALETTE.label);
      set("text-halo-color", PALETTE.halo);
    }
  }
  // Sides read darker than tops through the light; intensity comes from the palette's two tones.
  const shade = Math.min(0.6, Math.max(0.15, (1 - luminance(PALETTE.buildingSide) / Math.max(luminance(PALETTE.buildingTop), 0.001)) * 1.7));
  if (map.getLayer("buildings-3d")) {
    map.setPaintProperty("buildings-3d", "fill-extrusion-color", PALETTE.mass);
    map.setLight({ anchor: "viewport", color: PALETTE.light, intensity: shade, position: [1.2, 210, 40] });
  } else if (buildingSource) {
    map.addLayer({
      id: "buildings-3d", type: "fill-extrusion", source: buildingSource.source, "source-layer": buildingSource.layer, minzoom: 13,
      paint: {
        "fill-extrusion-color": PALETTE.mass,
        // Restrained: real heights scaled down so markers stay readable at corridor pitch.
        "fill-extrusion-height": ["*", 0.55, ["coalesce", ["get", "render_height"], ["get", "height"], 12]],
        "fill-extrusion-base": ["*", 0.55, ["coalesce", ["get", "render_min_height"], ["get", "min_height"], 0]],
        "fill-extrusion-opacity": 0.9,
        "fill-extrusion-vertical-gradient": true,
      },
    }, firstSymbol);
    map.setLight({ anchor: "viewport", color: PALETTE.light, intensity: shade, position: [1.2, 210, 40] });
  }
}

/** Overlay colours that follow the palette (semantic colours stay fixed). */
function paintOverlays(map: MLMap, c: MapColors) {
  const set = (id: string, prop: string, v: unknown) => { if (map.getLayer(id)) (map.setPaintProperty as (i: string, p: string, v: unknown) => void).call(map, id, prop, v); };
  // camera dot + icon colour comes with the data: the camera's incident status, else live / off
  set("cams", "circle-stroke-color", c.markerStroke);
  set("cams-icon", "icon-halo-color", c.markerStroke);
  set("signals", "circle-color", c.signal);
  set("signals", "circle-stroke-color", c.markerStroke);
  set("incident-ring", "circle-stroke-color", c.ring);
  set("incidents", "circle-stroke-color", ["case", ["==", ["get", "status"], "critical"], c.carQueued, c.markerStroke]);
}

/** Small top-down car glyph, pointing east; rotated per feature on the map. */
/** Video-camera glyph (rounded body + lens wedge, like the FaceTime logo), white on
 * transparent: an SDF icon, coloured by the layer like the camera dot under it. */
function cameraImage(): ImageData | null {
  const c = document.createElement("canvas");
  c.width = 32; c.height = 22;
  const ctx = c.getContext("2d");
  if (!ctx) return null;
  ctx.fillStyle = "white";
  ctx.beginPath();
  ctx.roundRect(2, 3, 20, 16, 4); // body
  ctx.fill();
  ctx.beginPath();                // lens wedge, opening to the right
  ctx.moveTo(23, 9);
  ctx.lineTo(29, 4.5);
  ctx.quadraticCurveTo(30.5, 4, 30.5, 5.5);
  ctx.lineTo(30.5, 16.5);
  ctx.quadraticCurveTo(30.5, 18, 29, 17.5);
  ctx.lineTo(23, 13);
  ctx.closePath();
  ctx.fill();
  return ctx.getImageData(0, 0, 32, 22);
}

function carImage(color: string): ImageData | null {
  const c = document.createElement("canvas");
  c.width = 28; c.height = 14;
  const ctx = c.getContext("2d");
  if (!ctx) return null;
  const r = 4;
  ctx.beginPath();
  ctx.roundRect(1, 1.5, 26, 11, r);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 1.2;
  ctx.strokeStyle = "rgba(0,0,0,0.55)";
  ctx.stroke();
  ctx.fillStyle = "rgba(0,0,0,0.28)"; // windscreen, marks the direction of travel
  ctx.fillRect(17, 3.5, 4, 7);
  return ctx.getImageData(0, 0, 28, 14);
}

function addOverlays(map: MLMap) {
  for (const st of Object.keys(CAR_COLOR) as CarState[]) {
    const img = !map.hasImage(`car-${st}`) && carImage(CAR_COLOR[st]);
    if (img) map.addImage(`car-${st}`, img, { pixelRatio: 2 });
  }
  const cam = !map.hasImage("cam-icon") && cameraImage();
  if (cam) map.addImage("cam-icon", cam, { pixelRatio: 2, sdf: true });
  for (const id of ["impact", "cams", "signals", "incidents", "sim-queue", "sim-cars"]) {
    if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: fc([]) });
  }
  const add = (spec: Parameters<MLMap["addLayer"]>[0]) => { if (!map.getLayer(spec.id)) map.addLayer(spec); };
  // Congestion heatmap: its own classic heat ramp, drawn over the buildings but under the
  // labels and every other overlay, so it adds a glow without restyling anything.
  if (!map.getSource("congestion-heat")) map.addSource("congestion-heat", { type: "geojson", data: fc([]) });
  if (!map.getLayer("congestion-heat")) {
    map.addLayer({
      id: "congestion-heat", type: "heatmap", source: "congestion-heat",
      paint: {
        "heatmap-weight": ["get", "weight"],
        "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 12, 1.2, 15, 1.1, 17, 1.4],
        "heatmap-radius": ["interpolate", ["exponential", 2], ["zoom"], 12, 8, 14, 16, 15, 26, 17, 80],
        "heatmap-color": HEATMAP_COLOR,
        "heatmap-opacity": 0.75,
      },
    }, map.getStyle().layers.find((l) => l.type === "symbol")?.id);
  }
  add({ id: "impact", type: "line", source: "impact", layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": ["get", "color"], "line-width": ["case", ["get", "selected"], 5, 3], "line-opacity": ["case", ["get", "selected"], 0.95, 0.6] } });
  // Queue trail: support only; the cars carry the state (fix brief §57).
  add({ id: "sim-queue", type: "line", source: "sim-queue", layout: { "line-cap": "round" },
    paint: { "line-color": ["get", "color"], "line-width": 2, "line-opacity": 0.35 } });
  add({ id: "sim-cars", type: "symbol", source: "sim-cars",
    layout: {
      "icon-image": ["get", "icon"], "icon-rotate": ["get", "rot"], "icon-rotation-alignment": "map", "icon-pitch-alignment": "map",
      "icon-allow-overlap": true, "icon-ignore-placement": true,
      "icon-size": ["interpolate", ["linear"], ["zoom"], 14, 0.55, 16, 0.85, 18, 1.4],
    } });
  add({ id: "cams", type: "circle", source: "cams",
    paint: { "circle-radius": 4, "circle-stroke-width": 1, "circle-color": ["get", "color"] } });
  // Camera icon above each dot; click either to open the camera's live feed.
  add({ id: "cams-icon", type: "symbol", source: "cams",
    layout: {
      "icon-image": "cam-icon", "icon-anchor": "bottom", "icon-offset": [0, -7],
      "icon-size": 1.15, "icon-allow-overlap": true, "icon-ignore-placement": true,
    },
    paint: { "icon-halo-width": 1, "icon-color": ["get", "color"] } });
  add({ id: "signals", type: "circle", source: "signals",
    paint: { "circle-radius": 4, "circle-stroke-width": 1.5 } });
  add({ id: "incident-ring", type: "circle", source: "incidents", filter: ["==", ["get", "selected"], true],
    paint: { "circle-radius": 9, "circle-color": "rgba(0,0,0,0)", "circle-stroke-width": 1.5 } });
  // An incident is its camera's dot in the status colour: the same size as any camera dot
  // (the camera icon above it takes the colour too).
  add({ id: "incidents", type: "circle", source: "incidents",
    paint: {
      "circle-radius": 4,
      "circle-color": ["get", "color"],
      "circle-stroke-width": 1,
      "circle-opacity": ["get", "opacity"], "circle-stroke-opacity": ["get", "opacity"],
    } });
}

export function MapShell(p: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(0); // bumps on every style load
  const [is3d, setIs3d] = useState(true);
  const latest = useRef(p);
  latest.current = p;
  const labelRef = useRef<Marker | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const sigMarkers = useRef<Marker[]>([]);

  // --- create the map once ---
  useEffect(() => {
    if (!el.current) return;
    const map = new MLMap({
      container: el.current, style: STYLE_URL, center: HOME.center, zoom: HOME.zoom, pitch: HOME.pitch, bearing: HOME.bearing,
      maxPitch: 65, attributionControl: { compact: true }, canvasContextAttributes: { antialias: true },
    });
    mapRef.current = map;
    if (import.meta.env.DEV) (window as unknown as { __map: MLMap }).__map = map; // debugging aid
    let fellBack = false;
    map.on("error", (e) => {
      if (!fellBack && !map.isStyleLoaded() && /style|fetch|Failed/i.test(String(e.error?.message ?? ""))) {
        fellBack = true;
        map.setStyle(fallbackStyle(latest.current.colors));
      }
    });
    map.on("style.load", () => {
      repaint(map, latest.current.colors);
      addOverlays(map);
      paintOverlays(map, latest.current.colors);
      setReady((n) => n + 1);
    });
    map.on("click", "incidents", (e) => {
      const id = e.features?.[0]?.properties?.id;
      if (id && !latest.current.sim) latest.current.onSelect(String(id));
    });
    map.on("mouseenter", "incidents", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "incidents", () => { map.getCanvas().style.cursor = ""; });
    for (const layer of ["cams", "cams-icon"]) {
      map.on("click", layer, (e) => {
        const props = e.features?.[0]?.properties;
        // a camera with an incident opens the incident (its panel has the feed too)
        const onIncident = map.queryRenderedFeatures(e.point, { layers: ["incidents"] }).length > 0;
        if (!props?.id || onIncident || latest.current.sim) return;
        if (props.incident) latest.current.onSelect(String(props.incident));
        else latest.current.onSelectCamera?.(String(props.id));
      });
      map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
    }
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // --- overview data: incidents, cameras, signals, road impact ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const { incidents, cameras, selectedId, layers, sim } = p;
    const hot = hotCameras(p.heat ?? []);
    const focusId = sim?.incident.id ?? selectedId;
    const selected = incidents.find((i) => i.id === focusId) ?? null;

    (map.getSource("incidents") as GeoJSONSource).setData(fc(incidents.map((i) => point([i.lon, i.lat], {
      id: i.id, status: i.status, color: STATUS_COLOR[i.status], selected: i.id === focusId,
      opacity: sim && i.id !== focusId ? 0.3 : 1,
    }))));

    const shown = selected?.camera.id ?? p.selectedCameraId; // the camera being looked at
    const worst = layers.incidents || sim ? worstIncidents(incidents) : new Map<string, Incident>();
    (map.getSource("cams") as GeoJSONSource).setData(fc(cameras
      .filter((c) => layers.cameras || c.id === shown || worst.has(c.id))
      .map((c) => {
        const inc = worst.get(c.id);
        const color = inc ? STATUS_COLOR[inc.status] : c.is_online ? HEALTHY : p.colors.cameraOff;
        return point([c.lon, c.lat], { id: c.id, color, incident: inc?.id ?? null });
      })));

    const signalPts = layers.signals && !sim
      ? incidents.flatMap((i) => i.response.changes.map((ch) => parseSignalId(ch.id)).filter(Boolean)
        .map((s) => point(toLngLat(s!.ax, s!.st), {})))
      : [];
    (map.getSource("signals") as GeoJSONSource).setData(fc(signalPts));

    const impact = sim ? [] : incidents.flatMap((i) => {
      const isSel = i.id === selectedId;
      const pos = parseCameraName(i.location);
      if (!pos || !i.response.sim || i.status === "resolved" || !(layers.traffic || isSel)) return [];
      if (layers.traffic && hot.has(i.camera.id)) return []; // the congestion heat shows it
      const q = i.response.sim.queueBefore;
      return [line(queuePath([i.lon, i.lat], pos, q * METERS_PER_VEHICLE), { color: roadColor(q), selected: isSel })];
    });
    (map.getSource("impact") as GeoJSONSource).setData(fc(impact));
    map.setLayoutProperty("incidents", "visibility", layers.incidents || sim ? "visible" : "none");

    // Selected label (DOM, so it uses Geist).
    labelRef.current?.remove();
    labelRef.current = null;
    if (selected) {
      const div = document.createElement("div");
      div.className = "map-label";
      const loc = document.createElement("strong");
      loc.textContent = selected.location;
      const type = document.createElement("span");
      type.textContent = selected.typeLabel;
      div.append(loc, type);
      // In simulation the connectors arrive from above, so the label sits below the marker.
      if (sim) div.classList.add("below");
      labelRef.current = new Marker({ element: div, anchor: sim ? "top" : "bottom" }).setLngLat([selected.lon, selected.lat]).addTo(map);
    }

    // One pulse for incidents that appeared since the last poll (not on first load).
    const ids = new Set(incidents.map((i) => i.id));
    if (seen.current) {
      for (const i of incidents) {
        if (seen.current.has(i.id) || i.status === "resolved") continue;
        const dot = document.createElement("div");
        dot.className = "pulse";
        const m = new Marker({ element: dot }).setLngLat([i.lon, i.lat]).addTo(map);
        setTimeout(() => m.remove(), 1300);
      }
    }
    seen.current = ids;
  }, [p.incidents, p.cameras, p.selectedId, p.selectedCameraId, p.layers, p.sim, p.heat, p.colors, ready]);

  // --- congestion heatmap (Traffic layer; hidden in simulation, which draws its own queue) ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer("congestion-heat")) return;
    const on = p.layers.traffic && !p.sim;
    (map.getSource("congestion-heat") as GeoJSONSource).setData(heatFeatures(heatPoints(p.heat ?? [])));
    map.setLayoutProperty("congestion-heat", "visibility", on ? "visible" : "none");
  }, [p.heat, p.layers.traffic, p.sim, ready]);

  const simId = p.sim?.incident.id ?? null;

  // --- palette swaps repaint in place (no reload) ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    repaint(map, p.colors);
    paintOverlays(map, p.colors);
  }, [p.colors, ready]);

  // --- screen anchor of the simulated incident, for the scenario connectors ---
  useEffect(() => {
    const map = mapRef.current;
    const onAnchor = latest.current.onAnchor;
    if (!map || !ready || !onAnchor) return;
    const inc = latest.current.sim?.incident;
    if (!simId || !inc) { onAnchor(null); return; }
    let raf = 0;
    const update = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const pt = map.project([inc.lon, inc.lat]);
        const box = map.getContainer().getBoundingClientRect();
        latest.current.onAnchor?.({ x: box.left + pt.x, y: box.top + pt.y });
      });
    };
    update();
    map.on("move", update);
    map.on("resize", update);
    return () => { cancelAnimationFrame(raf); map.off("move", update); map.off("resize", update); latest.current.onAnchor?.(null); };
  }, [simId, ready]);

  // --- camera moves ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const padding = simId
      ? { left: 360, right: 40, top: 400, bottom: 60 + (p.insetBottom ?? 0) }
      : { left: p.insetLeft, right: p.insetRight, top: 40, bottom: 40 + (p.insetBottom ?? 0) };
    const target = p.incidents.find((i) => i.id === (simId ?? p.selectedId));
    if (target) {
      map.flyTo({ center: [target.lon, target.lat], zoom: simId ? 16.1 : 16, pitch: simId ? 50 : 52, bearing: HOME.bearing, padding, duration: 1300, essential: true });
      setIs3d(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.selectedId, simId, ready]);

  // --- simulation: changed-signal labels ---
  const sigKey = JSON.stringify(p.sim?.signals ?? []);
  useEffect(() => {
    const map = mapRef.current;
    sigMarkers.current.forEach((m) => m.remove());
    sigMarkers.current = [];
    if (!map || !ready || !p.sim) return;
    for (const s of p.sim.signals) {
      const div = document.createElement("div");
      div.className = `sig-label${s.changed ? " is-changed" : ""}`;
      div.textContent = s.text;
      sigMarkers.current.push(new Marker({ element: div, anchor: "bottom" }).setLngLat(s.lngLat).addTo(map));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sigKey, simId, ready]);

  // --- simulation: car glyphs by state (one animation loop per scenario) ---
  // Two lanes: the blocked curb lane (stopped queue, arrivals slow into its tail) and the
  // passing lane, which slows around the blockage in proportion to the queue.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const queueSrc = map.getSource("sim-queue") as GeoJSONSource;
    const carSrc = map.getSource("sim-cars") as GeoJSONSource;
    const sim = latest.current.sim;
    if (!sim) { queueSrc.setData(fc([])); carSrc.setData(fc([])); return; }
    const pos = parseCameraName(sim.incident.location);
    if (!pos) return;
    const start: LngLat = [sim.incident.lon, sim.incident.lat];
    const reach = Math.max(sim.incident.response.sim?.queueBefore ?? 12, 12) * METERS_PER_VEHICLE + 300;
    const DOWN = 160;
    const upstream = queuePath(start, pos, reach, 24);
    const downstream = queuePath(start, { ...pos, flow: (-pos.flow) as 1 | -1 }, DOWN, 8);
    const curb = offsetPath(upstream, 2.2);
    const through = offsetPath([...downstream.slice().reverse(), ...upstream.slice(1)], -2.2); // s=0 far downstream
    const V = 12;
    const state = {
      vehicles: 0,
      curbMovers: Array.from({ length: 5 }, (_, k) => reach - k * (reach / 5)),
      through: Array.from({ length: 9 }, (_, k) => ({ s: (k * (reach + DOWN)) / 9, v: V })),
    };
    const glyph = (path: LngLat[], d: number, st: CarState): GeoJSON.Feature => {
      const a = along(path, d), b = along(path, Math.max(0, d - 3));
      return point(a, { icon: `car-${st}`, rot: bearing(a, b) - 90 });
    };
    let raf = 0;
    let last = performance.now();
    const frame = (t: number) => {
      const dt = Math.min(0.05, (t - last) / 1000);
      last = t;
      const cur = latest.current.sim;
      const target = cur?.targetVehicles ?? 0;
      state.vehicles += (target - state.vehicles) * Math.min(1, dt * 1.1);
      const qm = state.vehicles * METERS_PER_VEHICLE;
      const pressure = Math.min(1, state.vehicles / HEAVY_QUEUE);
      const cars: GeoJSON.Feature[] = [];
      for (let k = 0; k < Math.floor(state.vehicles); k++) cars.push(glyph(curb, (k + 0.5) * METERS_PER_VEHICLE, "stopped"));
      if (cur?.flowing) {
        state.curbMovers = state.curbMovers.map((d) => {
          const gap = d - qm;
          const nd = d - (gap < 60 ? Math.max(2, gap / 5) : V) * dt;
          return nd <= qm + METERS_PER_VEHICLE ? reach - Math.random() * 30 : nd;
        });
        for (const d of state.curbMovers) cars.push(glyph(curb, d, d - qm < 60 ? "slowing" : "flowing"));
        const block = DOWN; // blockage position along the through path
        state.through = state.through.map((c) => {
          const zone = c.s > block - 20 && c.s < block + Math.max(40, qm * 0.6);
          const target = zone ? V * (1 - 0.8 * pressure) : V;
          const v = c.v + (target - c.v) * Math.min(1, dt * 2);
          const s2 = c.s - v * dt;
          return s2 < 0 ? { s: reach + DOWN - Math.random() * 20, v: V } : { s: s2, v };
        });
        for (const c of state.through) cars.push(glyph(through, c.s, carState(c.v, V)));
      }
      carSrc.setData(fc(cars));
      queueSrc.setData(fc(qm > 1 ? [line(sliceTo(curb, qm), { color: roadColor(state.vehicles) })] : []));
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); queueSrc.setData(fc([])); carSrc.setData(fc([])); };
  }, [simId, ready]);

  const nav = {
    zoomIn: () => mapRef.current?.zoomIn(),
    zoomOut: () => mapRef.current?.zoomOut(),
    toggle3d: () => {
      const next = !is3d;
      setIs3d(next);
      mapRef.current?.easeTo({ pitch: next ? 52 : 0, duration: 600 });
    },
    reset: () => { setIs3d(true); mapRef.current?.flyTo({ ...HOME, duration: 1000, padding: { left: p.insetLeft, right: 0, top: 0, bottom: 0 } }); },
  };

  return (
    <>
      <div ref={el} className="map-shell" role="region" aria-label="Map of Midtown Manhattan with incident markers" />
      {!p.sim && <MapLayerControls layers={p.layers} onChange={p.onLayers} />}
      <MapNavigationControls is3d={is3d} {...nav} />
    </>
  );
}

const SEVERITY: Record<Incident["status"], number> = { critical: 3, confirmed: 2, needs_review: 1, resolved: 0 };

/** Each camera's most severe open incident (resolved ones don't colour the camera). */
function worstIncidents(incidents: Incident[]): Map<string, Incident> {
  const out = new Map<string, Incident>();
  for (const i of incidents) {
    if (i.status === "resolved") continue;
    const cur = out.get(i.camera.id);
    if (!cur || SEVERITY[i.status] > SEVERITY[cur.status]) out.set(i.camera.id, i);
  }
  return out;
}

/** First `meters` of a polyline. */
function sliceTo(path: LngLat[], meters: number): LngLat[] {
  const out: LngLat[] = [path[0]];
  const steps = 24;
  for (let k = 1; k <= steps; k++) out.push(along(path, (meters * k) / steps));
  return out;
}
