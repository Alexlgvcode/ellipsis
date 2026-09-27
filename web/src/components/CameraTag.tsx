import type { CameraView } from "../lib/incidents";
import type { FeedMode } from "./LiveCameraFeed";

/** LIVE only when the view really is the camera now; a replay or a recording says so. */
export function CameraTag({ camera, mode }: { camera: CameraView; mode: FeedMode }) {
  if (camera.state !== "live") return <span className="offline-tag">OFFLINE</span>;
  if (mode === "replay") return <span className="source-tag">REPLAY</span>;
  if (mode === "recorded") return <span className="source-tag">RECORDED</span>;
  return <span className="live"><i aria-hidden="true" />LIVE</span>;
}
