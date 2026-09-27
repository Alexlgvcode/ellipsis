import type {
  Camera, Congestion, Event, Feedback, FeedbackAction, Health, Recommendation, Summary,
} from "./types";

import { DEMO_BASE, demoFrameUrl, demoPlayer } from "./demo";

/** All requests go through the Vite proxy (/api -> LW_API_URL). */
export const API_BASE = "/api";

/** Built with VITE_DEMO=1: no API, the bundled recording plays instead (api/demo.ts). */
export const DEMO = import.meta.env.VITE_DEMO === "1";

export class ApiUnavailable extends Error {}

async function get<T>(path: string, allow404 = false): Promise<T | null> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, { headers: { accept: "application/json" } });
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
  if (DEMO) return (await demoPlayer()).snapshot();
  const [health, cameras, events, fb, sums, congestion] = await Promise.all([
    get<Health>("/health"),
    get<Camera[]>("/cameras"),
    get<Event[]>("/events?limit=100"),
    get<Feedback[]>("/feedback", true),
    get<Summary[]>("/summaries", true),
    get<Congestion[]>("/congestion", true),
  ]);
  const recs = await Promise.all(
    (events ?? []).map((e) => get<Recommendation>(`/recommendations/${encodeURIComponent(e.id)}`, true)),
  );
  const recommendations: Record<string, Recommendation | null> = {};
  (events ?? []).forEach((e, i) => (recommendations[e.id] = recs[i]));
  const feedback = Object.fromEntries((fb ?? []).map((f) => [f.event_id, f.action]));
  const notes = Object.fromEntries((sums ?? []).map((s) => [s.event_id, s.text]));
  return {
    health: health!, cameras: cameras ?? [], events: events ?? [], recommendations, feedback, notes,
    congestion: congestion ?? [], fetchedAt: Date.now(),
  };
}

/** Record the operator's decision on an alert. The latest one replaces the earlier. */
export async function postFeedback(eventId: string, action: FeedbackAction): Promise<void> {
  if (DEMO) return (await demoPlayer()).decide(eventId, action);
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}/events/${encodeURIComponent(eventId)}/feedback`, {
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
  DEMO && path ? `${DEMO_BASE}${path}` : `${API_BASE}/events/${encodeURIComponent(eventId)}/snapshot`;

/** What a camera's view shows: its live NYC DOT still, or in the demo the replay's recorded
 * still for this moment ("" when the replay didn't record that camera). */
export function cameraFrameUrl(cameraId: string, imageUrl: string | null, bucket: number): string {
  if (DEMO) {
    const frame = demoFrameUrl(cameraId);
    if (frame !== undefined) return frame ?? "";
  }
  return imageUrl ? `${imageUrl}${imageUrl.includes("?") ? "&" : "?"}t=${bucket}` : "";
}

/** The spoken alert for an event (ElevenLabs), or null when there is none. */
export async function voiceUrl(eventId: string): Promise<string | null> {
  if (DEMO) return (await demoPlayer()).voice(eventId);
  return `${API_BASE}/events/${encodeURIComponent(eventId)}/voice`;
}
