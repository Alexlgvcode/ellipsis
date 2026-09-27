import type { Congestion } from "../api/types";
import { CAMERAS, CONGESTION, NOW } from "../test/fixtures";
import { distance, toLngLat } from "./grid";
import {
  HEAT_REACH_M, HEAT_STALE_S, heatFeatures, heatPoints, heatStretches, hotCameras,
} from "./heat";

const cam = (name: string) => CAMERAS.find((c) => c.name === name)!;
const reading = (over: Partial<Congestion> = {}): Congestion => ({
  camera_id: cam("7 Ave @ 32 St").id, approach: "7_ave", direction: "southbound",
  ts: new Date(NOW - 30_000).toISOString(), level: "congested", score: 0.8, occupancy: 0.3,
  stuck_share: 0.7, since_ts: new Date(NOW - 600_000).toISOString(), ...over,
});
const stretches = (rs: Congestion[], mock = false) => heatStretches(rs, CAMERAS, NOW, mock);

describe("congestion heat", () => {
  it("puts heat only where traffic is slow or congested", () => {
    expect(stretches([reading({ level: "free", score: 0 })])).toEqual([]);
    expect(heatPoints(stretches([reading()])).length).toBeGreaterThan(5);
  });

  it("runs up the street against the flow (7 Ave is southbound: the queue is to the north)", () => {
    const c = cam("7 Ave @ 32 St");
    const pts = heatPoints(stretches([reading()]));
    const far = pts[pts.length - 1].lngLat;
    expect(far[1]).toBeGreaterThan(c.lat);
    expect(distance([c.lon, c.lat], far)).toBeLessThanOrEqual(HEAT_REACH_M + 1);
    // near the camera it's hotter than at the far end
    expect(pts.find((p) => distance([c.lon, c.lat], p.lngLat) < 5)!.weight).toBeGreaterThan(pts[pts.length - 1].weight);
    expect(toLngLat(1, 33)[1]).toBeGreaterThan(toLngLat(1, 32)[1]); // sanity: uptown is north
  });

  it("is stronger and longer for a jam than for slow traffic", () => {
    const jam = heatPoints(stretches([reading()]));
    const slow = heatPoints(stretches([reading({ level: "slow", score: 0.1 })]));
    expect(slow.length).toBeLessThan(jam.length);
    expect(Math.max(...slow.map((p) => p.weight))).toBeCloseTo(0.35); // slow still shows
    expect(Math.max(...jam.map((p) => p.weight))).toBeCloseTo(0.8);
  });

  it("drops stale readings, except in mock mode", () => {
    const old = reading({ ts: new Date(NOW - (HEAT_STALE_S + 5) * 1000).toISOString() });
    expect(stretches([old])).toEqual([]);
    expect(stretches([old], true)).toHaveLength(1);
  });

  it("ignores cameras it doesn't know and builds GeoJSON for the map", () => {
    expect(stretches([reading({ camera_id: "nope" })])).toEqual([]);
    const s = stretches(CONGESTION, true);
    const fc = heatFeatures(heatPoints(s));
    expect(fc.features.length).toBeGreaterThan(20); // mock: three jams + two slow cameras
    expect(fc.features.every((f) => (f.properties!.weight as number) > 0)).toBe(true);
  });

  it("lists the glowing cameras, whose incident queue lines the map leaves out", () => {
    const hot = hotCameras(stretches(CONGESTION, true));
    expect(hot.has(cam("8th Ave @ 33rd St").id)).toBe(true);  // mock: congested behind evt_mock_001
    expect(hot.has(cam("8th Ave @ 31st St").id)).toBe(false); // mock: free
    expect(hotCameras(stretches(CONGESTION)).size).toBe(0);    // mock readings are stale when live
  });
});
