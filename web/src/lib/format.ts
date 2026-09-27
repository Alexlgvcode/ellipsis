const NY = "America/New_York";

/** 255 -> "04:15"; 3720 -> "62:00". */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** New York wall-clock time, e.g. "18:24" or "18:24:05". */
export function nyTime(ts: number | string | Date, withSeconds = false): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: NY, hour: "2-digit", minute: "2-digit", second: withSeconds ? "2-digit" : undefined,
    hourCycle: "h23",
  }).format(new Date(ts));
}

/** "2s old", "1 min old". */
export function age(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)} min`;
}

export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const secs = (x: number) => `${x.toFixed(1)}s`;
