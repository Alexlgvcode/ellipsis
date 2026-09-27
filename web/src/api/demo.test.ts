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
  go(100);
  expect(player.snapshot().recommendations.a).toEqual(rec);
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
