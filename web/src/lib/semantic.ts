import type { IncidentStatus } from "./incidents";
import { HEAVY_QUEUE, MODERATE_QUEUE } from "./scenario";

/** Semantic colours (spec §4.3, §13). Identical in every palette: they carry meaning. */
export const STATUS_COLOR: Record<IncidentStatus, string> = {
  needs_review: "#C88A22", confirmed: "#E7644C", critical: "#C9473D", resolved: "#2F8F62",
};
export const HEALTHY = "#2F8F62";
export const ROAD = { moderate: "#D2A14C", heavy: "#D96A4B", severe: "#C9473D" };
export const roadColor = (vehicles: number) =>
  vehicles >= HEAVY_QUEUE ? ROAD.severe : vehicles >= MODERATE_QUEUE ? ROAD.heavy : ROAD.moderate;
