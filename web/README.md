# ellipsis web dashboard

React 19 + TypeScript + Vite, MapLibre GL for the 3D map, Geist and Lucide. See
[docs/dashboard.md](../docs/dashboard.md) for what it does and
[docs/dashboard-design-spec.md](../docs/dashboard-design-spec.md) for the design spec.

```bash
npm ci
LW_API_URL=http://localhost:8000 npm run dev   # :5173, /api is proxied to the FastAPI backend
npm test                                       # vitest (jsdom); the map itself is mocked
npm run typecheck
```

- `src/lib/`: pure data shaping (incidents, grid geometry, rules, formatting), unit tested
- `src/components/`: one file per spec component (`TopBar`, `IncidentRail`, `MapShell`, `IncidentInspector`, `SimulationMode`, …)
- `src/styles/tokens.css`: design tokens from the spec (§3–4, §8, §29)
