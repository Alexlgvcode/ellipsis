import { useEffect, useState } from "react";
import { snapshotUrl } from "../api/client";
import { age, clock, nyTime } from "../lib/format";
import type { CameraView, Incident } from "../lib/incidents";

const REFRESH_MS = 5000;
const FRAME_W = 352;
const FRAME_H = 240;

type View = "live" | "alert";

/**
 * Source camera. NYC DOT cameras publish periodic stills, not video, so the live view says
 * "updated Ns ago" rather than claiming live video (§16). With an `incident`, "At alert" is
 * the frame the detector flagged, with a thin box on the vehicle only; without one (a camera
 * opened from the map) it's the live view alone.
 */
export function LiveCameraFeed({ camera: cam, incident, now }: { camera: CameraView; incident?: Incident; now: number }) {
  // The alert frame is the evidence to review; the live view is one click away.
  const first: View = incident?.hasSnapshot ? "alert" : "live";
  const [view, setView] = useState<View>(first);
  const [bucket, setBucket] = useState(() => Math.floor(Date.now() / REFRESH_MS));
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => { setView(first); setFailed(false); setLoadedAt(null); }, [incident?.id, cam.id, first]);
  useEffect(() => {
    const id = setInterval(() => setBucket(Math.floor(Date.now() / REFRESH_MS)), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const offline = cam.state === "offline" || failed || !cam.imageUrl;
  const liveSrc = cam.imageUrl ? `${cam.imageUrl}${cam.imageUrl.includes("?") ? "&" : "?"}t=${bucket}` : "";
  const src = view === "live" || !incident ? liveSrc : snapshotUrl(incident.id);

  return (
    <section className="sec" aria-label="Camera feed">
      <div className="inc-hd" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>{view === "live" ? "Live camera" : "At alert"}</h3>
        {incident && (
          <div className="seg" role="group" aria-label="Camera view">
            <button aria-pressed={view === "live"} onClick={() => setView("live")}>Live</button>
            <button aria-pressed={view === "alert"} onClick={() => setView("alert")}>At alert</button>
          </div>
        )}
      </div>
      <div className={`feed${view === "live" && offline ? " is-offline" : ""}`}>
        {src && (
          <img
            key={src}
            src={src}
            alt={view === "live"
              ? `Latest frame from ${cam.name}`
              : `Frame from ${cam.name} when the ${incident!.typeLabel.toLowerCase()} alert fired, vehicle outlined`}
            onLoad={() => { if (view === "live") { setLoadedAt(Date.now()); setFailed(false); } }}
            onError={() => { if (view === "live") setFailed(true); }}
          />
        )}
        {view === "alert" && incident && <AlertBox incident={incident} />}
      </div>
      <div className="feed-foot">
        {view === "live" ? (
          offline ? (
            <span><span className="offline-tag">{cam.code} OFFLINE</span>{loadedAt && <> · Last frame {nyTime(loadedAt, true)}</>}</span>
          ) : (
            <span>{cam.code} · Live camera · {loadedAt ? `updated ${age((now - loadedAt) / 1000)} ago` : "loading…"}</span>
          )
        ) : (
          <span>{cam.code} · Alert frame</span>
        )}
        <span>{nyTime(view === "live" || !incident ? (loadedAt ?? now) : incident.startedAt, true)}</span>
      </div>
    </section>
  );
}

/** The detector's box on the vehicle, with its type and duration. */
function AlertBox({ incident }: { incident: Incident }) {
  const [x1, y1, x2, y2] = incident.bbox;
  const tag = `${incident.typeLabel} · ${clock(incident.durationS)}`;
  return (
    <svg viewBox={`0 0 ${FRAME_W} ${FRAME_H}`} preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none" stroke="var(--incident)" strokeWidth="1.5" />
      <g transform={`translate(${Math.min(x1, FRAME_W - 110)} ${y1 > 18 ? y1 - 15 : y2 + 3})`}>
        <rect width={tag.length * 5.2 + 8} height="12" rx="2" fill="var(--incident)" />
        <text x="4" y="9" fontSize="8.5" fontFamily="Geist Mono, monospace" fill="#fff">{tag}</text>
      </g>
    </svg>
  );
}
