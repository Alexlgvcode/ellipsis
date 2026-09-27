import { useEffect, useRef } from "react";
import type { Theme } from "../lib/palettes";
import { STATUS_COLOR } from "../lib/semantic";
import { CAR_COLOR, carState, type InsetScene } from "../lib/traffic";

/**
 * Close-up of the treated intersection from a fixed side-angle camera (fix brief §43, §53).
 * Base and Sim render the same geometry and camera; only the scene (queue, slowdown, green
 * time) differs. Illustrative: scaled from the simulated queues, not a replay of SUMO.
 */

const W_CSS = 248;
const H_CSS = 138;
const LANE = 3.5;
const LANES = 3;
const ROAD_W = LANE * LANES;          // avenue, x ∈ [0, ROAD_W], traffic travels +z
const STREET = [0, 12] as const;      // cross street, z range
const Z_MIN = -72, Z_MAX = 52;
const V_FREE = 11;                    // m/s
const TIME_SCALE = 4;                 // 90 s cycle plays in ~22 s
const CAR_L = 4.4, CAR_W = 1.9, CAR_H = 1.4;

type Pt = [number, number];
interface Car { z: number; v: number }

const THETA = (50 * Math.PI) / 180;
const K = 4.1;
function project(x: number, z: number, y = 0): Pt {
  const cx = x - ROAD_W / 2, cz = z - 4;
  const u = cx * Math.cos(THETA) + cz * Math.sin(THETA);
  const w = -cx * Math.sin(THETA) + cz * Math.cos(THETA);
  return [W_CSS * 0.47 + u * K, H_CSS * 0.58 - w * K * 0.46 - y * K * 0.9];
}
const depth = (x: number, z: number) => -(x - ROAD_W / 2) * Math.sin(THETA) + (z - 4) * Math.cos(THETA);

function shade(hex: string, t: number): string {
  const n = parseInt(hex.slice(1), 16);
  const f = (c: number) => Math.round(c * (1 - t));
  return `rgb(${f(n >> 16)}, ${f((n >> 8) & 255)}, ${f(n & 255)})`;
}

function poly(ctx: CanvasRenderingContext2D, pts: Pt[], fill: string, stroke?: string) {
  ctx.beginPath();
  pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 0.6; ctx.stroke(); }
}

/** Box with its viewer-facing faces: top, the -z face and the +x face. */
function box(ctx: CanvasRenderingContext2D, x0: number, x1: number, z0: number, z1: number, h: number, top: string, front: string, side: string, edge?: string) {
  poly(ctx, [project(x0, z0, 0), project(x1, z0, 0), project(x1, z0, h), project(x0, z0, h)], front, edge);
  poly(ctx, [project(x1, z0, 0), project(x1, z1, 0), project(x1, z1, h), project(x1, z0, h)], side, edge);
  poly(ctx, [project(x0, z0, h), project(x1, z0, h), project(x1, z1, h), project(x0, z1, h)], top, edge);
}

function laneCenter(i: number) { return LANE * i + LANE / 2; }

interface Props {
  scene: InsetScene;
  colors: Theme["map"];
  running: boolean;
  label: string;
}

