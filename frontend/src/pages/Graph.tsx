import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useAppSettings } from "../contexts/SettingsContext";
import type { GraphData, GraphNode } from "../types";

type Mode = "full" | "papers";

interface VisSettings {
  nodeSize: number;
  maxNodeSize: number;
  linkDistance: number;
  charge: number;
  linkWidth: number;
  arrowSize: number;
  linkCurvature: number;
  gravity: number;
  showParticles: boolean;
  dashedLinks: boolean;
  showEdgeLabels: boolean;
  showNodeLabels: boolean;
  sizeByDegree: boolean;
  maxNodes: number;
  hiddenTypes: string[];
  nodeColors: Record<string, string>;
  bgColor: string;
}

const NODE_COLORS: Record<string, string> = {
  paper:   "#7c3aed",
  person:  "#2563eb",
  topic:   "#16a34a",
  tag:     "#d97706",
  project: "#db2777",
  note:    "#6b7280",
  unknown: "#9ca3af",
};

const DEFAULT_SETTINGS: VisSettings = {
  nodeSize: 16,
  maxNodeSize: 8,
  linkDistance: 120,
  charge: -200,
  linkWidth: 1.5,
  arrowSize: 6,
  linkCurvature: 0,
  gravity: 0.3,
  showParticles: false,
  dashedLinks: false,
  showEdgeLabels: true,
  showNodeLabels: true,
  sizeByDegree: true,
  maxNodes: 2000,
  hiddenTypes: [],
  nodeColors: { ...NODE_COLORS },
  bgColor: "#f9fafb",
};

function defaultQuery(mode: Mode, maxNodes: number): string {
  if (mode === "papers") {
    return `MATCH (n)\nWHERE n:Paper OR n:Person OR n:Project\nWITH n LIMIT ${maxNodes}\nOPTIONAL MATCH (n)-[r]-(m)\nWHERE m:Paper OR m:Person OR m:Topic OR m:Project\nRETURN n, r, m`;
  }
  return `MATCH (n)\nWITH n LIMIT ${maxNodes}\nOPTIONAL MATCH (n)-[r]->(m)\nRETURN n, r, m`;
}

const SKIP_PROPS = new Set(["x", "y", "vx", "vy", "fx", "fy", "__indexColor", "index"]);

