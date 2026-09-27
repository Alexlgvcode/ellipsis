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
