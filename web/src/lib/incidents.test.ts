import { CAMERAS, EVENTS, NOW, RECS, ev } from "../test/fixtures";
import {
  cameraCode, changeText, counts, decisionLabel, elapsed, filterIncidents, isActive, simulationOf, sortIncidents,
  statusOf, toIncidents,
} from "./incidents";
import { clock } from "./format";

describe("status", () => {
  it("resolves events not updated within the active window (not in mock mode)", () => {
    const endedAgo = (s: number) => ev({ start_ts: new Date(NOW - (s + 60) * 1000).toISOString(), duration_s: 60 });
    expect(isActive(endedAgo(300), NOW, false)).toBe(true);
    expect(isActive(endedAgo(301), NOW, false)).toBe(false);
    expect(isActive(endedAgo(9999), NOW, true)).toBe(true);
  });

  it("maps confidence and dwell to review / confirmed / critical", () => {
    expect(statusOf(ev({ confidence: 0.71 }), true)).toBe("needs_review");
    expect(statusOf(ev({ confidence: 0.84, duration_s: 255 }), true)).toBe("confirmed");
    expect(statusOf(ev({ confidence: 0.84, duration_s: 300 }), true)).toBe("critical"); // 5x 60 s
    expect(statusOf(ev(), false)).toBe("resolved");
  });
});

describe("mock data", () => {
  const list = toIncidents(EVENTS, CAMERAS, RECS, NOW, true);

  it("builds one incident per mock event with its camera", () => {
    expect(list.map((i) => [i.id, i.location, i.status])).toEqual([
      ["evt_mock_001", "8th Ave @ 33rd St", "confirmed"],
      ["evt_mock_002", "7 Ave @ 34 St", "needs_review"],
      ["evt_mock_003", "7 Ave @ 34 St", "confirmed"],
    ]);
    expect(list[0].camera.code).toBe("CAM-8AV-033");
  });

  it("carries the recommendation: done, running", () => {
    const [dp, sil] = list;
    expect(dp.response.state).toBe("done");
    expect(dp.response.sim).toMatchObject({ baselineDelay: 48.3, recommendedDelay: 39.1, queueBefore: 21, queueAfter: 13, improvementPct: 19 });
    expect(dp.response.sim!.savedPerVehicle).toBeCloseTo(9.2);
    expect(dp.response.changes[0].text).toBe("Green −6s");
    expect(sil.response.state).toBe("done");
    expect(sil.response.sim).toMatchObject({ baselineDelay: 50.4, recommendedDelay: 52.0, queueBefore: 4, queueAfter: 3 });
    expect(sil.response.sim!.savedPerVehicle).toBeCloseTo(-1.6);
    expect(sil.response.changes[0].text).toBe("Green +10s");
    expect(simulationOf({ event_id: "x", intersections: [], sim: null }).state).toBe("running");
  });

  it("drops events whose camera is unknown", () => {
    expect(toIncidents([ev({ camera_id: "nope" })], CAMERAS, {}, NOW, true)).toEqual([]);
  });
});

describe("rail", () => {
  const list = toIncidents(
    [
      ev({ id: "old", confidence: 0.9, start_ts: new Date(NOW - 400_000).toISOString(), duration_s: 250 }),
      ev({ id: "review", confidence: 0.6 }),
      ev({ id: "crit", duration_s: 600 }),
      ev({ id: "gone", start_ts: new Date(NOW - 7_200_000).toISOString(), duration_s: 60 }),
    ],
    CAMERAS, {}, NOW, false,
  );

  it("sorts by severity, then newest", () => {
    expect(sortIncidents(list, "severity").map((i) => i.id)).toEqual(["crit", "old", "review", "gone"]);
    expect(sortIncidents(list, "newest").map((i) => i.id)).toEqual(["review", "crit", "old", "gone"]);
  });

  it("filters and counts", () => {
    expect(filterIncidents(list, "critical").map((i) => i.id)).toEqual(["crit"]);
    expect(filterIncidents(list, "review").map((i) => i.id)).toEqual(["review"]);
    expect(counts(list)).toEqual({ open: 3, critical: 1, review: 1, all: 4 });
  });

  it("counts elapsed time up from first sight, never backwards, for open incidents only", () => {
    const open = list.find((i) => i.id === "old")!;
    const seen = { old: { durationS: open.durationS, atMs: NOW }, gone: { durationS: 60, atMs: NOW } };
    expect(elapsed(open, seen, NOW + 5000)).toBe(open.durationS + 5);
    expect(elapsed({ ...open, durationS: open.durationS + 2 }, seen, NOW + 5000)).toBe(open.durationS + 5);
    expect(elapsed({ ...open, durationS: open.durationS + 9 }, seen, NOW + 5000)).toBe(open.durationS + 9);
    const gone = list.find((i) => i.id === "gone")!;
    expect(elapsed(gone, seen, NOW + 5000)).toBe(gone.durationS);
    expect(elapsed(open, undefined, NOW + 5000)).toBe(open.durationS);
  });
});

it("carries the Claude incident note when there is one", () => {
  const list = toIncidents(EVENTS, CAMERAS, RECS, NOW, true, {}, { evt_mock_001: "A van is double parked." });
  expect(list.map((i) => i.note)).toEqual(["A van is double parked.", null, null]);
});

describe("operator decisions", () => {
  const list = toIncidents(EVENTS, CAMERAS, RECS, NOW, true, { evt_mock_001: "accept", evt_mock_003: "false_positive" });

  it("carries each event's decision, or null", () => {
    expect(list.map((i) => i.decision)).toEqual(["accept", null, "false_positive"]);
  });

  it("labels an accepted recommendation as applied in the sim only", () => {
    expect(decisionLabel("accept", true)).toBe("Applied (sim)");
    expect(decisionLabel("accept", false)).toBe("Accepted");
    expect(decisionLabel("reject", true)).toBe("Rejected");
    expect(decisionLabel("false_positive", true)).toBe("False positive");
  });

  it("stops counting a false positive as open, but keeps it in the list", () => {
    expect(counts(list)).toMatchObject({ open: 2, all: 3 });
    expect(counts(toIncidents(EVENTS, CAMERAS, RECS, NOW, true)).open).toBe(3);
  });
});

it("formats camera codes and clocks", () => {
  expect(cameraCode("7 Ave @ 34 St", "x")).toBe("CAM-7AV-034");
  expect(cameraCode("Broadway @ 38 St", "x")).toBe("CAM-BWY-038");
  expect(cameraCode("Dyer Ave @ W 34 St", "f96c7b05-aaaa")).toBe("CAM-F96C7B05");
  expect(clock(255)).toBe("04:15");
  expect(clock(3720)).toBe("62:00");
  expect(changeText(-6)).toBe("Green −6s");
  expect(simulationOf(null).state).toBe("none");
});
