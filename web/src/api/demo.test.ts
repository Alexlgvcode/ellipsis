import { CAMERAS, ev } from "../test/fixtures";
import { DemoPlayer, LOOP_PAUSE_S, START_AT_S, type Timeline } from "./demo";

const T0 = "2026-09-26T18:21:30Z";
const at = (s: number) => new Date(Date.parse(T0) + s * 1000).toISOString();
const rec = { event_id: "a", intersections: [{ id: "tls", phase: 1, change_s: -6.8 }],
  sim: { delay_default: 95.1, delay_new: 88.9, queue_default: 7, queue_new: 9 } };

const TIMELINE: Timeline = {
  t0: T0, duration_s: 300, cameras: CAMERAS,
  updates: [
    { t: 74, event: ev({ id: "a", start_ts: at(14), duration_s: 60, snapshot_path: "snapshots/c/a.jpg" }) },
    { t: 64, event: ev({ id: "b", start_ts: at(3), duration_s: 61 }) },       // out of order on purpose
    { t: 134, event: ev({ id: "a", start_ts: at(14), duration_s: 120 }) },
  ],
  congestion: [{ t: 50, reading: { camera_id: CAMERAS[0].id, approach: "7_ave", ts: at(50), level: "slow",
    score: 0.2, occupancy: 0.3, stuck_share: 0.4, since_ts: at(40) } }],
  recommendations: { a: { t: 99, rec } },
  notes: { a: { t: 99, text: "A truck is double parked." } },
  voice: { a: "voice/a.mp3" },
};

function playerAt(seconds: number) {
  let clock = 1_000_000;
  const player = new DemoPlayer(TIMELINE, () => clock);   // opens at START_AT_S into the recording
  const go = (s: number) => { clock = 1_000_000 + (s - START_AT_S) * 1000; };
  go(seconds);
  return { player, go };
}

it("serves each event's latest state so far, shifted to the time the page opened", () => {
  const { player, go } = playerAt(START_AT_S);
  let snap = player.snapshot();
  expect(snap.events).toEqual([]);
  expect(snap.health).toEqual({ status: "ok", mock_mode: false, source: "replay" });

  go(80);
  snap = player.snapshot();
  expect(snap.events.map((e) => [e.id, e.duration_s])).toEqual([["a", 60], ["b", 61]]);   // newest first
  // recording second 14 is page-open time minus (40 - 14) s
  expect(Date.parse(snap.events[0].start_ts)).toBe(1_000_000 - (START_AT_S - 14) * 1000);

  go(140);
  expect(player.snapshot().events.find((e) => e.id === "a")!.duration_s).toBe(120);
});

it("shows a recommendation only once the worker would have scored it", () => {
  const { player, go } = playerAt(80);
  expect(player.snapshot().recommendations.a).toBeNull();
  expect(player.snapshot().notes).toEqual({});
  go(100);
  expect(player.snapshot().recommendations.a).toEqual(rec);
  expect(player.snapshot().notes).toEqual({ a: "A truck is double parked." });
});

it("carries congestion, decisions and spoken alerts, and starts over after the loop pause", () => {
  const { player, go } = playerAt(60);
  expect(player.snapshot().congestion.map((c) => c.level)).toEqual(["slow"]);
  player.decide("a", "accept");
  expect(player.snapshot().feedback).toEqual({ a: "accept" });
  expect(player.voice("a")).toMatch(/demo\/voice\/a\.mp3$/);
  expect(player.voice("b")).toBeNull();

  go(300 + LOOP_PAUSE_S + 1);
  const again = player.snapshot();
  expect(again.events).toEqual([]);          // back to the start
  expect(again.feedback).toEqual({});
});

it("serves the sample incidents all at once, like the API's mock mode", async () => {
  const { SamplePlayer } = await import("./demo");
  const data = {
    cameras: CAMERAS,
    events: [ev({ id: "a", snapshot_path: "data/mock/snapshots/a.jpg" }), ev({ id: "b" })],
    recommendations: [{ ...rec, event_id: "a" }],
    congestion: TIMELINE.congestion.map((c) => c.reading),
  };
  const player = new SamplePlayer(data, () => 5);
  const snap = player.snapshot();
  expect(snap.health).toEqual({ status: "ok", mock_mode: true });
  expect(snap.events.map((e) => [e.id, e.snapshot_path])).toEqual([["a", "sample/snapshots/a.jpg"], ["b", null]]);
  expect(snap.recommendations).toEqual({ a: { ...rec, event_id: "a" }, b: null });
  expect(snap.congestion).toHaveLength(1);
  expect(snap.notes).toEqual({});                  // no summaries.json: no notes
  player.decide("b", "false_positive");
  expect(player.snapshot().feedback).toEqual({ b: "false_positive" });
  const noted = new SamplePlayer({ ...data, summaries: [{ event_id: "a", text: "A van is double parked." }] });
  expect(noted.snapshot().notes).toEqual({ a: "A van is double parked." });  // b has none: hidden
});

it("a synced replay shows each recorded camera's still for the same moment, and only those cameras", () => {
  let clock = 1_000_000;
  const synced: Timeline = { ...TIMELINE, frames: { [CAMERAS[0].id]: [0, 8, 16, 60] }, start_at_s: 10, loop_pause_s: 5 };
  const player = new DemoPlayer(synced, () => clock);          // opens at 10 s
  expect(player.frameUrl(CAMERAS[0].id)).toMatch(new RegExp(`demo/frames/${CAMERAS[0].id}/8\\.webp$`));
  clock += 50_000;                                              // 60 s in
  expect(player.frameUrl(CAMERAS[0].id)).toMatch(/\/60\.webp$/);
  expect(player.frameUrl(CAMERAS[1].id)).toBeNull();            // not recorded
  const snap = player.snapshot();
  expect(snap.health).toEqual({ status: "ok", mock_mode: false, source: "replay", synced: true });
  expect(snap.cameras.map((c) => c.id)).toEqual([CAMERAS[0].id]);
  clock += (300 + 5 - 60 + 1) * 1000;                           // past the end and the pause
  expect(player.frameUrl(CAMERAS[0].id)).toMatch(/\/8\.webp$/);    // looped back to 10 s
});