// ── Small reusable UI pieces ──────────────────────────────────────────────────

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={`relative w-9 h-5 rounded-full transition-colors ${value ? "bg-violet-600" : "bg-gray-300"}`}
    >
      <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${value ? "translate-x-4" : "translate-x-0"}`} />
    </button>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="pt-2 pb-0.5 border-t border-gray-100 first:border-t-0 first:pt-0">
      <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">{children}</span>
    </div>
  );
}

function SliderRow({ label, value, min, max, step, onChange, format }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <label className="block">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{label}</span>
        <span className="font-mono text-gray-700">{format ? format(value) : value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(+e.target.value)}
        className="w-full accent-violet-600" />
    </label>
  );
}

function ToggleRow({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-gray-500">{label}</span>
      <Toggle value={value} onChange={onChange} />
    </div>
  );
}

// ── Node properties panel ─────────────────────────────────────────────────────

function NodePanel({ node, onClose, onNavigate, onDelete, nodeColors }: {
  node: GraphNode;
  onClose: () => void;
  onNavigate: () => void;
  onDelete: () => void;
  nodeColors: Record<string, string>;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const color = nodeColors[node.type] ?? NODE_COLORS.unknown;
  const entries = Object.entries(node).filter(
    ([k, v]) => !SKIP_PROPS.has(k) && k !== "label" && k !== "type" && v !== null && v !== undefined && v !== ""
  );

  return (
    <div className="w-72 shrink-0 bg-white border-l border-gray-200 flex flex-col overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
        <span className="w-3 h-3 rounded-full shrink-0" style={{ background: color }} />
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{node.type}</span>
        <button onClick={onClose} className="ml-auto text-gray-400 hover:text-gray-600 text-lg leading-none">×</button>
      </div>

      <div className="px-4 py-3 border-b border-gray-100">
        <p className="text-sm font-semibold text-gray-800 break-words">{node.label}</p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {entries.map(([k, v]) => (
          <div key={k}>
            <span className="block text-[10px] font-semibold uppercase tracking-wide text-gray-400">{k}</span>
            <span className="text-xs text-gray-700 break-words">{String(v)}</span>
          </div>
        ))}
        {entries.length === 0 && (
          <p className="text-xs text-gray-400">No additional properties.</p>
        )}
      </div>

      <div className="px-4 py-3 border-t border-gray-100 space-y-2">
        {node.type === "paper" && (
          <button
            onClick={onNavigate}
            className="w-full px-3 py-1.5 text-xs font-medium bg-violet-600 text-white rounded hover:bg-violet-700 transition-colors"
          >
            Open paper →
          </button>
        )}
        {!confirmDelete ? (
          <button
            onClick={() => setConfirmDelete(true)}
            className="w-full px-3 py-1.5 text-xs font-medium border border-red-200 text-red-500 rounded hover:bg-red-50 transition-colors"
          >
            Delete node
          </button>
        ) : (
          <div className="space-y-1.5">
            <p className="text-[11px] text-red-600 text-center">Delete this node and all its relationships?</p>
            <div className="flex gap-1.5">
              <button
                onClick={onDelete}
                className="flex-1 px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
              >
                Yes, delete
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="flex-1 px-3 py-1.5 text-xs font-medium border border-gray-200 text-gray-600 rounded hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Settings panel ────────────────────────────────────────────────────────────

function SettingsPanel({ settings, onChange, onClose }: {
  settings: VisSettings;
  onChange: (patch: Partial<VisSettings>) => void;
  onClose: () => void;
}) {
  const typeEntries = Object.entries(NODE_COLORS).filter(([k]) => k !== "unknown");

  return (
    <div className="absolute top-10 right-2 z-20 w-72 bg-white rounded-lg shadow-xl border border-gray-200 p-4 overflow-y-auto max-h-[90vh]">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Visualization</span>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-base leading-none">×</button>
      </div>

      <div className="space-y-3">

        {/* ── NODES ── */}
        <SectionLabel>Nodes</SectionLabel>
        <SliderRow label="Node size" value={settings.nodeSize} min={6} max={36} step={1}
          onChange={v => onChange({ nodeSize: v })} />
        <SliderRow label="Max node size (cap)" value={settings.maxNodeSize} min={2} max={20} step={1}
          onChange={v => onChange({ maxNodeSize: v })} />
        <ToggleRow label="Scale by connections" value={settings.sizeByDegree}
          onChange={v => onChange({ sizeByDegree: v })} />

        {/* ── LINKS ── */}
        <SectionLabel>Links</SectionLabel>
        <SliderRow label="Link distance" value={settings.linkDistance} min={30} max={400} step={10}
          onChange={v => onChange({ linkDistance: v })} />
        <SliderRow label="Repulsion" value={Math.abs(settings.charge)} min={30} max={600} step={10}
          onChange={v => onChange({ charge: -v })} />
        <SliderRow label="Link width" value={settings.linkWidth} min={0.5} max={6} step={0.5}
          onChange={v => onChange({ linkWidth: v })} />
        <SliderRow label="Arrow size" value={settings.arrowSize} min={0} max={14} step={1}
          onChange={v => onChange({ arrowSize: v })} />
        <SliderRow label="Curvature" value={settings.linkCurvature} min={0} max={0.5} step={0.05}
          onChange={v => onChange({ linkCurvature: v })} />
        <ToggleRow label="Animated particles" value={settings.showParticles}
          onChange={v => onChange({ showParticles: v })} />
        <ToggleRow label="Dashed edges" value={settings.dashedLinks}
          onChange={v => onChange({ dashedLinks: v })} />

        {/* ── LABELS ── */}
        <SectionLabel>Labels</SectionLabel>
        <ToggleRow label="Node labels" value={settings.showNodeLabels}
          onChange={v => onChange({ showNodeLabels: v })} />
        <ToggleRow label="Edge labels" value={settings.showEdgeLabels}
          onChange={v => onChange({ showEdgeLabels: v })} />

        {/* ── NODE TYPES ── */}
        <SectionLabel>Node types (click to hide)</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          {typeEntries.map(([type]) => {
            const hidden = settings.hiddenTypes.includes(type);
            const color = settings.nodeColors[type] ?? NODE_COLORS[type];
            return (
              <button
                key={type}
                onClick={() => {
                  const next = hidden
                    ? settings.hiddenTypes.filter(t => t !== type)
                    : [...settings.hiddenTypes, type];
                  onChange({ hiddenTypes: next });
                }}
                className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border transition-colors ${
                  hidden
                    ? "border-gray-200 text-gray-400 bg-gray-50 line-through opacity-60"
                    : "border-gray-200 text-gray-700 bg-white hover:bg-gray-50"
                }`}
              >
                <span
                  className="w-2 h-2 rounded-full inline-block shrink-0"
                  style={{ background: hidden ? "#d1d5db" : color }}
                />
                {type}
              </button>
            );
          })}
        </div>

        {/* ── COLORS ── */}
        <SectionLabel>Colors</SectionLabel>
        {typeEntries.map(([type]) => (
          <div key={type} className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: settings.nodeColors[type] ?? NODE_COLORS[type] }} />
              <span className="text-xs text-gray-500 capitalize">{type}</span>
            </div>
            <input
              type="color"
              value={settings.nodeColors[type] ?? NODE_COLORS[type]}
              onChange={e => onChange({ nodeColors: { ...settings.nodeColors, [type]: e.target.value } })}
              className="w-7 h-7 rounded cursor-pointer border border-gray-200 p-0.5"
              title={`${type} color`}
            />
          </div>
        ))}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">Background</span>
          <input
            type="color"
            value={settings.bgColor}
            onChange={e => onChange({ bgColor: e.target.value })}
            className="w-7 h-7 rounded cursor-pointer border border-gray-200 p-0.5"
            title="Background color"
          />
        </div>
        <button
          onClick={() => onChange({ nodeColors: { ...NODE_COLORS }, bgColor: "#f9fafb" })}
          className="w-full text-xs text-gray-400 hover:text-gray-600 py-1 border border-dashed border-gray-200 rounded hover:border-gray-300 transition-colors"
        >
          Reset colors
        </button>

        {/* ── LIMITS & PHYSICS ── */}
        <SectionLabel>Limits &amp; Physics</SectionLabel>
        <SliderRow label="Max nodes" value={settings.maxNodes} min={100} max={5000} step={100}
          onChange={v => onChange({ maxNodes: v })} />
        <SliderRow label="Gravity" value={settings.gravity} min={0} max={1} step={0.05}
          format={v => v.toFixed(2)}
          onChange={v => onChange({ gravity: v })} />

      </div>
    </div>
  );
}

