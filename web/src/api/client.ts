import type {
  Camera, Congestion, Event, Feedback, FeedbackAction, Health, Recommendation, Summary,
} from "./types";

import { DEMO_BASE, demoFrameUrl, demoPlayer } from "./demo";

/** All requests go through the Vite proxy (/api -> LW_API_URL). */
export const API_BASE = "/api";

/** Built with VITE_DEMO=1: no API, the bundled recording plays instead (api/demo.ts). */
export const DEMO = import.meta.env.VITE_DEMO === "1";

/** The hosted live API (deploy/). A demo build that has one tries it first. */
const LIVE_API = (import.meta.env.VITE_LIVE_API as string | undefined)?.replace(/\/$/, "") || null;

/**
 * Where the data comes from: "api" (a dev build through the Vite proxy), "hosted" (the demo
 * site reading the live API, decisions kept in this browser) or "demo" (the bundled recording).
 */
export type Source = "api" | "hosted" | "demo";

/** How long the demo site waits for the live API before playing the recording. */
export const LIVE_TIMEOUT_MS = 4000;

/**
 * The demo site's source: the live API when it answers in time and is serving real events,
 * else the recording. `?replay` or `?sample` asks for the recording. `unreachable` says the
 * live API was tried and didn't answer, so the page can say why it's showing a recording.
 */
export async function chooseSource(search: string, liveApi: string | null,
  fetchFn: typeof fetch = fetch): Promise<{ source: Source; unreachable: boolean }> {
  const q = new URLSearchParams(search);
  if (!liveApi || q.has("replay") || q.has("sample")) return { source: "demo", unreachable: false };
  try {
    const resp = await fetchFn(`${liveApi}/health`, { signal: AbortSignal.timeout(LIVE_TIMEOUT_MS) });
    const health = resp.ok ? ((await resp.json()) as Health) : null;
    if (health && !health.mock_mode) return { source: "hosted", unreachable: false };
  } catch { /* offline, timed out or blocked: play the recording */ }
  return { source: "demo", unreachable: true };
}

let source: Source = DEMO ? "demo" : "api";
let chosen: Promise<Source> | null = null;
/** The live API was tried and couldn't be reached, so the recording is playing. */
export let liveUnreachable = false;

function resolveSource(): Promise<Source> {
  if (!DEMO) return Promise.resolve(source);
  chosen ??= chooseSource(typeof location === "undefined" ? "" : location.search, LIVE_API)
    .then((c) => { source = c.source; liveUnreachable = c.unreachable; return source; });
  return chosen;
}

/** The source in use (after the first snapshot). */
export const currentSource = (): Source => source;
const base = () => (source === "hosted" ? LIVE_API! : API_BASE);
/** On the public site, a visitor's decisions stay in their browser. */
const localDecisions: Record<string, FeedbackAction> = {};

export class ApiUnavailable extends Error {}

async function get<T>(path: string, allow404 = false): Promise<T | null> {
  let resp: Response;
  try {
    resp = await fetch(`${base()}${path}`, { headers: { accept: "application/json" } });
  } catch (e) {
    throw new ApiUnavailable(`API unreachable: ${(e as Error).message}`);
  }
  if (allow404 && resp.status === 404) return null;
  if (!resp.ok) throw new ApiUnavailable(`API error ${resp.status} on ${path}`);
  return (await resp.json()) as T;
}

export interface Snapshot {
  health: Health;
  cameras: Camera[];
  events: Event[];
  recommendations: Record<string, Recommendation | null>;
  /** Operator decision per event id. */
  feedback: Record<string, FeedbackAction>;
  /** Claude incident note per event id, when one was written. */
  notes: Record<string, string>;
  /** Latest congestion reading per camera approach (empty on an API without /congestion). */
  congestion: Congestion[];
  fetchedAt: number;
}

export async function fetchSnapshot(): Promise<Snapshot> {
  if ((await resolveSource()) === "demo") return (await demoPlayer()).snapshot();
  const hosted = source === "hosted";
  const [health, cameras, events, fb, sums, congestion] = await Promise.all([
    get<Health>("/health"),
    get<Camera[]>("/cameras"),
    get<Event[]>("/events?limit=100"),
    hosted ? Promise.resolve([]) : get<Feedback[]>("/feedback", true),
    get<Summary[]>("/summaries", true),
    get<Congestion[]>("/congestion", true),
  ]);
  const recs = await Promise.all(
    (events ?? []).map((e) => get<Recommendation>(`/recommendations/${encodeURIComponent(e.id)}`, true)),
  );
  const recommendations: Record<string, Recommendation | null> = {};
  (events ?? []).forEach((e, i) => (recommendations[e.id] = recs[i]));
  const feedback = { ...Object.fromEntries((fb ?? []).map((f) => [f.event_id, f.action])), ...localDecisions };
  const notes = Object.fromEntries((sums ?? []).map((s) => [s.event_id, s.text]));
  return {
    health: health!, cameras: cameras ?? [], events: events ?? [], recommendations, feedback, notes,
    congestion: congestion ?? [], fetchedAt: Date.now(),
  };
}

/** Record the operator's decision on an alert. The latest one replaces the earlier. */
export async function postFeedback(eventId: string, action: FeedbackAction): Promise<void> {
  if (source === "demo") return (await demoPlayer()).decide(eventId, action);
  if (source === "hosted") { localDecisions[eventId] = action; return; }
  let resp: Response;
  try {
    resp = await fetch(`${base()}/events/${encodeURIComponent(eventId)}/feedback`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ action }),
    });
  } catch (e) {
    throw new ApiUnavailable(`API unreachable: ${(e as Error).message}`);
  }
  if (!resp.ok) throw new ApiUnavailable(`API error ${resp.status} saving feedback`);
}

export const snapshotUrl = (eventId: string, path?: string | null) =>
  source === "demo" && path ? `${DEMO_BASE}${path}` : `${base()}/events/${encodeURIComponent(eventId)}/snapshot`;

/** What a camera's view shows: its live NYC DOT still, or in the demo the replay's recorded
 * still for this moment ("" when the replay didn't record that camera). */
export function cameraFrameUrl(cameraId: string, imageUrl: string | null, bucket: number): string {
  if (source === "demo") {
    const frame = demoFrameUrl(cameraId);
    if (frame !== undefined) return frame ?? "";
  }
  return imageUrl ? `${imageUrl}${imageUrl.includes("?") ? "&" : "?"}t=${bucket}` : "";
}

/** The spoken alert for an event (ElevenLabs), or null when there is none. */
export async function voiceUrl(eventId: string): Promise<string | null> {
  if (source === "demo") return (await demoPlayer()).voice(eventId);
  return `${base()}/events/${encodeURIComponent(eventId)}/voice`;
}
