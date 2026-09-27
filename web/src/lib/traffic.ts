import type { Simulation } from "./incidents";
import { HEAVY_QUEUE, queuePressure } from "./scenario";

/** Vehicle state colours (fix brief §56). Semantic, identical in every palette. */
export const CAR_COLOR = { stopped: "#D85B5B", slowing: "#D8B24C", flowing: "#54B87A" } as const;
export type CarState = keyof typeof CAR_COLOR;

/** Speed as a fraction of free-flow speed -> state. */
export function carState(speed: number, freeFlow: number): CarState {
  const f = freeFlow > 0 ? speed / freeFlow : 0;
  return f < 0.15 ? "stopped" : f < 0.6 ? "slowing" : "flowing";
}

/** Most cars the close-up can show queued before it gets cluttered. */
export const INSET_MAX_QUEUE = 8;

export interface InsetScene {
  greenS: number;          // avenue green on the treated signal
  cycleS: number;
  queuedCars: number;      // cars stopped behind the blockage, scaled to the view
  pressure: number;        // 0..1, how much the blockage slows the passing lane
  blockage: "curb" | "box";
}

/**
 * Parameters for one close-up. Both close-ups share geometry and camera; only these change.
 * Queue and slowdown are scaled from the simulated queues so the pictures agree with the
 * numbers beneath them (the baseline fills the view, the recommended plan is proportional).
 */
export function insetScene(sim: Simulation, greenS: number, plan: "base" | "sim", blockage: InsetScene["blockage"]): InsetScene {
  const q = plan === "base" ? sim.queueBefore : sim.queueAfter;
  const scale = sim.queueBefore > 0 ? INSET_MAX_QUEUE / sim.queueBefore : 0;
  return {
    greenS, cycleS: 90, blockage,
    queuedCars: Math.max(1, Math.round(q * scale)),
    pressure: Math.min(1, q / HEAVY_QUEUE),
  };
}

/** Plain-language flow for the close-up stats. */
export function flowWord(sim: Simulation, plan: "base" | "sim"): string {
  if (plan === "sim") return sim.queueAfter < sim.queueBefore ? "Improved" : "Unchanged";
  return ({ High: "Congested", Moderate: "Slowed", Low: "Moderate" } as const)[queuePressure(sim.queueBefore)];
}
