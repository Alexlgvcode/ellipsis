/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
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

export default defineConfig({
  plugins: [react(), maplibreWorker()],
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