export function IntersectionView({ scene, colors, running, label }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const sceneRef = useRef(scene);
  sceneRef.current = scene;
  const colorsRef = useRef(colors);
  colorsRef.current = colors;

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext?.("2d");
    if (!canvas || !ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = W_CSS * dpr;
    canvas.height = H_CSS * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Deterministic arrivals so Base and Sim are directly comparable.
    let seed = 7;
    const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const blocked = sceneRef.current.blockage === "box" ? 1 : 2;
    const zBlock = sceneRef.current.blockage === "box" ? 6 : 27;
    const moving = [0, 1, 2].filter((l) => l !== blocked);
    const lanes: Record<number, Car[]> = { 0: [], 1: [], 2: [] };
    let t = 0;

    const phaseAt = (time: number) => {
      const { greenS, cycleS } = sceneRef.current;
      const p = time % cycleS;
      return p < greenS ? "green" : p < greenS + 3 ? "amber" : "red";
    };

    const step = (dt: number) => {
      t += dt;
      const s = sceneRef.current;
      const phase = phaseAt(t);
      for (const l of moving) {
        const cars = lanes[l];
        const near = Math.abs(l - blocked) === 1 ? 0.78 : 0.35; // adjacent lane slows most (merges)
        for (let i = 0; i < cars.length; i++) {
          const c = cars[i];
          let target = V_FREE;
          if (c.z > zBlock - 46 && c.z < zBlock + 6) target *= 1 - s.pressure * near;
          if (phase !== "green" && c.z < -1.5) target = Math.min(target, Math.max(0, (-1.5 - c.z - 1) * 1.1));
          const lead = cars[i - 1];
          if (lead) target = Math.min(target, Math.max(0, (lead.z - c.z - CAR_L - 1.6) * 1.4));
          c.v = target < c.v ? target : Math.min(target, c.v + 3 * dt);
          c.z += c.v * dt;
        }
        while (cars.length && cars[0].z > Z_MAX) cars.shift();
        const last = cars[cars.length - 1];
        if ((!last || last.z > Z_MIN + 11) && rand() < 0.42 * dt) cars.push({ z: Z_MIN, v: V_FREE * 0.8 });
      }
    };

    const draw = () => {
      const c = colorsRef.current;
      const s = sceneRef.current;
      ctx.clearRect(0, 0, W_CSS, H_CSS);
      ctx.fillStyle = c.ground;
      ctx.fillRect(0, 0, W_CSS, H_CSS);

      // Road surfaces: avenue and cross street, one step brighter than the city mass.
      poly(ctx, [project(-60, STREET[0]), project(70, STREET[0]), project(70, STREET[1]), project(-60, STREET[1])], c.road2);
      poly(ctx, [project(0, Z_MIN - 20), project(ROAD_W, Z_MIN - 20), project(ROAD_W, Z_MAX + 20), project(0, Z_MAX + 20)], c.road);

      // Lane markings (dashed), stop line.
      ctx.strokeStyle = c.lane;
      ctx.lineWidth = 0.8;
      ctx.setLineDash([3, 4]);
      for (const x of [LANE, LANE * 2]) {
        for (const [a, b] of [[Z_MIN - 20, -2], [STREET[1] + 1, Z_MAX + 20]] as const) {
          const p = project(x, a), q = project(x, b);
          ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
        }
      }
      ctx.setLineDash([]);
      ctx.lineWidth = 1.4;
      const sl0 = project(0, -1.2), sl1 = project(ROAD_W, -1.2);
      ctx.beginPath(); ctx.moveTo(sl0[0], sl0[1]); ctx.lineTo(sl1[0], sl1[1]); ctx.stroke();

      // Everything with height, far to near.
      type Item = { d: number; draw: () => void };
      const items: Item[] = [];
      const blocks: [number, number, number, number, number][] = [
        // Low, set back from the kerb: context only, so the lanes and cars stay readable.
        [-44, -5, 17, 60, 7], [ROAD_W + 5, 50, 17, 60, 8], [-44, -5, -90, -5, 6], [ROAD_W + 5, 50, -90, -5, 7],
      ];
      for (const [x0, x1, z0, z1, h] of blocks) {
        items.push({ d: depth(x1, z0) + 30, draw: () => box(ctx, x0, x1, z0, z1, h, c.mass, c.buildingSide, shade(c.buildingSide, 0.12)) });
      }
      const car = (lane: number, z: number, color: string, outline?: string) => {
        const x = laneCenter(lane) - CAR_W / 2;
        items.push({ d: depth(x + CAR_W, z), draw: () => box(ctx, x, x + CAR_W, z, z + CAR_L, CAR_H, color, shade(color, 0.28), shade(color, 0.42), outline) });
      };
      // The blocking vehicle (semantic incident colour) and the stopped queue behind it.
      car(blocked, zBlock, STATUS_COLOR.confirmed, "rgba(0,0,0,0.35)");
      for (let k = 0; k < s.queuedCars; k++) car(blocked, zBlock - (CAR_L + 2.2) * (k + 1), CAR_COLOR.stopped);
      for (const l of moving) for (const m of lanes[l]) car(l, m.z, CAR_COLOR[carState(m.v, V_FREE)]);

      // Signal head on the near corner.
      const phase = phaseAt(t);
      items.push({
        d: depth(ROAD_W + 1.5, -2) - 1,
        draw: () => {
          const base = project(ROAD_W + 1.5, -2, 0), topP = project(ROAD_W + 1.5, -2, 6);
          ctx.strokeStyle = c.lane; ctx.lineWidth = 1.2;
          ctx.beginPath(); ctx.moveTo(base[0], base[1]); ctx.lineTo(topP[0], topP[1]); ctx.stroke();
          ctx.fillStyle = "#101211";
          ctx.fillRect(topP[0] - 3, topP[1] - 9, 6, 11);
          ctx.fillStyle = phase === "green" ? CAR_COLOR.flowing : phase === "amber" ? CAR_COLOR.slowing : CAR_COLOR.stopped;
          ctx.beginPath(); ctx.arc(topP[0], phase === "red" ? topP[1] - 6 : phase === "amber" ? topP[1] - 3.5 : topP[1] - 1, 1.9, 0, Math.PI * 2); ctx.fill();
        },
      });
      items.sort((a, b) => b.d - a.d).forEach((i) => i.draw());
    };

    // Warm up so the view opens mid-cycle with traffic already present.
    for (let i = 0; i < 400; i++) step(0.1);
    draw();

    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!running || reduce) return;
    let raf = 0;
    let last = performance.now();
    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000) * TIME_SCALE;
      last = now;
      step(dt);
      draw();
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [running, scene.blockage]);

  return <canvas ref={ref} className="inset-canvas" style={{ width: W_CSS, height: H_CSS }} role="img" aria-label={label} />;
}
