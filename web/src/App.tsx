import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSnapshot, postFeedback } from "./api/client";
import type { FeedbackAction } from "./api/types";
import { BrandLoader } from "./components/BrandMark";
import { IncidentInspector } from "./components/IncidentInspector";
import { IncidentRail } from "./components/IncidentRail";
import type { Layers } from "./components/MapControls";
import { MapShell, type SimOverlay } from "./components/MapShell";
import { SimulationMode } from "./components/SimulationMode";
import { StatusBanner } from "./components/StatusBanner";
import { TopBar, type FeedState } from "./components/TopBar";
import { useNow } from "./hooks/useNow";
import { usePolling } from "./hooks/usePolling";
import { heatStretches } from "./lib/heat";
import { counts, toIncidents, type FirstSeen, type RailFilter, type RailSort } from "./lib/incidents";
import { DEFAULT_PALETTE, applyTheme, themeOf } from "./lib/palettes";

const THEME = themeOf(DEFAULT_PALETTE);

export const POLL_MS = 2500;
const RAIL_W = 288;
const INSPECTOR_W = 380;

export default function App() {
  const poll = usePolling(fetchSnapshot, POLL_MS);
  const now = useNow(1000);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [simId, setSimId] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<SimOverlay | null>(null);
  const [filter, setFilter] = useState<RailFilter>("all");
  const [sort, setSort] = useState<RailSort>("severity");
  const [collapsed, setCollapsed] = useState(() => typeof window !== "undefined" && window.innerWidth < 1100);
  const [layers, setLayers] = useState<Layers>({ incidents: true, traffic: true, cameras: false, signals: false });
  const [, setRetry] = useState(0);
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);
  // decisions saved from this browser, shown before the next poll picks them up
  const [decided, setDecided] = useState<Record<string, FeedbackAction>>({});
  const [saving, setSaving] = useState(false);
  const [decideError, setDecideError] = useState<{ id: string; msg: string } | null>(null);
  const theme = THEME;
  useEffect(() => { applyTheme(theme); }, [theme]);

  const snap = poll.data;
  const mock = Boolean(snap?.health.mock_mode);
  const incidents = useMemo(
    () => (snap ? toIncidents(snap.events, snap.cameras, snap.recommendations, snap.fetchedAt, mock,
      { ...snap.feedback, ...decided }, snap.notes) : []),
    [snap, mock, decided],
  );
  const heat = useMemo(
    () => (snap ? heatStretches(snap.congestion, snap.cameras, snap.fetchedAt, mock) : []),
    [snap, mock],
  );
  const seenRef = useRef<FirstSeen>({});
  for (const i of incidents) seenRef.current[i.id] ??= { durationS: i.durationS, atMs: snap!.fetchedAt };
  const seen = seenRef.current;
  const selected = incidents.find((i) => i.id === selectedId) ?? null;
  const simIncident = incidents.find((i) => i.id === simId) ?? null;
  const onOverlay = useCallback((o: SimOverlay | null) => setOverlay(o), []);
  const onDecide = useCallback(async (id: string, action: FeedbackAction) => {
    setSaving(true);
    setDecideError(null);
    try {
      await postFeedback(id, action);
      setDecided((d) => ({ ...d, [id]: action }));
    } catch {
      setDecideError({ id, msg: "Couldn't save the decision. Check the API connection and try again." });
    } finally {
      setSaving(false);
    }
  }, []);

  if (!snap && !poll.error) return <BrandLoader fullscreen text="Loading live traffic state…" />;

  const offline = Boolean(poll.error);
  const feed: FeedState = offline ? "offline" : mock ? "sample" : snap?.health.source === "replay" ? "replay" : "live";
  const cams = snap?.cameras ?? [];
  const railW = simIncident ? 0 : collapsed ? 48 : RAIL_W;
  const narrow = typeof window !== "undefined" && window.innerWidth < 1100;

  return (
    <div className={`app${offline ? " has-banner" : ""}${collapsed ? " rail-collapsed" : ""}${selected && !simIncident ? " has-inspector" : ""}`}>
      <a className="skip-link" href="#incidents">Skip to incidents</a>
      <TopBar openIncidents={counts(incidents).open} camerasOnline={cams.filter((c) => c.is_online).length}
        camerasTotal={cams.length} feed={feed} now={now} />
      {offline && <StatusBanner lastOkAt={poll.lastOkAt} />}

      <MapShell
        incidents={incidents} cameras={cams} selectedId={selectedId} onSelect={setSelectedId}
        layers={layers} onLayers={setLayers} sim={simIncident ? overlay : null}
        insetLeft={narrow ? 0 : simIncident ? 400 : railW} insetRight={selected && !simIncident && !narrow ? INSPECTOR_W + 24 : 0}
        insetBottom={narrow && selected && !simIncident ? window.innerHeight * 0.5 : 0}
        colors={theme.map} onAnchor={setAnchor} heat={heat}
      />

      {!simIncident && (
        <IncidentRail incidents={incidents} selectedId={selectedId} onSelect={setSelectedId}
          filter={filter} onFilter={setFilter} sort={sort} onSort={setSort}
          collapsed={collapsed} onCollapse={setCollapsed} seen={seen} now={now} />
      )}

      {selected && !simIncident && (
        <IncidentInspector incident={selected} seen={seen} now={now}
          onClose={() => setSelectedId(null)} onOpenSimulation={() => setSimId(selected.id)}
          onDecide={(a) => onDecide(selected.id, a)} saving={saving}
          decideError={decideError?.id === selected.id ? decideError.msg : null} />
      )}

      {simIncident && (
        <SimulationMode incident={simIncident} anchor={anchor} colors={theme.map} onOverlay={onOverlay}
          onClose={() => setSimId(null)} onRetry={() => setRetry((n) => n + 1)} />
      )}
    </div>
  );
}
