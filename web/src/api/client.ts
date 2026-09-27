import type { Camera, Event, Health, Recommendation } from "./types";

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
  fetchedAt: number;
}

export async function fetchSnapshot(): Promise<Snapshot> {
  const [health, cameras, events] = await Promise.all([
    get<Health>("/health"),
    get<Camera[]>("/cameras"),
    get<Event[]>("/events?limit=100"),
  ]);
  const recs = await Promise.all(
    (events ?? []).map((e) => get<Recommendation>(`/recommendations/${encodeURIComponent(e.id)}`, true)),
  );
  const recommendations: Record<string, Recommendation | null> = {};
  (events ?? []).forEach((e, i) => (recommendations[e.id] = recs[i]));
  return { health: health!, cameras: cameras ?? [], events: events ?? [], recommendations, fetchedAt: Date.now() };
}

export const snapshotUrl = (eventId: string) => `${API_BASE}/events/${encodeURIComponent(eventId)}/snapshot`;
