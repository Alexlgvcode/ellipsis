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

  constructor(private timeline: Timeline, private now: () => number = Date.now) {
    this.timeline = { ...timeline, updates: [...timeline.updates].sort((a, b) => a.t - b.t) };
    this.startedAt = now() - START_AT_S * 1000;
  }

  /** Seconds into the recording, restarting (and forgetting decisions) after each loop. */
  elapsed(): number {
    let e = (this.now() - this.startedAt) / 1000;
    if (e > this.timeline.duration_s + LOOP_PAUSE_S) {
      this.startedAt = this.now() - START_AT_S * 1000;
      this.feedback = {};
      e = START_AT_S;
    }
    return e;
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
    return {
      health: { status: "ok", mock_mode: false, source: "replay" },
      cameras: this.timeline.cameras, events, recommendations, feedback: { ...this.feedback }, notes,
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

let player: Promise<DemoPlayer> | null = null;

export function demoPlayer(): Promise<DemoPlayer> {
  player ??= fetch(`${DEMO_BASE}timeline.json`)
    .then((r) => { if (!r.ok) throw new Error(`demo timeline missing (${r.status})`); return r.json(); })
    .then((t: Timeline) => new DemoPlayer(t));
  return player;
}
