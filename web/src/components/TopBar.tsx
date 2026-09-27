import { Volume2, VolumeX } from "lucide-react";
import { BrandMark } from "./BrandMark";
import { nyTime } from "../lib/format";

export type FeedState = "live" | "replay" | "sample" | "offline";

interface Props {
  openIncidents: number;
  camerasOnline: number;
  camerasTotal: number;
  feed: FeedState;
  now: number;
  sound: boolean;
  onSound: (on: boolean) => void;
}

const FEED_TEXT: Record<FeedState, string> = { live: "LIVE", replay: "REPLAY", sample: "SAMPLE DATA", offline: "OFFLINE" };

/** Brand left, geography centred and quiet, operational state compact on the right. */
export function TopBar({ openIncidents, camerasOnline, camerasTotal, feed, now, sound, onSound }: Props) {
  const health = camerasTotal ? camerasOnline / camerasTotal : 1;
  return (
    <header className="topbar">
      <BrandMark />
      <nav className="breadcrumb" aria-label="Geography">
        <span className="optional">New York City</span><span className="sep optional">/</span>
        <span className="optional">Manhattan</span><span className="sep optional">/</span>
        <span aria-current="location">Midtown</span>
      </nav>
      <div className="health">
        <span className="count-inc"><span className="mono">{openIncidents}</span> {openIncidents === 1 ? "incident" : "incidents"}</span>
        <span className={`optional${health < 0.95 ? " is-amber" : ""}`}>
          <span className="mono">{Math.round(health * 1000) / 10}%</span> cameras
        </span>
        <span className={`state ${feed}`} role="status" aria-live="polite">{FEED_TEXT[feed]} <i aria-hidden="true" /></span>
        <button className="icon-btn" aria-pressed={sound} onClick={() => onSound(!sound)}
          aria-label={sound ? "Spoken alerts on" : "Spoken alerts off"} title="Spoken alerts for new incidents">
          {sound ? <Volume2 size={16} /> : <VolumeX size={16} />}
        </button>
        <span className="mono" aria-label="New York time">{nyTime(now)}</span>
      </div>
    </header>
  );
}
