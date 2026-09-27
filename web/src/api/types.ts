// Mirrors common/schemas.py (the wire contract). Change only with the whole team.

export type EventType = "double_parked" | "stopped_in_lane" | "blocked_box" | "frozen_feed";
export type LaneZone = "curb" | "curb_adjacent" | "travel" | "box" | "bus_stop" | "ignore" | "none";

export interface Camera {
  id: string;
  name: string;
  lat: number;
  lon: number;
  area?: string | null;
  image_url: string;
  is_online: boolean;
}

export interface Event {
  id: string;
  camera_id: string;
  type: EventType;
  start_ts: string;
  duration_s: number;
  bbox: [number, number, number, number];
  lane_zone: LaneZone;
  confidence: number;
  snapshot_path?: string | null;
}

export interface SignalChange {
  id: string;
  phase: number;
  change_s: number;
}

export interface SimResult {
  delay_default: number;
  delay_new: number;
  queue_default: number;
  queue_new: number;
  queue_series_default?: number[];
  queue_series_new?: number[];
}

export interface Recommendation {
  event_id: string;
  intersections: SignalChange[];
  sim: SimResult | null;
}

export interface Health {
  status: string;
  mock_mode?: boolean;
}