// ── Main graph page ───────────────────────────────────────────────────────────

export default function Graph() {
  const { settings: appSettings } = useAppSettings();
  const [mode, setMode]           = useState<Mode>(appSettings.defaultGraphMode as Mode);
  const [data, setData]           = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading]     = useState(true);
  const [selected, setSelected]   = useState<GraphNode | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings]   = useState<VisSettings>({
    ...DEFAULT_SETTINGS,
    nodeSize:       appSettings.graphNodeSize,
    showNodeLabels: appSettings.graphShowNodeLabels,
    showEdgeLabels: appSettings.graphShowEdgeLabels,
  });

  const [queryText, setQueryText]     = useState(() => defaultQuery(appSettings.defaultGraphMode as Mode, DEFAULT_SETTINGS.maxNodes));
  const [queryError, setQueryError]   = useState<string | null>(null);
  const [queryRunning, setQueryRunning] = useState(false);

  const containerRef  = useRef<HTMLDivElement>(null);
  const graphRef      = useRef<unknown>(null);
  const settingsRef   = useRef<VisSettings>(settings);
  settingsRef.current = settings;
  const degreeRef     = useRef<Map<string, number>>(new Map());

  const navigate = useNavigate();
  const location = useLocation();

  const patchSettings = useCallback((patch: Partial<VisSettings>) => {
    setSettings(prev => ({ ...prev, ...patch }));
  }, []);

  const hasCypherState = !!(location.state as { cypherQuery?: string } | null)?.cypherQuery;

  // Filtered data: exclude hidden node types and their links
  const filteredData = useMemo(() => {
    if (settings.hiddenTypes.length === 0) return data;
    const hidden = new Set(settings.hiddenTypes);
    const nodes = data.nodes.filter(n => !hidden.has(n.type));
    const nodeIds = new Set(nodes.map(n => n.id));
    const links = data.links.filter(l => {
      const src = typeof l.source === "object" ? (l.source as GraphNode).id : l.source as string;
      const tgt = typeof l.target === "object" ? (l.target as GraphNode).id : l.target as string;
      return nodeIds.has(src) && nodeIds.has(tgt);
    });
    return { nodes, links };
  }, [data, settings.hiddenTypes]);

  // Sync query bar text when mode changes
  useEffect(() => {
    setQueryText(defaultQuery(mode, settings.maxNodes));
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-run Cypher query passed from the Cypher page via router state
  useEffect(() => {
    if (!hasCypherState) return;
    const q = (location.state as { cypherQuery?: string }).cypherQuery!;
    window.history.replaceState({}, "");
    setQueryText(q);
    setLoading(true);
    apiFetch<GraphData & { error?: string }>("/graph/cypher", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q }),
    })
      .then(res => { if (!res.error) setData(res); })
      .catch(() => {})
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Recompute node degrees from filtered links
  useEffect(() => {
    const map = new Map<string, number>();
    for (const l of filteredData.links) {
      const src = typeof l.source === "object" ? (l.source as GraphNode).id : l.source as string;
      const tgt = typeof l.target === "object" ? (l.target as GraphNode).id : l.target as string;
      map.set(src, (map.get(src) ?? 0) + 1);
      map.set(tgt, (map.get(tgt) ?? 0) + 1);
    }
    degreeRef.current = map;
  }, [filteredData]);

  // Fetch data on mode change (skip initial load when a cypher query was injected)
  const initialLoadDone = useRef(false);
  useEffect(() => {
    if (!initialLoadDone.current && hasCypherState) {
      initialLoadDone.current = true;
      return;
    }
    initialLoadDone.current = true;
    setLoading(true);
    apiFetch<GraphData>(`/graph?mode=${mode}&max_nodes=${settings.maxNodes}`)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [mode, settings.maxNodes]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build graph when filtered data is ready
  useEffect(() => {
    if (loading || !containerRef.current || filteredData.nodes.length === 0) return;

    import("force-graph").then(({ default: ForceGraph }) => {
      if (graphRef.current) {
        (graphRef.current as { _destructor?: () => void })?._destructor?.();
        containerRef.current!.innerHTML = "";
      }

      const width  = containerRef.current!.clientWidth;
      const height = containerRef.current!.clientHeight;
      const s      = settingsRef.current;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const graph = (ForceGraph as any)()(containerRef.current!);
      graph
        .width(width)
        .height(height)
        .backgroundColor(s.bgColor)
        .nodeId("id")
        .nodeLabel((n: unknown) => (n as GraphNode).label ?? "")
        .nodeColor((n: unknown) => settingsRef.current.nodeColors[(n as GraphNode).type] ?? NODE_COLORS.unknown)
        .nodeRelSize(s.nodeSize)
        .nodeVal((n: unknown) => {
          if (!settingsRef.current.sizeByDegree) return 1;
          return Math.min(Math.max(1, degreeRef.current.get((n as GraphNode).id) ?? 1), settingsRef.current.maxNodeSize);
        })
        .nodeCanvasObjectMode(() => "after")
        .nodeCanvasObject((node: unknown, ctx: CanvasRenderingContext2D, globalScale: number) => {
          if (!settingsRef.current.showNodeLabels) return;
          const n = node as GraphNode & { x?: number; y?: number };
          if (typeof n.x !== "number" || typeof n.y !== "number") return;
          const label = n.label ?? "";
          if (!label) return;

          const val = settingsRef.current.sizeByDegree
            ? Math.min(Math.max(1, degreeRef.current.get(n.id) ?? 1), settingsRef.current.maxNodeSize)
            : 1;
          const r = Math.cbrt(val) * settingsRef.current.nodeSize;
          const fontSize = Math.max(10 / globalScale, 2.5);
          ctx.font = `${fontSize}px Inter, sans-serif`;

          const maxChars = 20;
          const display = label.length > maxChars ? label.slice(0, maxChars - 1) + "…" : label;
          const tw = ctx.measureText(display).width;

          const px = n.x;
          const py = n.y + r + fontSize * 0.9;

          ctx.fillStyle = "rgba(249,250,251,0.85)";
          ctx.fillRect(px - tw / 2 - 2, py - fontSize / 2 - 1, tw + 4, fontSize + 2);
          ctx.fillStyle = "#1e293b";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(display, px, py);
        })
        .linkColor(() => "#cbd5e1")
        .linkWidth(s.linkWidth)
        .linkCurvature(s.linkCurvature)
        .linkDirectionalArrowLength(s.arrowSize)
        .linkDirectionalArrowRelPos(1)
        .linkDirectionalParticles(s.showParticles ? 2 : 0)
        .linkDirectionalParticleSpeed(0.005)
        .linkLineDash(s.dashedLinks ? [4, 2] : null)
        .linkCanvasObjectMode(() => "after")
        .linkCanvasObject((link: unknown, ctx: CanvasRenderingContext2D, globalScale: number) => {
          if (!settingsRef.current.showEdgeLabels) return;
          const l = link as { type?: string; source?: { x?: number; y?: number }; target?: { x?: number; y?: number } };
          const label = l.type ?? "";
          if (!label) return;
          const src = l.source;
          const tgt = l.target;
          if (!src || !tgt || typeof src.x !== "number" || typeof tgt.x !== "number") return;

          const midX = (src.x! + tgt.x!) / 2;
          const midY = (src.y! + tgt.y!) / 2;
          const fontSize = Math.max(9 / globalScale, 2);
          ctx.font = `${fontSize}px Inter, sans-serif`;
          const tw = ctx.measureText(label).width;

          ctx.fillStyle = "rgba(249,250,251,0.85)";
          ctx.fillRect(midX - tw / 2 - 2, midY - fontSize / 2 - 1, tw + 4, fontSize + 2);
          ctx.fillStyle = "#64748b";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(label, midX, midY);
        })
        .onNodeClick((n: unknown) => setSelected(n as GraphNode))
        .graphData({
          nodes: filteredData.nodes.map(n => ({ ...n })),
          links: filteredData.links.map(l => ({ ...l })),
        });

      graph.d3Force("link")?.distance?.(s.linkDistance);
      graph.d3Force("charge")?.strength?.(s.charge);
      graph.d3Force("center")?.strength?.(s.gravity);

      graphRef.current = graph;
    });

    return () => {
      if (graphRef.current) {
        (graphRef.current as { _destructor?: () => void })?._destructor?.();
        graphRef.current = null;
      }
    };
  }, [filteredData, loading]);

  // ── Reactive settings (no full rebuild) ────────────────────────────────────

  useEffect(() => {
    if (!graphRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (graphRef.current as any).nodeRelSize(settings.nodeSize);
  }, [settings.nodeSize]);

  useEffect(() => {
    if (!graphRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (graphRef.current as any).linkWidth(settings.linkWidth);
  }, [settings.linkWidth]);

  useEffect(() => {
    if (!graphRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (graphRef.current as any).linkDirectionalArrowLength(settings.arrowSize);
  }, [settings.arrowSize]);

  useEffect(() => {
    if (!graphRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const g = graphRef.current as any;
    g.linkCurvature(settings.linkCurvature);
    g.refresh?.();
  }, [settings.linkCurvature]);

  useEffect(() => {
    if (!graphRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (graphRef.current as any).linkDirectionalParticles(settings.showParticles ? 2 : 0);
  }, [settings.showParticles]);

  useEffect(() => {
    if (!graphRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const g = graphRef.current as any;
    g.linkLineDash(settings.dashedLinks ? [4, 2] : null);
    g.refresh?.();
  }, [settings.dashedLinks]);

  useEffect(() => {
    if (!graphRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (graphRef.current as any).backgroundColor(settings.bgColor);
  }, [settings.bgColor]);

  useEffect(() => {
    if (!graphRef.current) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const g = graphRef.current as any;
    g.nodeColor((n: unknown) => settingsRef.current.nodeColors[(n as GraphNode).type] ?? NODE_COLORS.unknown);
    g.refresh?.();
  }, [settings.nodeColors]);

  useEffect(() => {
    if (!graphRef.current) return;
    const g = graphRef.current as {
      d3Force: (n: string) => { distance?: (d: number) => unknown; strength?: (s: number) => unknown } | null;
      d3ReheatSimulation: () => void;
    };
    g.d3Force("link")?.distance?.(settings.linkDistance);
    g.d3Force("charge")?.strength?.(settings.charge);
    g.d3ReheatSimulation();
  }, [settings.linkDistance, settings.charge]);

  useEffect(() => {
    if (!graphRef.current) return;
    const g = graphRef.current as {
      d3Force: (n: string) => { strength?: (s: number) => unknown } | null;
      d3ReheatSimulation: () => void;
    };
    g.d3Force("center")?.strength?.(settings.gravity);
    g.d3ReheatSimulation();
  }, [settings.gravity]);

  useEffect(() => {
    if (!graphRef.current) return;
    (graphRef.current as { refresh?: () => void }).refresh?.();
  }, [settings.showEdgeLabels, settings.showNodeLabels, settings.sizeByDegree]);

  // ── Query bar ──────────────────────────────────────────────────────────────

  const runQuery = useCallback(async () => {
    if (!queryText.trim() || queryRunning) return;
    setQueryRunning(true);
    setQueryError(null);
    try {
      const result = await apiFetch<GraphData & { error?: string }>("/graph/cypher", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: queryText.trim() }),
      });
      if (result.error) throw new Error(result.error);
      setData(result);
    } catch (e: unknown) {
      setQueryError(e instanceof Error ? e.message : "Error");
    } finally {
      setQueryRunning(false);
    }
  }, [queryText, queryRunning]);

  const resetQuery = useCallback(() => {
    const q = defaultQuery(mode, settings.maxNodes);
    setQueryText(q);
    setQueryError(null);
    setLoading(true);
    apiFetch<GraphData>(`/graph?mode=${mode}&max_nodes=${settings.maxNodes}`)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [mode, settings.maxNodes]);

  // ── Delete node ────────────────────────────────────────────────────────────

  const handleDeleteNode = useCallback(async (node: GraphNode) => {
    await apiFetch(`/cypher/nodes/${node.id}`, { method: "DELETE" });
    setSelected(null);
    setData(prev => {
      const filtered: GraphData = {
        nodes: prev.nodes.filter(n => n.id !== node.id),
        links: prev.links.filter(l => {
          const src = typeof l.source === "object" ? (l.source as GraphNode).id : l.source;
          const tgt = typeof l.target === "object" ? (l.target as GraphNode).id : l.target;
          return src !== node.id && tgt !== node.id;
        }),
      };
      if (graphRef.current) {
        (graphRef.current as { graphData: (d: GraphData) => void }).graphData({
          nodes: filtered.nodes.map(n => ({ ...n })),
          links: filtered.links.map(l => ({ ...l })),
        });
      }
      return filtered;
    });
  }, []);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="h-[calc(100vh-53px)] flex flex-col">

      {/* Top bar */}
      <div className="flex items-center gap-2 px-4 py-2 bg-white border-b border-gray-200 shrink-0">
        {(["full", "papers"] as Mode[]).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-3 py-1 text-xs rounded-full font-medium transition-colors
              ${mode === m ? "bg-violet-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
          >
            {m === "full" ? "All nodes" : "Papers + People + Projects"}
          </button>
        ))}

        <span className="ml-auto text-xs text-gray-400">
          {loading ? "Loading…" : `${filteredData.nodes.length} nodes · ${filteredData.links.length} edges`}
        </span>

        {/* Legend — uses live node colors */}
        <div className="flex items-center gap-3 ml-4">
          {Object.entries(settings.nodeColors).filter(([k]) => k !== "unknown").map(([type, color]) => {
            const hidden = settings.hiddenTypes.includes(type);
            return (
              <span key={type} className={`flex items-center gap-1 text-xs transition-opacity ${hidden ? "opacity-30" : "text-gray-500"}`}>
                <span className="w-2 h-2 rounded-full inline-block" style={{ background: color }} />
                {type}
              </span>
            );
          })}
        </div>

        {/* Gear icon */}
        <button
          onClick={() => setShowSettings(s => !s)}
          title="Visualization settings"
          className={`ml-3 p-1.5 rounded hover:bg-gray-100 transition-colors ${showSettings ? "bg-gray-100 text-violet-600" : "text-gray-400"}`}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>

      {/* Active Cypher query bar */}
      <div className="shrink-0 bg-white border-b border-gray-200 px-4 py-2">
        <div className="flex items-start gap-2">
          <span className="text-[10px] font-bold uppercase tracking-widest text-violet-500 pt-2 shrink-0">Cypher</span>
          <textarea
            value={queryText}
            onChange={e => setQueryText(e.target.value)}
            rows={8}
            spellCheck={false}
            className="flex-1 text-xs font-mono border border-gray-200 rounded p-1.5 resize-y focus:outline-none focus:ring-1 focus:ring-violet-400 bg-gray-50 leading-relaxed"
            onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runQuery(); }}
          />
          <div className="flex flex-col gap-1 shrink-0 pt-0.5">
            <button
              onClick={runQuery}
              disabled={queryRunning}
              className="px-2.5 py-1 text-xs font-medium bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {queryRunning ? "…" : "Run ⌘↵"}
            </button>
            <button
              onClick={resetQuery}
              className="px-2.5 py-1 text-xs font-medium border border-gray-200 text-gray-500 rounded hover:bg-gray-50 transition-colors"
            >
              Reset
            </button>
          </div>
        </div>
        {queryError && <p className="text-xs text-red-500 mt-1 ml-14">{queryError}</p>}
      </div>

      {/* Graph + properties panel */}
      <div className="flex-1 flex overflow-hidden">

        {/* Canvas area */}
        <div className="flex-1 relative overflow-hidden" style={{ background: settings.bgColor }}>
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-400 z-10">
              Loading graph…
            </div>
          )}
          {!loading && filteredData.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-400">
              No data yet — upload some papers or run a Cypher query.
            </div>
          )}
          <div ref={containerRef} className="w-full h-full" />

          {/* Floating settings panel */}
          {showSettings && (
            <SettingsPanel
              settings={settings}
              onChange={patchSettings}
              onClose={() => setShowSettings(false)}
            />
          )}
        </div>

        {/* Node properties panel */}
        {selected && (
          <NodePanel
            node={selected}
            onClose={() => setSelected(null)}
            onNavigate={() => navigate(`/paper/${selected.id}`)}
            onDelete={() => handleDeleteNode(selected)}
            nodeColors={settings.nodeColors}
          />
        )}
      </div>
    </div>
  );
}
