import type { SignalChangeView } from "./incidents";
import { parseSignalId } from "./grid";
// SUMO signal id -> intersection, generated from sim/network/tls_nodes.json (api/summarize.py signal_name)
import SIGNAL_NAMES_JSON from "./signal-names.json";

const SIGNAL_NAMES: Record<string, string> = SIGNAL_NAMES_JSON;

/**
 * Baseline green times from the modeled Midtown plan (sim/network/signal_plans.yaml,
 * program "lanewatch"): 90 s pre-timed cycle, 45 s avenue green and 28 s cross-street
 * green after the 7 s leading pedestrian interval. The API only carries the change
 * (`change_s`), so the "before" value is the modeled plan, not a live controller reading.
 */
export const CYCLE_S = 90;
export const AVENUE_GREEN_S = 45;
export const STREET_GREEN_S = 28;

/** Phase index -> approach. Mock ids use 0 = avenue, 2 = street; "lanewatch" uses 1 and 4. */
const STREET_PHASES = new Set([2, 3, 4, 5]);

export interface TimingChange {
  signal: string;       // "8 Ave @ 32 St"
  approach: "avenue" | "street";
  before: number;       // s
  after: number;        // s
  delta: number;        // s, signed
}

export function timingChange(ch: SignalChangeView): TimingChange {
  const approach = STREET_PHASES.has(ch.phase) ? "street" : "avenue";
  const before = approach === "street" ? STREET_GREEN_S : AVENUE_GREEN_S;
  return {
    signal: SIGNAL_NAMES[ch.id] ?? parseSignalId(ch.id)?.label ?? "Nearby signal",
    approach, before, after: Math.max(0, before + ch.changeS), delta: ch.changeS,
  };
}

export const fmtDelta = (s: number) => `${s > 0 ? "+" : "−"}${Math.abs(s)}s`;

/** Queue on the blocked approach, in words. Same thresholds as the road colouring. */
export type Pressure = "High" | "Moderate" | "Low";
export const HEAVY_QUEUE = 16;
export const MODERATE_QUEUE = 8;
export function queuePressure(vehicles: number): Pressure {
  return vehicles >= HEAVY_QUEUE ? "High" : vehicles >= MODERATE_QUEUE ? "Moderate" : "Low";
}
