import type { Camera, Event, EventType, FeedbackAction, LaneZone, Recommendation } from "../api/types";
import { ACTIVE_WINDOW_S, CRITICAL_RATIO, DWELL_S, METERS_PER_VEHICLE, REVIEW_BELOW } from "./rules";

export type IncidentStatus = "needs_review" | "confirmed" | "critical" | "resolved";
export type CameraState = "live" | "offline";

export const TYPE_LABEL: Record<EventType, string> = {
  double_parked: "Double parked",
  stopped_in_lane: "Stopped in lane",
  blocked_box: "Blocking the box",
  frozen_feed: "Frozen camera feed",
};

export const TYPE_TITLE: Record<EventType, string> = {
  double_parked: "Double parked vehicle",
  stopped_in_lane: "Vehicle stopped in lane",
  blocked_box: "Vehicle blocking the box",
  frozen_feed: "Camera feed frozen",
};

export const ZONE_LABEL: Record<LaneZone, string> = {
  curb: "curb lane",
  curb_adjacent: "travel lane next to curb",
  travel: "travel lane",
  box: "intersection box",
  bus_stop: "bus stop",
  ignore: "ignored area",
  none: "unmapped",
};

export const STATUS_LABEL: Record<IncidentStatus, string> = {
  needs_review: "Needs review",
  confirmed: "Confirmed",
  critical: "Critical",
  resolved: "Resolved",
};

/** An accepted recommendation is applied in the simulation only, never to real signals. */
export function decisionLabel(action: FeedbackAction, hasResponse: boolean): string {
  if (action === "accept") return hasResponse ? "Applied (sim)" : "Accepted";
  return action === "reject" ? "Rejected" : "False positive";
}

const STATUS_RANK: Record<IncidentStatus, number> = { critical: 0, confirmed: 1, needs_review: 2, resolved: 3 };

export interface Simulation {
  baselineDelay: number;
  recommendedDelay: number;
  savedPerVehicle: number;
  improvementPct: number;
  queueBefore: number;
  queueAfter: number;
  /** Queue on the blocked lane every 15 s, when the run recorded one. */
  seriesDefault?: number[];
  seriesNew?: number[];
}

export interface SignalChangeView {
  id: string;
  phase: number;
  changeS: number;
  text: string;
}

export interface Incident {
  id: string;
  type: EventType;
  status: IncidentStatus;
  title: string;
  typeLabel: string;
  location: string;
  lat: number;
  lon: number;
  startedAt: string;
  durationS: number;
  confidence: number;
  thresholdS: number;
  laneZone: LaneZone;
  bbox: [number, number, number, number];
  /** The API has the frame from when the alert fired. */
  hasSnapshot: boolean;
  snapshotPath: string | null;
  camera: { id: string; code: string; name: string; state: CameraState; imageUrl: string | null };
  response: { state: "none" | "running" | "done"; changes: SignalChangeView[]; sim: Simulation | null };
  decision: FeedbackAction | null;
  /** Claude incident note, if one was written. */
  note: string | null;
}

/** "8th Ave @ 33rd St" -> "CAM-8AV-033"; falls back to the id prefix. */
export function cameraCode(name: string, id: string): string {
  const av = /^(\d+)(?:st|nd|rd|th)?\s+Ave/i.exec(name);
  const bw = /^Broadway/i.test(name);
  const st = /@\s*(?:W\s*)?(\d+)/i.exec(name) ?? /(\d+)\s*St\s*$/i.exec(name);
  if ((av || bw) && st) return `CAM-${bw ? "BWY" : `${av![1]}AV`}-${st[1].padStart(3, "0")}`;
  return `CAM-${id.slice(0, 8).toUpperCase()}`;
}

export function isActive(e: Event, nowMs: number, mockMode: boolean): boolean {
  if (mockMode) return true;
  const endMs = Date.parse(e.start_ts) + e.duration_s * 1000;
  return (nowMs - endMs) / 1000 <= ACTIVE_WINDOW_S;
}

export function statusOf(e: Event, active: boolean): IncidentStatus {
  if (!active) return "resolved";
  if (e.confidence < REVIEW_BELOW) return "needs_review";
  const thr = DWELL_S[e.type] || 1;
  return e.duration_s >= CRITICAL_RATIO * thr ? "critical" : "confirmed";
}

