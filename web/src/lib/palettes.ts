/**
 * The ellipsis surface palette: Night Shift (fix brief §38, §59–61). Surfaces only; semantic
 * status colours live in semantic.ts / tokens.css. Everything not listed (subtle fills, muted
 * text, map labels) is derived, so no component hardcodes a surface colour.
 */

export interface Palette {
  name: string;
  canvas: string;
  panel: string;
  road: string;
  buildingTop: string;
  buildingSide: string;
  border: string;
  text: string;
  text2: string;
  park: string;
  water: string;
  raised?: string;
  dark?: boolean;
  /** Optional finer control (Night Shift depth hierarchy, fix brief §59–61). */
  map?: { background?: string; road2?: string; rail?: string; rail2?: string; distant?: string; lane?: string };
  ui?: { hover?: string; borderSubtle?: string; textMuted?: string };
}

export const PALETTES = {
  // Refined depth hierarchy (§59–61):
  // quiet city mass < brighter roads < semantic traffic < crisp charcoal panels.
  "night-shift": {
    name: "Night Shift", canvas: "#1C201E", panel: "#202322", road: "#323734", buildingTop: "#303531", buildingSide: "#252A27",
    border: "#3A3F3C", text: "#F2F4F1", text2: "#AEB5AF", park: "#26352D", water: "#24343A", raised: "#252927", dark: true,
    map: { background: "#171A18", road2: "#292E2B", rail: "#555B57", rail2: "#444A46", distant: "#242825", lane: "#69716B" },
    ui: { hover: "#2B302D", borderSubtle: "#303531", textMuted: "#7F8781" },
  },
} satisfies Record<string, Palette>;

export type PaletteId = keyof typeof PALETTES;
export const DEFAULT_PALETTE: PaletteId = "night-shift";
export const PALETTE_IDS = Object.keys(PALETTES) as PaletteId[];

// --- colour maths ---------------------------------------------------------------------

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const hex = (c: number[]) => `#${c.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("")}`.toUpperCase();

/** a blended toward b by t (0..1). */
export function mix(a: string, b: string, t: number): string {
  const x = rgb(a), y = rgb(b);
  return hex(x.map((v, i) => v + (y[i] - v) * t));
}

export function luminance(color: string): number {
  const [r, g, b] = rgb(color).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((m, n) => n - m);
  return (hi + 0.05) / (lo + 0.05);
}

/** Darken (light palettes) or lighten (dark) `fg` until it reaches `ratio` on `bg`. */
function ensure(fg: string, bg: string, ratio: number, dark: boolean): string {
  let c = fg;
  for (let i = 0; i < 20 && contrast(c, bg) < ratio; i++) c = mix(c, dark ? "#FFFFFF" : "#000000", 0.08);
  return c;
}

// --- derived tokens -------------------------------------------------------------------

export interface Theme {
  vars: Record<string, string>;
  map: {
    background: string; ground: string; road: string; road2: string; buildingTop: string; buildingSide: string; park: string; water: string;
    rail: string; rail2: string; railOpacity: number; lane: string; mass: string; light: string;
    label: string; minorLabel: string; halo: string; markerStroke: string; ring: string;
    carQueued: string; carMoving: string; cameraOff: string; signal: string;
  };
}

export function themeOf(id: PaletteId): Theme {
  const p: Palette = PALETTES[id];
  const dark = Boolean(p.dark);
  const raised = p.raised ?? "#FFFFFF";
  const subtle = p.ui?.hover ?? mix(p.panel, p.canvas, 0.6);
  const selectedFill = mix(p.panel, p.text, dark ? 0.1 : 0.06);
  const text2 = ensure(p.text2, selectedFill, 4.5, dark);
  const textMuted = ensure(p.ui?.textMuted ?? mix(p.text2, p.panel, 0.2), selectedFill, 4.5, dark);
  const vars: Record<string, string> = {
    "--canvas": p.canvas,
    "--panel": p.panel,
    "--raised": raised,
    "--subtle": subtle,
    "--border": p.border,
    "--border-strong": mix(p.border, p.text, 0.18),
    "--text": p.text,
    "--text-2": text2,
    "--text-muted": textMuted,
    "--text-disabled": mix(p.text2, p.panel, 0.5),
    "--text-inverse": p.panel,
    "--selected-fill": selectedFill,
    "--selected-border": mix(p.border, p.text, 0.35),
    "--connector": mix(p.border, p.text, 0.28),
    "--feed-bg": mix(p.canvas, p.text, 0.06),
    "--border-subtle": p.ui?.borderSubtle ?? mix(p.border, p.panel, 0.5),
    "--beam": dark ? "255, 255, 255" : "27, 29, 27",
  };
  if (dark) {
    // Same semantic hues, lifted so status text stays AA on dark surfaces.
    Object.assign(vars, {
      "--healthy-text": "#6CC49A", "--healthy-soft": "#1F3328", "--healthy-border": "#2F5A43",
      "--amber-text": "#E6B45A", "--amber-soft": "#3A2F1B", "--amber-border": "#6B5326",
      "--incident-text": "#F08A74", "--incident-soft": "#3D2520",
      "--critical-text": "#EE7A70", "--critical-soft": "#3B201E",
    });
  }
  return {
    vars,
    map: {
      background: p.map?.background ?? p.canvas, ground: p.canvas, road: p.road, road2: p.map?.road2 ?? mix(p.road, p.canvas, 0.5),
      rail: p.map?.rail ?? mix(p.text2, p.canvas, 0.55), rail2: p.map?.rail2 ?? mix(p.text2, p.canvas, 0.7), railOpacity: 0.3,
      lane: p.map?.lane ?? mix(p.text2, p.road, 0.45),
      // Extrusions are lit, so the rendered top reads lighter than its colour; quiet mass colour keeps roads brighter.
      mass: p.map?.distant ?? p.buildingTop,
      // On dark maps a white light lifts the city mass to road brightness; a dim light keeps it quiet.
      light: dark ? "#B3B8B4" : "#FFFFFF",
      buildingTop: p.buildingTop, buildingSide: p.buildingSide, park: p.park, water: p.water,
      label: ensure(mix(p.text2, p.canvas, 0.15), p.road, 3, dark),
      minorLabel: mix(p.text2, p.canvas, 0.4),
      halo: p.road, markerStroke: p.panel, ring: mix(p.border, p.text, 0.35),
      carQueued: p.text, carMoving: text2, cameraOff: mix(p.text2, p.canvas, 0.45), signal: text2,
    },
  };
}

/** Writes the palette's CSS variables onto the document root. */
export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement) {
  // Clear anything the previous palette set (e.g. Night Shift's semantic overrides).
  for (const k of (root.dataset.themeVars ?? "").split(",").filter(Boolean)) {
    if (!(k in theme.vars)) root.style.removeProperty(k);
  }
  for (const [k, v] of Object.entries(theme.vars)) root.style.setProperty(k, v);
  root.dataset.themeVars = Object.keys(theme.vars).join(",");
  root.style.colorScheme = luminance(theme.vars["--canvas"]) < 0.2 ? "dark" : "light";
}
