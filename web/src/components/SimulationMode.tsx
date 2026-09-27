import { ArrowLeft } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { BrandLoader } from "./BrandMark";
import { IntersectionView } from "./IntersectionView";
import type { SimOverlay } from "./MapShell";
import { parseCameraName, parseSignalId, toLngLat } from "../lib/grid";
import type { Incident } from "../lib/incidents";
import type { Theme } from "../lib/palettes";
import { fmtDelta, timingChange } from "../lib/scenario";
import { CAR_COLOR, flowWord, insetScene, type CarState } from "../lib/traffic";

type Stage = "loading" | "baseline" | "change" | "respond" | "settled";
export type Plan = "baseline" | "recommended";

/** Demo pacing (spec §26): loader, baseline, change, response, result. */
export const PACING: [Stage, number][] = [["loading", 0], ["baseline", 1200], ["change", 4000], ["respond", 6000], ["settled", 10000]];
/** Projection reveal (fix brief §52): beams extend, then the close-ups resolve. */
export const BEAM_MS = 550;
export const INSET_MS = 250;

const STAGE_TEXT: Record<Stage, string> = {
  loading: "Running scenario…",
  baseline: "Main map: baseline signal timing",
  change: "Main map: signal timing update applied",
  respond: "Main map: traffic responding",
  settled: "Result",
};

interface Props {
  incident: Incident;
  anchor: { x: number; y: number } | null;
  colors: Theme["map"];
  onClose: () => void;
  onOverlay: (o: SimOverlay | null) => void;
  onRetry: () => void;
}

interface Rect { left: number; right: number; bottom: number }

const reducedMotion = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

/**
 * Simulation comparison (fix brief §49–65). Three layers: the bird's-eye corridor map behind,
 * a Base-vs-Sim summary top-left, and paired Base / Sim close-ups top-right, projected from the
 * incident by two beams.
 */
