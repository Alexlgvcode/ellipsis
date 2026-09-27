import { ChevronRight, X } from "lucide-react";
import { useEffect } from "react";
import { LiveCameraFeed } from "./LiveCameraFeed";
import { QueueChart, savedLabel } from "./QueueChart";
import { clock, nyTime, pct } from "../lib/format";
import type { FeedbackAction } from "../api/types";
import {
  STATUS_LABEL, ZONE_LABEL, decisionLabel, elapsed, queueMeters, type FirstSeen, type Incident,
} from "../lib/incidents";

interface Props {
  incident: Incident;
  seen: FirstSeen;
  now: number;
  onClose: () => void;
  onOpenSimulation: () => void;
  onDecide: (action: FeedbackAction) => void;
  saving: boolean;
  decideError: string | null;
}

const DECISIONS: [FeedbackAction, string][] = [["accept", "Accept"], ["reject", "Reject"], ["false_positive", "False positive"]];

export function IncidentInspector({ incident: i, seen, now, onClose, onOpenSimulation, onDecide, saving, decideError }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const sim = i.response.sim;
  const t = elapsed(i, seen, now);

  return (
    <aside className={`float inspector sev-${i.status}`} aria-label={`Incident at ${i.location}`}>
      {/* 1. Incident */}
      <section className="sec">
        <div className="inc-hd">
          <span className="status-tag">{STATUS_LABEL[i.status]}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close incident"><X size={16} /></button>
        </div>
        <h2 className="inc-title">{i.title}</h2>
        <div className="inc-loc">{i.location}</div>
        <div className="inc-meta">
          <span className="big" aria-label="Elapsed">{clock(t)}</span>
          <span style={{ color: "var(--text-2)" }}>{pct(i.confidence)} conf.</span>
        </div>
        {i.status === "needs_review" && (
          <p className="review-hint">Low confidence ({pct(i.confidence)}): check the frame before acting.</p>
        )}
        <div className="cam-line">
          <span>{i.camera.code}</span>
          {i.camera.state === "live"
            ? <span className="live"><i aria-hidden="true" />LIVE</span>
            : <span className="offline-tag">OFFLINE</span>}
        </div>
      </section>

      {i.note && (
        <section className="sec" aria-label="Incident note">
          <h3>Incident note</h3>
          <p className="note">{i.note}</p>
          <p className="note-src">AI-written (Gemini) from the detection and simulation data only</p>
        </section>
      )}

      {/* 2. Live camera feed */}
      <LiveCameraFeed camera={i.camera} incident={i} now={now} />

      {/* 3. Traffic impact */}
      <section className="sec">
        <h3>Traffic impact</h3>
        {sim ? (
          <dl className="kv">
            <dt>delay per vehicle</dt><dd>{sim.baselineDelay.toFixed(1)}s</dd>
            <dt>queue estimate</dt><dd>{sim.queueBefore} vehicles</dd>
            <dt>queue length</dt><dd>≈{Math.round(queueMeters(sim.queueBefore))} m</dd>
          </dl>
        ) : (
          <p style={{ margin: 0, color: "var(--text-2)" }}>
            {i.response.state === "running" ? "Estimating from the scenario run…" : "Not estimated for this incident yet."}
          </p>
        )}
      </section>

      {/* 4. Recommended response */}
      <section className="sec">
        <h3>Recommended response</h3>
        <div>Signal timing simulation</div>
        {sim ? (
          <>
            <p className={sim.savedPerVehicle > 0.05 ? "verdict good" : "verdict"}>{savedLabel(sim.savedPerVehicle)}</p>
            <QueueChart sim={sim} />
            <dl className="kv" style={{ marginTop: 10 }}>
              <dt>Current</dt><dd>{sim.baselineDelay.toFixed(1)}s</dd>
              <dt>Proposed</dt><dd>{sim.recommendedDelay.toFixed(1)}s</dd>
            </dl>
            <button className="cta" onClick={onOpenSimulation}>Open simulation <ChevronRight size={16} /></button>
          </>
        ) : i.response.state === "running" ? (
          <button className="cta" onClick={onOpenSimulation}>Scenario running… <ChevronRight size={16} /></button>
        ) : (
          <p style={{ margin: "6px 0 0", color: "var(--text-2)" }}>No signal response calculated yet.</p>
        )}
      </section>

      {/* 5. Detection details */}
      <details className="sec">
        <summary>Detection details <ChevronRight size={16} aria-hidden="true" /></summary>
        <dl className="kv">
          <dt>stationary duration</dt><dd>{Math.round(i.durationS)}s</dd>
          <dt>lane zone</dt><dd>{ZONE_LABEL[i.laneZone]}</dd>
          <dt>in travel lane</dt><dd>{["travel", "curb_adjacent", "box"].includes(i.laneZone) ? "yes" : "no"}</dd>
          <dt>threshold</dt><dd>{i.thresholdS}s</dd>
          <dt>confidence</dt><dd>{i.confidence.toFixed(2)}</dd>
          <dt>box (px)</dt><dd>{i.bbox.map((v) => Math.round(v)).join(", ")}</dd>
        </dl>
      </details>

      {/* 6. Timeline */}
      <details className="sec">
        <summary>Timeline <ChevronRight size={16} aria-hidden="true" /></summary>
        <ol className="timeline">
          <li><span className="mono">{nyTime(i.startedAt, true)}</span><span>Vehicle stopped</span></li>
          <li><span className="mono">{nyTime(Date.parse(i.startedAt) + i.thresholdS * 1000, true)}</span><span>Passed {i.thresholdS}s threshold, incident opened</span></li>
          {i.response.state !== "none" && <li><span className="mono">—</span><span>Signal scenario {i.response.state === "done" ? "calculated" : "running"}</span></li>}
          {i.decision && <li><span className="mono">—</span><span>Operator: {decisionLabel(i.decision, i.response.state !== "none")}</span></li>}
          <li><span className="mono">{nyTime(now, true)}</span><span>{i.status === "resolved" ? "Resolved" : "Still stopped"}</span></li>
        </ol>
      </details>
      {/* Operator decision: pinned to the bottom of the card, always in reach */}
      <section className="sec decide-bar" aria-label="Operator decision">
        <div className="decide-hd">
          <h3>Operator decision</h3>
          {i.decision
            ? <p className={`decision ${i.decision}`} role="status">{decisionLabel(i.decision, i.response.state !== "none")}</p>
            : <p className="decision" role="status">No decision yet</p>}
        </div>
        <div className="decide" role="group" aria-label="Decide on this alert">
          {DECISIONS.map(([action, label]) => (
            <button key={action} aria-pressed={i.decision === action} disabled={saving} onClick={() => onDecide(action)}>
              {label}
            </button>
          ))}
        </div>
        {decideError && <p className="decide-err" role="alert">{decideError}</p>}
        {i.response.state !== "none" && (
          <button className="to-sim" onClick={onOpenSimulation}>
            Compare in simulation <ChevronRight size={15} aria-hidden="true" />
          </button>
        )}
      </section>

    </aside>
  );
}
