import type { EventType } from "../api/types";

/** Dwell thresholds, mirrored from events/rules.yaml (a test keeps them in sync). */
export const DWELL_S: Record<EventType, number> = {
  double_parked: 60,
  stopped_in_lane: 75,
  blocked_box: 30,
  frozen_feed: 30,
};

/** An event not updated for this long is treated as resolved (live and replay modes). */
export const ACTIVE_WINDOW_S = 300;

/** Below this confidence an incident is shown as "Needs review". */
export const REVIEW_BELOW = 0.75;

/** At or above this many times its dwell threshold, a confirmed incident is "Critical". */
export const CRITICAL_RATIO = 5;

/** Metres of road one queued vehicle occupies (car length plus gap). */
export const METERS_PER_VEHICLE = 7.5;