export function SimulationMode({ incident, anchor, colors, onClose, onOverlay, onRetry }: Props) {
  const sim = incident.response.sim;
  const state = incident.response.state;
  const [stage, setStage] = useState<Stage>("loading");
  const [plan, setPlan] = useState<Plan>("baseline");
  const [beam, setBeam] = useState(0);          // 0..1 beam extension
  const [revealed, setRevealed] = useState(false);
  const baseRef = useRef<HTMLElement>(null);
  const simRef = useRef<HTMLElement>(null);
  const [targets, setTargets] = useState<Rect[] | null>(null);

  // Main-map timeline.
  useEffect(() => {
    if (state !== "done") { setStage("loading"); setPlan("baseline"); return; }
    const timers = PACING.map(([s, at]) => setTimeout(() => {
      setStage(s);
      if (s === "change") setPlan("recommended");
    }, at));
    return () => timers.forEach(clearTimeout);
  }, [incident.id, state]);

  // Projection reveal: once, when the scenario first leaves the loader.
  const started = stage !== "loading";
  useEffect(() => {
    if (!started) return;
    if (reducedMotion()) { setBeam(1); setRevealed(true); return; }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / BEAM_MS);
      setBeam(1 - (1 - p) ** 3); // ease-out
      if (p < 1) raf = requestAnimationFrame(tick);
      else setRevealed(true);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [started]);

  const changes = useMemo(() => incident.response.changes.map((c) => {
    const s = parseSignalId(c.id);
    return { ...timingChange(c), id: c.id, lngLat: s ? toLngLat(s.ax, s.st) : null };
  }), [incident.response.changes]);
  const main = changes[0];

  const applied = plan === "recommended" && (stage === "change" || stage === "respond" || stage === "settled");
  const target = !sim || stage === "loading" ? 0
    : plan === "baseline" || stage === "change" ? sim.queueBefore : sim.queueAfter;

  useEffect(() => {
    onOverlay(state === "none" ? null : {
      incident,
      targetVehicles: target,
      flowing: stage !== "loading",
      signals: changes.flatMap((c) => c.lngLat ? [{
        lngLat: c.lngLat,
        text: applied ? `Green ${c.before}s → ${c.after}s` : `Green ${c.before}s`,
        changed: applied,
      }] : []),
    });
  }, [incident, target, stage, applied, changes, state, onOverlay]);
  useEffect(() => () => onOverlay(null), [onOverlay]);

  // Beam targets: the bottom edge of each close-up.
  useLayoutEffect(() => {
    const measure = () => {
      const rs = [baseRef.current, simRef.current].map((el) => el?.getBoundingClientRect());
      setTargets(rs.every(Boolean) ? rs.map((r) => ({ left: r!.left, right: r!.right, bottom: r!.bottom })) : null);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [stage, state, revealed]);

  if (state === "none") {
    return (
      <>
        <div className="sim-top"><BackLink onClose={onClose} /></div>
        <section className="float sim-fail sec" role="alert">
          <h3>Simulation unavailable</h3>
          <p style={{ margin: "0 0 10px", color: "var(--text-2)" }}>Unable to calculate this scenario with the current traffic state.</p>
          <button className="cta" onClick={onRetry}>Retry</button>
        </section>
      </>
    );
  }

  const settled = stage === "settled";
  const pos = parseCameraName(incident.location);
  const direction = pos ? `${pos.flow === 1 ? "northbound" : "southbound"} flow on ${pos.avenue.replace(/ Av$/, " Ave")}` : "flow through the corridor";
  const blockage = incident.type === "blocked_box" ? "box" : "curb";
  const dash = "—";

  return (
    <>
      {stage === "loading" && (
        <BrandLoader text={state === "running" ? "Running scenario… waiting for the result" : "Running scenario…"} />
      )}

      <div className="sim-top">
        <BackLink onClose={onClose} />
        <span className="sim-title">Signal timing simulation · simulated</span>
      </div>

      {/* Top-left: the "so what" */}
      <aside className="float sim-summary" aria-label="Base versus sim summary">
        <div className="kicker">Base vs Sim</div>
        {sim && settled ? (
          <div className="settle" aria-live="polite">
            <div className="primary"><span className="mono">{sim.savedPerVehicle.toFixed(1)}s</span> saved per vehicle</div>
            <ul className="support">
              <li><b className="mono">{sim.improvementPct}%</b> lower average delay</li>
              <li><b className="mono">{sim.queueBefore - sim.queueAfter}</b> fewer queued vehicles</li>
              {sim.queueAfter < sim.queueBefore && <li className="interpret">Improved {direction}</li>}
            </ul>
          </div>
        ) : (
          <p className="pending" aria-live="polite">{STAGE_TEXT[stage]}</p>
        )}
        <div className="summary-foot">
          <span>Main map</span>
          <div className="seg" role="group" aria-label="Main map shows">
            {(["baseline", "recommended"] as Plan[]).map((p) => (
              <button key={p} aria-pressed={plan === p} disabled={!settled} onClick={() => setPlan(p)}>
                {p === "baseline" ? "Base" : "Sim"}
              </button>
            ))}
          </div>
        </div>
      </aside>

      {/* Projection beams from the incident to the two close-ups */}
      {targets && anchor && beam > 0 && (
        <svg className="beams" aria-hidden="true">
          <defs>
            <filter id="beam-feather" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="0.8" /></filter>
            {targets.map((t, i) => (
              <linearGradient key={i} id={`beam-${i}`} gradientUnits="userSpaceOnUse"
                x1={anchor.x} y1={anchor.y} x2={(t.left + t.right) / 2} y2={t.bottom}>
                <stop offset="0" style={{ stopColor: "rgb(var(--beam))", stopOpacity: 0.02 }} />
                <stop offset="1" style={{ stopColor: "rgb(var(--beam))", stopOpacity: 0.1 }} />
              </linearGradient>
            ))}
          </defs>
          {targets.map((t, i) => {
            const L = { x: anchor.x + (t.left + 14 - anchor.x) * beam, y: anchor.y + (t.bottom - anchor.y) * beam };
            const R = { x: anchor.x + (t.right - 14 - anchor.x) * beam, y: L.y };
            const a0 = { x: anchor.x - 2.5, y: anchor.y - 6 }, a1 = { x: anchor.x + 2.5, y: anchor.y - 6 };
            return (
              <g key={i}>
                <polygon points={`${a0.x},${a0.y} ${a1.x},${a1.y} ${R.x},${R.y} ${L.x},${L.y}`} fill={`url(#beam-${i})`} filter="url(#beam-feather)" />
                <line x1={a0.x} y1={a0.y} x2={L.x} y2={L.y} className="beam-edge" />
                <line x1={a1.x} y1={a1.y} x2={R.x} y2={R.y} className="beam-edge" />
              </g>
            );
          })}
        </svg>
      )}

      {/* Top-right: paired close-ups, same intersection, same camera */}
      <div className={`insets${revealed ? " is-revealed" : ""}`}>
        {(["base", "sim"] as const).map((which) => {
          const isBase = which === "base";
          const scene = sim && main ? insetScene(sim, isBase ? main.before : main.after, which, blockage) : null;
          const onMap = (plan === "baseline") === isBase;
          return (
            <section key={which} ref={isBase ? baseRef : simRef} className={`float inset${onMap ? " is-shown" : ""}`}
              aria-label={isBase ? "Base close-up" : "Sim close-up"}>
              <div className="inset-hd">
                <span className="kicker">{isBase ? "Base" : "Sim"}</span>
                <span className="inset-sub">{isBase ? "Current timing" : "Signal timing update"}</span>
              </div>
              {scene ? (
                <IntersectionView scene={scene} colors={colors} running={revealed}
                  label={`${isBase ? "Baseline" : "Recommended"} close-up of ${main!.signal}: ${scene.queuedCars} vehicles queued behind the blockage`} />
              ) : <div className="inset-canvas inset-empty" />}
              <div className="inset-where">{main?.signal ?? incident.location} · illustrative close-up</div>
              <dl className="kv">
                <dt>Average delay</dt>
                <dd className={!isBase && sim ? "good" : ""}>{sim ? `${(isBase ? sim.baselineDelay : sim.recommendedDelay).toFixed(1)}s` : dash}</dd>
                <dt>Queue</dt>
                <dd className={!isBase && sim ? "good" : ""}>{sim ? `${isBase ? sim.queueBefore : sim.queueAfter} vehicles` : dash}</dd>
                <dt>Green phase</dt>
                <dd>{main ? (isBase ? `${main.before}s` : <>{main.before}s → {main.after}s <span className="delta">{fmtDelta(main.delta)}</span></>) : dash}</dd>
                <dt>Flow</dt>
                <dd className={!isBase && sim && sim.queueAfter < sim.queueBefore ? "good" : ""}>{sim ? flowWord(sim, which) : dash}</dd>
              </dl>
            </section>
          );
        })}
        <div className="car-legend" aria-hidden="true">
          {(Object.keys(CAR_COLOR) as CarState[]).map((k) => <span key={k}><i style={{ background: CAR_COLOR[k] }} />{k}</span>)}
        </div>
      </div>

      <p className="visually-hidden" aria-live="polite">{STAGE_TEXT[stage]}</p>
    </>
  );
}

function BackLink({ onClose }: { onClose: () => void }) {
  return <button className="back-link" onClick={onClose}><ArrowLeft size={14} /> Back to incident</button>;
}
