import type { Simulation } from "../lib/incidents";

export interface ChartPoint { t: number; default: number; recommended: number }

/** Same shape as signals/compare.py queue_chart, so the card matches the test. */
export function chartPoints(sim: Pick<Simulation, "queueBefore" | "queueAfter" | "seriesDefault" | "seriesNew">): ChartPoint[] {
  const left = sim.seriesDefault ?? [];
  const right = sim.seriesNew ?? [];
  if (left.length && right.length) {
    const n = Math.min(left.length, right.length);
    return Array.from({ length: n }, (_, i) => ({ t: i * 15, default: left[i], recommended: right[i] }));
  }
  return [
    { t: 0, default: 0, recommended: 0 },
    { t: 60, default: sim.queueBefore, recommended: sim.queueAfter },
    { t: 120, default: sim.queueBefore, recommended: sim.queueAfter },
  ];
}

export function savedLabel(saved: number): string {
  if (saved > 0.05) return `Recommended is faster by ${saved.toFixed(1)}s per vehicle`;
  if (saved < -0.05) return `Default is faster by ${Math.abs(saved).toFixed(1)}s per vehicle`;
  return "No delay difference";
}

/** Two queues on one clock. Default is the dashed line, recommended is solid. */
export function QueueChart({ sim }: { sim: Simulation }) {
  const points = chartPoints(sim);
  const w = 280;
  const h = 88;
  const pad = 8;
  const maxQ = Math.max(1, ...points.flatMap((p) => [p.default, p.recommended]));
  const maxT = Math.max(1, points[points.length - 1].t);
  const x = (t: number) => pad + (t / maxT) * (w - pad * 2);
  const y = (q: number) => h - pad - (q / maxQ) * (h - pad * 2);
  const path = (key: "default" | "recommended") => points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");

  return (
    <figure className="qchart" aria-label="Queue over time, default versus recommended">
      <svg viewBox={`0 0 ${w} ${h}`} role="img">
        <title>Queue over time, default versus recommended</title>
        <path d={path("default")} fill="none" stroke="var(--text-2)" strokeWidth="1.5" strokeDasharray="4 3" />
        <path d={path("recommended")} fill="none" stroke="var(--text)" strokeWidth="2" />
      </svg>
      <figcaption>
        <span><i className="swatch dash" /> Default · {Math.round(sim.queueBefore)} vehicles</span>
        <span><i className="swatch rec" /> Recommended · {Math.round(sim.queueAfter)} vehicles</span>
      </figcaption>
    </figure>
  );
}
