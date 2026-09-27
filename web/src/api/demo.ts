import type { Snapshot } from "./client";
import type { Camera, Congestion, Event, FeedbackAction, Recommendation } from "./types";

/**
 * Static demo (issue #55): plays back web/public/demo/timeline.json, a recording of the real
 * pipeline on the demo window (scripts/export_demo.py), as if an API were serving it live.
 * Times are shifted so the recording runs from when the page opened; it loops at the end.
 * Operator decisions stay in this browser.
 */

export interface Timeline {
  t0: string;
  duration_s: number;
  cameras: Camera[];
  updates: { t: number; event: Event }[];
  congestion: { t: number; reading: Congestion }[];
  recommendations: Record<string, { t: number; rec: Recommendation }>;
  /** The incident note the worker writes after scoring (absent in older recordings). */
  notes?: Record<string, { t: number; text: string }>;
  voice: Record<string, string>;
  /** Each camera's recorded stills (seconds from t0): its "live" view during the replay. */
  frames?: Record<string, number[]>;
  /** Where playback opens, and the pause before it loops (defaults below). */
  start_at_s?: number;
  loop_pause_s?: number;
}

/** Open a little before the first alert, so visitors don't wait a whole dwell time. */
export const START_AT_S = 40;
/** Pause after the last update before the recording starts again. */
export const LOOP_PAUSE_S = 120;

export const DEMO_BASE = `${import.meta.env.BASE_URL}demo/`;

const shift = (iso: string, ms: number) => new Date(Date.parse(iso) + ms).toISOString();

export class DemoPlayer {
  private startedAt: number;
  private feedback: Record<string, FeedbackAction> = {};

  private startAt: number;
  private loopPause: number;

  constructor(private timeline: Timeline, private now: () => number = Date.now) {
    this.timeline = { ...timeline, updates: [...timeline.updates].sort((a, b) => a.t - b.t) };
    this.startAt = timeline.start_at_s ?? START_AT_S;
    this.loopPause = timeline.loop_pause_s ?? LOOP_PAUSE_S;
    this.startedAt = now() - this.startAt * 1000;
  }

  /** Seconds into the recording, restarting (and forgetting decisions) after each loop. */
  elapsed(): number {
    let e = (this.now() - this.startedAt) / 1000;
    if (e > this.timeline.duration_s + this.loopPause) {
      this.startedAt = this.now() - this.startAt * 1000;
      this.feedback = {};
      e = this.startAt;
    }
    return e;
  }

  /** The still a camera showed at this point of the replay; null for a camera not recorded. */
  frameUrl(cameraId: string): string | null {
    const times = this.timeline.frames?.[cameraId];
    if (!times?.length) return null;
    const e = this.elapsed();
    let lo = 0, hi = times.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (times[mid] <= e) lo = mid; else hi = mid - 1; }
    return `${DEMO_BASE}frames/${cameraId}/${times[lo]}.webp`;
  }

  snapshot(): Snapshot {
    const e = this.elapsed();
    const ms = this.startedAt - Date.parse(this.timeline.t0);   // recording time -> now
    const latest = new Map<string, Event>();
    for (const u of this.timeline.updates) if (u.t <= e) latest.set(u.event.id, u.event);
    const events = [...latest.values()]
      .map((ev) => ({ ...ev, start_ts: shift(ev.start_ts, ms) }))
      .sort((a, b) => Date.parse(b.start_ts) - Date.parse(a.start_ts));
    const recommendations: Record<string, Recommendation | null> = {};
    const notes: Record<string, string> = {};
    for (const ev of events) {
      const r = this.timeline.recommendations[ev.id];
      recommendations[ev.id] = r && r.t <= e ? r.rec : null;
      const n = this.timeline.notes?.[ev.id];
      if (n && n.t <= e) notes[ev.id] = n.text;
    }
    const congestion = new Map<string, Congestion>();
    for (const c of this.timeline.congestion) {
      if (c.t <= e) {
        const r = c.reading;
        congestion.set(`${r.camera_id}/${r.approach}`, { ...r, ts: shift(r.ts, ms), since_ts: shift(r.since_ts, ms) });
      }
    }
    const frames = this.timeline.frames;
    return {
      health: { status: "ok", mock_mode: false, source: "replay", ...(frames ? { synced: true } : {}) },
      // a synced replay covers the cameras it recorded; the rest aren't part of this recording
      cameras: frames ? this.timeline.cameras.filter((c) => frames[c.id]) : this.timeline.cameras, events, recommendations, feedback: { ...this.feedback }, notes,
      congestion: [...congestion.values()], fetchedAt: this.now(),
    };
  }

  decide(eventId: string, action: FeedbackAction): void {
    this.feedback[eventId] = action;
  }

  voice(eventId: string): string | null {
    const file = this.timeline.voice[eventId];
    return file ? `${DEMO_BASE}${file}` : null;
  }
}

