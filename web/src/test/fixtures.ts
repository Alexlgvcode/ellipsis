import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Camera, Congestion, Event, Recommendation } from "../api/types";

export const REPO = resolve(__dirname, "../../..");
const json = <T,>(p: string): T => JSON.parse(readFileSync(resolve(REPO, p), "utf8")) as T;

export const CAMERAS = json<Camera[]>("data/cameras.json");
// The dashboard tests' own sample data: a frozen copy of the original hand-made mocks, so the
// UI tests don't change whenever data/mock/ is rebuilt from the recordings (scripts/build_mock.py).
export const EVENTS = json<Event[]>("web/src/test/data/events.json");
export const RECS: Record<string, Recommendation> = Object.fromEntries(
  json<Recommendation[]>("web/src/test/data/recommendations.json").map((r) => [r.event_id, r]),
);
export const CONGESTION = json<Congestion[]>("web/src/test/data/congestion.json");
export const NOW = Date.parse("2026-09-26T18:00:00Z");

export const ev = (over: Partial<Event> = {}): Event => ({
  id: "e1", camera_id: CAMERAS[0].id, type: "double_parked",
  start_ts: new Date(NOW - 300_000).toISOString(), duration_s: 240,
  bbox: [100, 80, 140, 120], lane_zone: "curb_adjacent", confidence: 0.8, snapshot_path: null, ...over,
});
