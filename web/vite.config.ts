/// <reference types="vitest/config" />
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/**
 * MapLibre's worker imports ./maplibre-gl-shared.mjs, which a `?url` import doesn't copy,
 * so a production build served the worker a 404 (index.html) and the map stayed blank.
 * Ship both files side by side; main.tsx points the worker at them in production.
 */
function maplibreWorker(): Plugin {
  const dist = resolve(__dirname, "node_modules/maplibre-gl/dist");
  return {
    name: "maplibre-worker",
    apply: "build",
    generateBundle() {
      for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
        this.emitFile({ type: "asset", fileName: `maplibre/${file}`, source: readFileSync(resolve(dist, file)) });
      }
    },
  };
}

// The FastAPI backend has no CORS, so the dev server proxies /api to it.
// LW_API_URL matches the variable the rest of the repo uses (default :8000).
const API = process.env.LW_API_URL ?? "http://localhost:8000";

/**
 * Demo builds (VITE_DEMO=1) also ship the API's mock data (data/mock/, built by
 * scripts/build_mock.py from real incidents) under demo/sample/, so the site shows the same
 * incidents as mock mode and follows every rebuild of it.
 */
function sampleData(): Plugin {
  const repo = resolve(__dirname, "..");
  const mock = resolve(repo, "data/mock");
  return {
    name: "demo-sample-data",
    apply: () => process.env.VITE_DEMO === "1",
    generateBundle() {
      const emit = (fileName: string, path: string) =>
        this.emitFile({ type: "asset", fileName: `demo/sample/${fileName}`, source: readFileSync(path) });
      for (const f of ["events.json", "recommendations.json", "congestion.json"]) emit(f, resolve(mock, f));
      emit("cameras.json", resolve(repo, "data/cameras.json"));
      for (const f of readdirSync(resolve(mock, "snapshots"))) emit(`snapshots/${f}`, resolve(mock, "snapshots", f));
    },
  };
}

export default defineConfig({
  plugins: [react(), maplibreWorker(), sampleData()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
