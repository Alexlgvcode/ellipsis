import { X } from "lucide-react";
import { useEffect } from "react";
import type { CameraView } from "../lib/incidents";
import { CameraTag } from "./CameraTag";
import { LiveCameraFeed, type FeedMode } from "./LiveCameraFeed";

/** A camera opened from the map: the incident panel's frame with just the live feed. */
export function CameraInspector({ camera, now, onClose, feedMode = "live" }: {
  camera: CameraView; now: number; onClose: () => void; feedMode?: FeedMode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="float inspector" aria-label={`Camera at ${camera.name}`}>
      <section className="sec">
        <div className="inc-hd">
          <h2 className="inc-title" style={{ margin: 0 }}>{camera.name}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close camera"><X size={16} /></button>
        </div>
        <div className="cam-line">
          <span>{camera.code}</span>
          <CameraTag camera={camera} mode={feedMode === "replay" ? "replay" : "live"} />
        </div>
      </section>
      <LiveCameraFeed camera={camera} now={now} mode={feedMode === "replay" ? "replay" : "live"} />
    </aside>
  );
}
