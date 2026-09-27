import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { currentSource, fetchSnapshot, liveUnreachable, postFeedback, voiceUrl } from "./api/client";
import type { FeedbackAction } from "./api/types";
import { BrandLoader } from "./components/BrandMark";
import { CameraInspector } from "./components/CameraInspector";
import { IncidentInspector } from "./components/IncidentInspector";
import type { FeedMode } from "./components/LiveCameraFeed";
import { IncidentRail } from "./components/IncidentRail";
import type { Layers } from "./components/MapControls";
import { MapShell, type SimOverlay } from "./components/MapShell";
import { SimulationMode } from "./components/SimulationMode";
import { RecordingBanner, StatusBanner } from "./components/StatusBanner";
import { TopBar, type FeedState } from "./components/TopBar";
import { useNow } from "./hooks/useNow";
import { usePolling } from "./hooks/usePolling";
import { heatStretches } from "./lib/heat";
import { cameraView, counts, toIncidents, type FirstSeen, type RailFilter, type RailSort } from "./lib/incidents";
import { DEFAULT_PALETTE, applyTheme, themeOf } from "./lib/palettes";

const THEME = themeOf(DEFAULT_PALETTE);

export const POLL_MS = 2500;
const RAIL_W = 288;
const INSPECTOR_W = 380;

export default function App() {
  const poll = usePolling(fetchSnapshot, POLL_MS);
  const now = useNow(1000);
  const [selectedId, setSelectedIdState] = useState<string | null>(null);
  const [cameraId, setCameraId] = useState<string | null>(null); // a camera opened from the map
  // one panel at a time: opening an incident closes the camera, and the other way round
  const setSelectedId = useCallback((id: string | null) => { setSelectedIdState(id); if (id) setCameraId(null); }, []);
  const openCamera = useCallback((id: string) => { setCameraId(id); setSelectedIdState(null); }, []);
  const [simId, setSimId] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<SimOverlay | null>(null);
  const [filter, setFilter] = useState<RailFilter>("all");
  const [sort, setSort] = useState<RailSort>("severity");
  const [collapsed, setCollapsed] = useState(() => typeof window !== "undefined" && window.innerWidth < 1100);
  const [layers, setLayers] = useState<Layers>({ incidents: true, traffic: true, cameras: true, signals: false });
  const [, setRetry] = useState(0);
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);
  // decisions saved from this browser, shown before the next poll picks them up
  const [decided, setDecided] = useState<Record<string, FeedbackAction>>({});
  const [saving, setSaving] = useState(false);
  const [decideError, setDecideError] = useState<{ id: string; msg: string } | null>(null);
  // Spoken alerts (ElevenLabs): off until the viewer turns them on (browsers block autoplay).
  const [sound, setSound] = useState(false);
  const announced = useRef<Set<string> | null>(null);
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
  // Sample data is a snapshot of stops that already ended: their clocks don't count up.
  if (!mock) for (const i of incidents) seenRef.current[i.id] ??= { durationS: i.durationS, atMs: snap!.fetchedAt };
  const seen = seenRef.current;
  const selected = incidents.find((i) => i.id === selectedId) ?? null;
  const cameraRow = snap?.cameras.find((c) => c.id === cameraId);
  const openCam = cameraRow && !selected ? cameraView(cameraRow) : null;
  const simIncident = incidents.find((i) => i.id === simId) ?? null;
  const onOverlay = useCallback((o: SimOverlay | null) => setOverlay(o), []);
  useEffect(() => {
    if (!sound) { announced.current = null; return; }
    const open = incidents.filter((i) => i.status !== "resolved").map((i) => i.id);
    if (!announced.current) { announced.current = new Set(open); return; }  // no backlog on switch-on
    const fresh = open.filter((id) => !announced.current!.has(id));
    fresh.forEach((id) => announced.current!.add(id));
    (async () => {
      for (const id of fresh) {
        const url = await voiceUrl(id);
        if (!url) continue;
        await new Audio(url).play().catch(() => undefined);   // no key or no file: stay silent
      }
    })();
  }, [incidents, sound]);
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

  if (!snap && !poll.error) return <BrandLoader fullscreen text="Loading traffic state…" />;

  const offline = Boolean(poll.error);
  // the public site tried the live backend and is playing the recording instead
  const recording = !offline && liveUnreachable;
  // Sample data is a recording whose frames the live feed can't match; a synced replay shows
  // each camera's recorded stills for the same moment; live mode shows the real feeds.
  const feedMode: FeedMode = mock ? "recorded"
    : snap?.health.source === "replay" ? (snap.health.synced ? "replay" : "recorded") : "live";
  // Resolved incidents leave the map (the one open in the card stays until it's closed).
  const onMap = incidents.filter((i) => i.status !== "resolved" || i.id === selectedId);
  const feed: FeedState = offline ? "offline" : mock ? "sample" : snap?.health.source === "replay" ? "replay" : "live";
  const cams = snap?.cameras ?? [];
  const railW = simIncident ? 0 : collapsed ? 48 : RAIL_W;
  const narrow = typeof window !== "undefined" && window.innerWidth < 1100;

  return (
    <div className={`app${offline || recording ? " has-banner" : ""}${collapsed ? " rail-collapsed" : ""}${(selected || openCam) && !simIncident ? " has-inspector" : ""}`}>
      <a className="skip-link" href="#incidents">Skip to incidents</a>
      <TopBar openIncidents={counts(incidents).open} camerasOnline={cams.filter((c) => c.is_online).length}
        camerasTotal={cams.length} feed={feed} now={now} sound={sound} onSound={setSound} />
      {offline && <StatusBanner lastOkAt={poll.lastOkAt} />}
      {recording && <RecordingBanner />}

      <MapShell
        incidents={onMap} cameras={cams} selectedId={selectedId} onSelect={setSelectedId}
        layers={layers} onLayers={setLayers} sim={simIncident ? overlay : null}
        insetLeft={narrow ? 0 : simIncident ? 400 : railW} insetRight={(selected || openCam) && !simIncident && !narrow ? INSPECTOR_W + 24 : 0}
        insetBottom={narrow && (selected || openCam) && !simIncident ? window.innerHeight * 0.5 : 0}
        selectedCameraId={openCam?.id ?? null} onSelectCamera={openCamera}
        colors={theme.map} onAnchor={setAnchor} heat={heat}
      />

      {!simIncident && (
        <IncidentRail incidents={incidents} selectedId={selectedId} onSelect={setSelectedId}
          filter={filter} onFilter={setFilter} sort={sort} onSort={setSort}
          collapsed={collapsed} onCollapse={setCollapsed} seen={seen} now={now}
          replayHref={currentSource() === "hosted" ? "?replay" : undefined} />
      )}

      {selected && !simIncident && (
        <IncidentInspector incident={selected} seen={seen} now={now} feedMode={feedMode}
          onClose={() => setSelectedId(null)} onOpenSimulation={() => setSimId(selected.id)}
          onDecide={(a) => onDecide(selected.id, a)} saving={saving}
          decideError={decideError?.id === selected.id ? decideError.msg : null} />
      )}

      {openCam && !simIncident && (
        <CameraInspector camera={openCam} now={now} onClose={() => setCameraId(null)} feedMode={feedMode} />
      )}

      {simIncident && (
        <SimulationMode incident={simIncident} anchor={anchor} colors={theme.map} onOverlay={onOverlay}
          onClose={() => setSimId(null)} onRetry={() => setRetry((n) => n + 1)} />
      )}
    </div>
  );
}
