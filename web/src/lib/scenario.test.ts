import { EVENTS, RECS, CAMERAS, NOW } from "../test/fixtures";
import { toIncidents } from "./incidents";
import { fmtDelta, queuePressure, timingChange } from "./scenario";

it("turns a signal change into explicit before/after green times from the modeled plan", () => {
  const [dp, sil, bb] = toIncidents(EVENTS, CAMERAS, RECS, NOW, true);
  expect(timingChange(dp.response.changes[0])).toEqual({ signal: "8 Ave @ 32 St", approach: "avenue", before: 45, after: 39, delta: -6 });
  expect(timingChange(bb.response.changes[0])).toMatchObject({ signal: "7 Ave @ 34 St", approach: "street", before: 28, after: 23 });
  expect(timingChange(sil.response.changes[0])).toMatchObject({ before: 45, after: 55 });
  expect(fmtDelta(-6)).toBe("−6s");
  expect(fmtDelta(10)).toBe("+10s");
});

it("describes queue pressure in words", () => {
  expect([21, 13, 5].map(queuePressure)).toEqual(["High", "Moderate", "Low"]);
});

it("names real SUMO signals by intersection, never by their raw id", () => {
  const ch = { id: "cluster_10173490593_10173490594_10173490596_10268795725_#2more", phase: 1, changeS: -10.9, text: "" };
  expect(timingChange(ch).signal).toBe("Broadway @ 39 St");
  expect(timingChange({ ...ch, id: "unknown_cluster" }).signal).toBe("Nearby signal");
});