export interface SampleData {
  cameras: Camera[];
  events: Event[];
  recommendations: Recommendation[];
  congestion: Congestion[];
  /** Incident notes written once from each incident's facts (data/mock/summaries.json). */
  summaries?: { event_id: string; text: string }[];
}

/**
 * The API's mock mode, without the API: the real incidents in data/mock/ (scripts/build_mock.py),
 * all at once, with their recommendations and the congestion heatmap. The site's default view.
 */
export class SamplePlayer {
  private feedback: Record<string, FeedbackAction> = {};

  constructor(private data: SampleData, private now: () => number = Date.now) {}

  snapshot(): Snapshot {
    const events = this.data.events.map((e) => ({
      ...e,  // data/mock/snapshots/x.jpg -> demo/sample/snapshots/x.jpg
      snapshot_path: e.snapshot_path ? `sample/snapshots/${e.snapshot_path.split("/").pop()}` : null,
    }));
    const recommendations: Record<string, Recommendation | null> = {};
    for (const e of events) recommendations[e.id] = this.data.recommendations.find((r) => r.event_id === e.id) ?? null;
    const notes = Object.fromEntries((this.data.summaries ?? []).map((n) => [n.event_id, n.text]));
    return {
      health: { status: "ok", mock_mode: true }, cameras: this.data.cameras, events, recommendations,
      feedback: { ...this.feedback }, notes, congestion: this.data.congestion, fetchedAt: this.now(),
    };
  }

  decide(eventId: string, action: FeedbackAction): void {
    this.feedback[eventId] = action;
  }

  voice(): string | null {
    return null;
  }

  frameUrl(): undefined {
    return undefined;  // sample data: cameras show their real live feed
  }
}

type Player = DemoPlayer | SamplePlayer;
let player: Promise<Player> | null = null;
let loaded: Player | null = null;

/**
 * A camera's view in the demo right now: the replay's recorded still (in step with the
 * alerts), null for a camera the replay didn't record, or undefined to use its real feed.
 */
export function demoFrameUrl(cameraId: string): string | null | undefined {
  return loaded ? loaded.frameUrl(cameraId) : undefined;
}

const json = <T,>(path: string): Promise<T> =>
  fetch(`${DEMO_BASE}${path}`).then((r) => { if (!r.ok) throw new Error(`demo data missing: ${path}`); return r.json(); });

/** By default the recorded window plays in real time, every camera in step; `?sample` shows
 * the sample incidents (data/mock/) all at once instead. */
export function demoPlayer(search: string = typeof location === "undefined" ? "" : location.search): Promise<Player> {
  player ??= (!new URLSearchParams(search).has("sample")
    ? json<Timeline>("timeline.json").then((t) => new DemoPlayer(t))
    : Promise.all([
      ...["cameras", "events", "recommendations", "congestion"].map((f) => json(`sample/${f}.json`)),
      json("sample/summaries.json").catch(() => []),  // no notes is fine: the cards hide them
    ]).then(([cameras, events, recommendations, congestion, summaries]) => new SamplePlayer(
        { cameras, events, recommendations, congestion, summaries } as SampleData)))
    .then((p) => (loaded = p));
  return player;
}