export function changeText(changeS: number): string {
  return `Green ${changeS > 0 ? "+" : "−"}${Math.abs(changeS)}s`;
}

export function simulationOf(rec: Recommendation | null | undefined): Incident["response"] {
  if (!rec) return { state: "none", changes: [], sim: null };
  const changes = rec.intersections.map((s) => ({ id: s.id, phase: s.phase, changeS: s.change_s, text: changeText(s.change_s) }));
  if (!rec.sim) return { state: "running", changes, sim: null };
  const { delay_default: d0, delay_new: d1, queue_default: q0, queue_new: q1 } = rec.sim;
  return {
    state: "done",
    changes,
    sim: {
      baselineDelay: d0, recommendedDelay: d1, savedPerVehicle: d0 - d1,
      improvementPct: d0 > 0 ? Math.round(((d0 - d1) / d0) * 100) : 0,
      queueBefore: q0, queueAfter: q1,
      seriesDefault: rec.sim.queue_series_default ?? [],
      seriesNew: rec.sim.queue_series_new ?? [],
    },
  };
}

export function toIncidents(
  events: Event[], cameras: Camera[], recs: Record<string, Recommendation | null>, nowMs: number, mockMode: boolean,
  feedback: Record<string, FeedbackAction> = {}, notes: Record<string, string> = {},
): Incident[] {
  const byId = new Map(cameras.map((c) => [c.id, c]));
  return events.flatMap((e) => {
    const cam = byId.get(e.camera_id);
    if (!cam) return [];
    const active = isActive(e, nowMs, mockMode);
    return [{
      id: e.id,
      type: e.type,
      status: statusOf(e, active),
      title: TYPE_TITLE[e.type],
      typeLabel: TYPE_LABEL[e.type],
      location: cam.name,
      lat: cam.lat,
      lon: cam.lon,
      startedAt: e.start_ts,
      durationS: e.duration_s,
      confidence: e.confidence,
      thresholdS: DWELL_S[e.type],
      laneZone: e.lane_zone,
      bbox: e.bbox,
      hasSnapshot: Boolean(e.snapshot_path),
      snapshotPath: e.snapshot_path ?? null,
      camera: {
        id: cam.id, code: cameraCode(cam.name, cam.id), name: cam.name,
        state: cam.is_online ? "live" : "offline", imageUrl: cam.image_url || null,
      },
      response: simulationOf(recs[e.id]),
      decision: feedback[e.id] ?? null,
      note: notes[e.id] ?? null,
    }];
  });
}

export type RailFilter = "critical" | "review" | "all";
export type RailSort = "severity" | "newest";

export function filterIncidents(list: Incident[], filter: RailFilter): Incident[] {
  if (filter === "critical") return list.filter((i) => i.status === "critical");
  if (filter === "review") return list.filter((i) => i.status === "needs_review");
  return list;
}

export function sortIncidents(list: Incident[], sort: RailSort): Incident[] {
  const newest = (a: Incident, b: Incident) => Date.parse(b.startedAt) - Date.parse(a.startedAt);
  return [...list].sort((a, b) =>
    sort === "severity" ? STATUS_RANK[a.status] - STATUS_RANK[b.status] || newest(a, b) : newest(a, b));
}

export function counts(list: Incident[]) {
  // a false positive is dismissed: it stays in the list but isn't an open incident
  const open = list.filter((i) => i.status !== "resolved" && i.decision !== "false_positive");
  return {
    open: open.length,
    critical: open.filter((i) => i.status === "critical").length,
    review: open.filter((i) => i.status === "needs_review").length,
    all: list.length,
  };
}

/** When an incident was first seen by this browser, and its API duration at that moment. */
export type FirstSeen = Record<string, { durationS: number; atMs: number }>;

/**
 * Elapsed time shown on screen. Counts up smoothly from when the browser first saw the
 * incident, and never goes backwards when a poll returns a slightly stale duration.
 */
export function elapsed(i: Incident, seen: FirstSeen | undefined, nowMs: number): number {
  const first = seen?.[i.id];
  if (i.status === "resolved" || !first) return i.durationS;
  return Math.max(i.durationS, first.durationS + Math.max(0, (nowMs - first.atMs) / 1000));
}

/** Queue length on the blocked approach in metres (simulated baseline), if known. */
export const queueMeters = (vehicles: number) => vehicles * METERS_PER_VEHICLE;
