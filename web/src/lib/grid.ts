/**
 * Midtown street grid, fitted to the camera coordinates in data/cameras.json.
 *
 * ax is the avenue index (9 Av = -1, 8 Av = 0, 7 Av = 1, 6 Av = 2, 5 Av = 3), st the street
 * number. Each avenue is a straight line; fit residual is ~14 m. Used to place queues and
 * changed signals, never to position cameras (those use their real lat/lon).
 */

export type LngLat = [number, number];

const AVENUE_ORIGIN: Record<number, [number, number]> = {
  [-1]: [40.7317778334, -74.0118281906],
  0: [40.7305738724, -74.0090136832],
  1: [40.7292880592, -74.0061618786],
  2: [40.7281928193, -74.0033235649],
  3: [40.7270975794, -74.0004852512], // extrapolated one avenue east of 6 Av
};
const PER_STREET: [number, number] = [0.0006355586625, 0.000457569851]; // lat, lon per street
export const METERS_PER_STREET = 80.4;

/** Direction traffic flows on each avenue, in streets: +1 uptown, -1 downtown. */
const FLOW: Record<number, 1 | -1> = { [-1]: -1, 0: 1, 1: -1, 2: 1, 3: -1 };
const BROADWAY_FLOW = -1;

/** Broadway's avenue index as a function of street (it runs diagonally through Herald Sq). */
export const broadwayAx = (st: number) => 1.99 - (st - 33.43) * 0.087;

export function toLngLat(ax: number, st: number): LngLat {
  const lo = Math.max(-1, Math.min(2, Math.floor(ax)));
  const t = ax - lo;
  const a = AVENUE_ORIGIN[lo];
  const b = AVENUE_ORIGIN[lo + 1];
  const lat = a[0] + (b[0] - a[0]) * t + st * PER_STREET[0];
  const lon = a[1] + (b[1] - a[1]) * t + st * PER_STREET[1];
  return [lon, lat];
}

export interface GridPos {
  ax: number;
  st: number;
  avenue: string;
  flow: 1 | -1;
}

const AVE = /(\d+)(?:st|nd|rd|th)?\s+Ave/i;
const ST = /@\s*(?:W\s*)?(\d+)(?:st|nd|rd|th)?\s+St/i;

/** "8th Ave @ 33rd St" -> { ax: 0, st: 33 }. Cross-street-only cameras return null. */
export function parseCameraName(name: string): GridPos | null {
  const st = ST.exec(name);
  if (/^Broadway/i.test(name)) {
    const n = st ? Number(st[1]) : Number(/(\d+)\s*St/i.exec(name)?.[1]);
    if (!n) return null;
    return { ax: broadwayAx(n), st: n, avenue: "Broadway", flow: BROADWAY_FLOW };
  }
  const av = AVE.exec(name);
  if (!av || !st) return null;
  const ax = 8 - Number(av[1]);
  if (!(ax in FLOW)) return null;
  return { ax, st: Number(st[1]), avenue: `${av[1]} Av`, flow: FLOW[ax] };
}

/** "tls_8av_32st" -> { ax: 0, st: 32 }. */
export function parseSignalId(id: string): { ax: number; st: number; label: string } | null {
  const m = /(\d+)av_(\d+)st/i.exec(id);
  if (!m) return null;
  const ax = 8 - Number(m[1]);
  return { ax, st: Number(m[2]), label: `${m[1]} Ave @ ${m[2]} St` };
}

/**
 * Upstream road path for a queue of `meters` behind a blockage at (lngLat) on this avenue.
 * Traffic flows toward the blockage, so upstream is against the flow direction.
 */
export function queuePath(start: LngLat, pos: GridPos, meters: number, steps = 8): LngLat[] {
  const streets = meters / METERS_PER_STREET;
  const dir = -pos.flow;
  const path: LngLat[] = [];
  for (let i = 0; i <= steps; i++) {
    const k = (streets * i) / steps;
    const st = pos.st + dir * k;
    const ax = pos.avenue === "Broadway" ? broadwayAx(st) : pos.ax;
    const [lon, lat] = toLngLat(ax, st);
    const [lon0, lat0] = toLngLat(pos.ax, pos.st);
    path.push([start[0] + (lon - lon0), start[1] + (lat - lat0)]);
  }
  return path;
}

/** Point `meters` along a polyline (clamped). */
export function along(path: LngLat[], meters: number): LngLat {
  let left = meters;
  for (let i = 1; i < path.length; i++) {
    const seg = distance(path[i - 1], path[i]);
    if (left <= seg || i === path.length - 1) {
      const t = seg ? Math.min(1, left / seg) : 0;
      return [path[i - 1][0] + (path[i][0] - path[i - 1][0]) * t, path[i - 1][1] + (path[i][1] - path[i - 1][1]) * t];
    }
    left -= seg;
  }
  return path[0];
}

export function distance(a: LngLat, b: LngLat): number {
  const dLat = (b[1] - a[1]) * 111_000;
  const dLon = (b[0] - a[0]) * 111_000 * Math.cos((a[1] * Math.PI) / 180);
  return Math.hypot(dLat, dLon);
}

export const pathLength = (p: LngLat[]) => p.slice(1).reduce((s, q, i) => s + distance(p[i], q), 0);

/** Compass bearing (degrees clockwise from north) from a to b. */
export function bearing(a: LngLat, b: LngLat): number {
  const dx = (b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180);
  const dy = b[1] - a[1];
  return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
}

/** The polyline shifted sideways by `meters` (positive = right of the direction of travel). */
export function offsetPath(path: LngLat[], meters: number): LngLat[] {
  return path.map((p, i) => {
    const a = path[Math.max(0, i - 1)], b = path[Math.min(path.length - 1, i + 1)];
    const br = (bearing(a, b) + 90) * (Math.PI / 180);
    const dLat = (Math.cos(br) * meters) / 111_000;
    const dLon = (Math.sin(br) * meters) / (111_000 * Math.cos((p[1] * Math.PI) / 180));
    return [p[0] + dLon, p[1] + dLat];
  });
}
