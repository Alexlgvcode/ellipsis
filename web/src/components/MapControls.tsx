import { Box, Camera, Check, Minus, Plus, RotateCcw, TrafficCone, TriangleAlert, Waypoints } from "lucide-react";

export interface Layers {
  incidents: boolean;
  traffic: boolean;
  cameras: boolean;
  signals: boolean;
}

const LAYERS: { key: keyof Layers; label: string; Icon: typeof Camera }[] = [
  { key: "incidents", label: "Incidents", Icon: TriangleAlert },
  { key: "traffic", label: "Traffic", Icon: Waypoints },
  { key: "cameras", label: "Cameras", Icon: Camera },
  { key: "signals", label: "Signals", Icon: TrafficCone },
];

export function MapLayerControls({ layers, onChange }: { layers: Layers; onChange: (l: Layers) => void }) {
  return (
    <div className="float layers" role="group" aria-label="Map layers">
      {LAYERS.map(({ key, label, Icon }) => (
        <button key={key} aria-pressed={layers[key]} onClick={() => onChange({ ...layers, [key]: !layers[key] })}>
          {layers[key] ? <Check size={14} /> : <Icon size={14} />}{label}
        </button>
      ))}
    </div>
  );
}

interface NavProps { is3d: boolean; zoomIn: () => void; zoomOut: () => void; toggle3d: () => void; reset: () => void }

export function MapNavigationControls({ is3d, zoomIn, zoomOut, toggle3d, reset }: NavProps) {
  return (
    <div className="float nav" role="group" aria-label="Map navigation">
      <button onClick={zoomIn} aria-label="Zoom in"><Plus size={16} /></button>
      <button onClick={zoomOut} aria-label="Zoom out"><Minus size={16} /></button>
      <button onClick={toggle3d} aria-pressed={is3d} aria-label="Toggle 3D">{is3d ? "3D" : <Box size={15} />}</button>
      <button onClick={reset} aria-label="Reset view"><RotateCcw size={15} /></button>
    </div>
  );
}
