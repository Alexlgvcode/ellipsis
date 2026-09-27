import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { DEFAULT_PALETTE, PALETTES, PALETTE_IDS, applyTheme, contrast, themeOf } from "./palettes";

describe.each(PALETTE_IDS)("palette %s", (id) => {
  const t = themeOf(id);
  const v = t.vars;

  it("keeps body, secondary and muted text AA on panels and selected rows", () => {
    for (const fg of [v["--text"], v["--text-2"], v["--text-muted"]]) {
      expect(contrast(fg, v["--panel"])).toBeGreaterThanOrEqual(4.5);
      expect(contrast(fg, v["--selected-fill"])).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("separates roads from ground, and building sides from tops", () => {
    const p = PALETTES[id];
    expect(p.road).not.toBe(p.canvas);
    expect(contrast(p.buildingTop, p.buildingSide)).toBeGreaterThan(1.1);
  });
});

it("applies the palette, including Night Shift's semantic overrides, to the root", () => {
  const root = document.createElement("div");
  applyTheme(themeOf(DEFAULT_PALETTE), root);
  expect(root.style.getPropertyValue("--canvas")).toBe("#1C201E");
  expect(root.style.getPropertyValue("--amber-text")).toBe("#E6B45A");
});

it("no stylesheet or component hardcodes a surface colour", () => {
  const read = (p: string) => readFileSync(resolve(__dirname, "..", p), "utf8");
  const css = read("styles/app.css");
  const surfaces = Object.values(PALETTES).flatMap((p) => [p.canvas, p.panel, p.road, p.buildingTop, p.border]).map((c) => c.toLowerCase());
  for (const c of surfaces) expect(css.toLowerCase()).not.toContain(c);
  for (const file of ["components/MapShell.tsx", "components/SimulationMode.tsx", "components/TopBar.tsx"]) {
    expect(read(file)).not.toMatch(/#[0-9A-F]{6}\b/i);
  }
});
