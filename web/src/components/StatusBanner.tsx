import { nyTime } from "../lib/format";

/** Thin, non-blocking disconnect banner (§34). */
export function StatusBanner({ lastOkAt }: { lastOkAt: number | null }) {
  return (
    <div className="banner" role="status">
      {lastOkAt
        ? <>Connection lost. Showing last known state from <span className="mono">{nyTime(lastOkAt, true)}</span>.</>
        : <>Can't reach the ellipsis API. Retrying…</>}
    </div>
  );
}

/** The public site plays a recording when the live backend can't be reached; say so. */
export function RecordingBanner() {
  return (
    <div className="banner info" role="status">
      The live feed isn't reachable right now, so this is a recording run through the same pipeline.
    </div>
  );
}
