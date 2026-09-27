import type { Camera, Event, Feedback, FeedbackAction, Health, Recommendation, Summary } from "./types";

/** All requests go through the Vite proxy (/api -> LW_API_URL). */
export const API_BASE = "/api";

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
  fetchedAt: number;
}

export async function fetchSnapshot(): Promise<Snapshot> {
  const [health, cameras, events, fb, sums] = await Promise.all([
    get<Health>("/health"),
    get<Camera[]>("/cameras"),
    get<Event[]>("/events?limit=100"),
    get<Feedback[]>("/feedback", true),
    get<Summary[]>("/summaries", true),
  ]);
  const recs = await Promise.all(
    (events ?? []).map((e) => get<Recommendation>(`/recommendations/${encodeURIComponent(e.id)}`, true)),
  );
  const recommendations: Record<string, Recommendation | null> = {};
  (events ?? []).forEach((e, i) => (recommendations[e.id] = recs[i]));
  const feedback = Object.fromEntries((fb ?? []).map((f) => [f.event_id, f.action]));
  const notes = Object.fromEntries((sums ?? []).map((s) => [s.event_id, s.text]));
  return {
    health: health!, cameras: cameras ?? [], events: events ?? [], recommendations, feedback, notes, fetchedAt: Date.now(),
  };
}

/** Record the operator's decision on an alert. The latest one replaces the earlier. */
export async function postFeedback(eventId: string, action: FeedbackAction): Promise<void> {
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

export const snapshotUrl = (eventId: string) => `${API_BASE}/events/${encodeURIComponent(eventId)}/snapshot`;
