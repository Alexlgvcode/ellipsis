import type { ExpressionSpecification } from "maplibre-gl";
import type { Camera, Congestion, CongestionLevel } from "../api/types";
import { METERS_PER_STREET, along, parseCameraName, pathLength, queuePath, type GridPos, type LngLat } from "./grid";

/**
 * Congestion heatmap (issue #47): at each camera whose traffic is slow or congested, a
 * stretch of street upstream of the camera (where the queue builds), as weighted points for
 * a MapLibre heatmap layer. Free cameras add no heat.
 */

/** Readings older than this are dropped: the pipeline re-posts every 60 s while a jam lasts. */
export const HEAT_STALE_S = 180;

/** Street covered at full intensity, upstream of the camera. */
export const HEAT_REACH_M = 1.5 * METERS_PER_STREET;

/** A bit of heat downstream too, so it sits on the intersection the camera watches. */
const DOWNSTREAM_M = 25;
const SPACING_M = 8;

/** Minimum weight per level, so a slow camera with a low score still shows. */
const LEVEL_WEIGHT = { free: 0, slow: 0.35, congested: 0.7 } as const;

const FLOW: Record<string, 1 | -1> = { northbound: 1, southbound: -1 };

export interface HeatPoint {
  lngLat: LngLat;
  weight: number; // 0-1
}

export interface HeatStretch {
  path: LngLat[];   // from just downstream of the camera to the end of the queue
  weight: number;   // 0-1
  level: Exclude<CongestionLevel, "free">;
  cameraId: string;
}

export function isFresh(c: Congestion, nowMs: number, mockMode: boolean): boolean {
  return mockMode || (nowMs - Date.parse(c.ts)) / 1000 <= HEAT_STALE_S;
}

/** The street stretch of every fresh slow or congested reading. */
export function heatStretches(readings: Congestion[], cameras: Camera[], nowMs: number, mockMode: boolean): HeatStretch[] {
  const byId = new Map(cameras.map((c) => [c.id, c]));
  return readings.flatMap((r) => {
    const cam = byId.get(r.camera_id);
    if (!cam || r.level === "free" || !isFresh(r, nowMs, mockMode)) return [];
    const weight = Math.min(1, Math.max(r.score, LEVEL_WEIGHT[r.level]));
    const start: LngLat = [cam.lon, cam.lat];
    const parsed = parseCameraName(cam.name);
    const base = { weight, level: r.level, cameraId: r.camera_id };
    if (!parsed) return [{ ...base, path: [start] }]; // cross-street camera: heat on the camera
    const pos: GridPos = { ...parsed, flow: FLOW[r.direction ?? ""] ?? parsed.flow };
    const up = queuePath(start, pos, HEAT_REACH_M * (0.4 + 0.6 * weight), 12);
    const down = queuePath(start, { ...pos, flow: (-pos.flow) as 1 | -1 }, DOWNSTREAM_M, 2);
    return [{ ...base, path: [...down.slice(1).reverse(), ...up] }];
  });
}

/** Weighted points along each stretch, fading up the street, for the heatmap layer. */
export function heatPoints(stretches: HeatStretch[]): HeatPoint[] {
  return stretches.flatMap(({ path, weight }) => {
    if (path.length === 1) return [{ lngLat: path[0], weight }];
    const reach = pathLength(path) - DOWNSTREAM_M; // the camera is DOWNSTREAM_M along the path
    const pts: HeatPoint[] = [];
    for (let d = SPACING_M; d <= DOWNSTREAM_M; d += SPACING_M) {
      pts.push({ lngLat: along(path, DOWNSTREAM_M - d), weight: weight * 0.6 });
    }
    for (let up = 0; up <= reach; up += SPACING_M) { // fades up the street
      pts.push({ lngLat: along(path, DOWNSTREAM_M + up), weight: weight * (1 - 0.5 * (up / reach)) });
    }
    return pts;
  });
}

/** Cameras whose traffic glows: their incidents' queue lines are left out, since the heat
 * already shows the traffic there. */
export function hotCameras(stretches: HeatStretch[]): Set<string> {
  return new Set(stretches.map((s) => s.cameraId));
}

export function heatFeatures(points: HeatPoint[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: points.map((p) => ({ type: "Feature", properties: { weight: p.weight }, geometry: { type: "Point", coordinates: p.lngLat } })),
  };
}

/** The heat ramp (semantic, the same in every palette): transparent -> blue -> green ->
 * yellow -> orange -> dark red, by heatmap density. */
export const HEATMAP_COLOR: ExpressionSpecification = ["interpolate", ["linear"], ["heatmap-density"],
  0, "rgba(0,0,255,0)", 0.12, "rgba(40,90,255,0.35)", 0.3, "rgba(0,200,140,0.55)",
  0.5, "rgba(160,230,0,0.7)", 0.68, "rgba(255,215,0,0.8)", 0.84, "rgba(255,80,0,0.85)",
  1, "rgba(140,0,0,0.9)"];
