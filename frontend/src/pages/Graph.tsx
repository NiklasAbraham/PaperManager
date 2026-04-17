import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useAppSettings } from "../contexts/SettingsContext";
import type { GraphData, GraphNode } from "../types";

type Mode = "full" | "papers";

interface VisSettings {
  nodeSize: number;
  linkDistance: number;
  charge: number;
  showEdgeLabels: boolean;
  showNodeLabels: boolean;
}

const DEFAULT_SETTINGS: VisSettings = {
  nodeSize: 16,
  linkDistance: 120,
  charge: -200,
  showEdgeLabels: true,
  showNodeLabels: true,
};

const NODE_COLORS: Record<string, string> = {
  paper:   "#7c3aed",
  person:  "#2563eb",
  topic:   "#16a34a",
  tag:     "#d97706",
  project: "#db2777",
  note:    "#6b7280",
  unknown: "#9ca3af",
};

const SKIP_PROPS = new Set(["x", "y", "vx", "vy", "fx", "fy", "__indexColor", "index"]);

// ── Node properties panel ────────────────────────────────────────────────────

function NodePanel({ node, onClose, onNavigate, onDelete }: {
  node: GraphNode;
  onClose: () => void;
  onNavigate: () => void;
  onDelete: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const color = NODE_COLORS[node.type] ?? NODE_COLORS.unknown;
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

// ── Settings panel ───────────────────────────────────────────────────────────

function SettingsPanel({ settings, onChange, onClose }: {
  settings: VisSettings;
  onChange: (patch: Partial<VisSettings>) => void;
  onClose: () => void;
}) {
  return (
    <div className="absolute top-10 right-2 z-20 w-60 bg-white rounded-lg shadow-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Visualization</span>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-base leading-none">×</button>
      </div>

      <div className="space-y-4">
        <label className="block">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>Node size</span><span className="font-mono">{settings.nodeSize}</span>
          </div>
          <input type="range" min="6" max="36" step="1" value={settings.nodeSize}
            onChange={e => onChange({ nodeSize: +e.target.value })}
            className="w-full accent-violet-600" />
        </label>

        <label className="block">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>Link distance</span><span className="font-mono">{settings.linkDistance}</span>
          </div>
          <input type="range" min="30" max="400" step="10" value={settings.linkDistance}
            onChange={e => onChange({ linkDistance: +e.target.value })}
            className="w-full accent-violet-600" />
        </label>

        <label className="block">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>Repulsion</span><span className="font-mono">{Math.abs(settings.charge)}</span>
          </div>
          <input type="range" min="30" max="600" step="10" value={Math.abs(settings.charge)}
            onChange={e => onChange({ charge: -Number(e.target.value) })}
            className="w-full accent-violet-600" />
        </label>

        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">Node labels</span>
          <button
            onClick={() => onChange({ showNodeLabels: !settings.showNodeLabels })}
            className={`relative w-9 h-5 rounded-full transition-colors ${settings.showNodeLabels ? "bg-violet-600" : "bg-gray-300"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${settings.showNodeLabels ? "translate-x-4" : "translate-x-0"}`} />
          </button>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">Edge labels</span>
          <button
            onClick={() => onChange({ showEdgeLabels: !settings.showEdgeLabels })}
            className={`relative w-9 h-5 rounded-full transition-colors ${settings.showEdgeLabels ? "bg-violet-600" : "bg-gray-300"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${settings.showEdgeLabels ? "translate-x-4" : "translate-x-0"}`} />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Cypher bar ───────────────────────────────────────────────────────────────

function CypherBar({ onRun }: { onRun: (q: string) => Promise<void> }) {
  const [open, setOpen]       = useState(false);
  const [query, setQuery]     = useState("");
  const [error, setError]     = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    if (!query.trim() || running) return;
    setRunning(true);
    setError(null);
    try {
      await onRun(query.trim());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="shrink-0 bg-white border-t border-gray-200">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 w-full px-4 py-2 text-xs text-gray-500 hover:text-gray-700"
      >
        <span className="font-mono font-semibold text-violet-600">CYPHER</span>
        <span className="text-gray-300 ml-1">run a custom query</span>
        <span className="ml-auto">{open ? "▾" : "▴"}</span>
      </button>

      {open && (
        <div className="px-4 pb-3 space-y-2">
          <textarea
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={"MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 50"}
            rows={3}
            className="w-full text-xs font-mono border border-gray-200 rounded p-2 resize-y focus:outline-none focus:ring-1 focus:ring-violet-500"
            onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run(); }}
          />
          <div className="flex items-center gap-3">
            <button
              onClick={run}
              disabled={running}
              className="px-3 py-1 text-xs font-medium bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {running ? "Running…" : "Run  (⌘↵)"}
            </button>
            {error && <span className="text-xs text-red-500 break-all">{error}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main graph page ──────────────────────────────────────────────────────────

export default function Graph() {
  const { settings: appSettings } = useAppSettings();
  const [mode, setMode]           = useState<Mode>(appSettings.defaultGraphMode);
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

  const containerRef  = useRef<HTMLDivElement>(null);
  const graphRef      = useRef<unknown>(null);
  const settingsRef   = useRef<VisSettings>(settings);
  settingsRef.current = settings;

  const navigate = useNavigate();
  const location = useLocation();

  const patchSettings = useCallback((patch: Partial<VisSettings>) => {
    setSettings(prev => ({ ...prev, ...patch }));
  }, []);

  const hasCypherState = !!(location.state as { cypherQuery?: string } | null)?.cypherQuery;

  // Auto-run Cypher query passed from the Cypher page via router state
  useEffect(() => {
    if (!hasCypherState) return;
    const q = (location.state as { cypherQuery?: string }).cypherQuery!;
    window.history.replaceState({}, "");
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

  // Fetch data on mode change (skip initial load when a cypher query was injected)
  const initialLoadDone = useRef(false);
  useEffect(() => {
    if (!initialLoadDone.current && hasCypherState) {
      initialLoadDone.current = true;
      return;
    }
    initialLoadDone.current = true;
    setLoading(true);
    apiFetch<GraphData>(`/graph?mode=${mode}`)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build graph when data is ready
  useEffect(() => {
    if (loading || !containerRef.current || data.nodes.length === 0) return;

    import("force-graph").then(({ default: ForceGraph }) => {
      if (graphRef.current) {
        (graphRef.current as { _destructor?: () => void })?._destructor?.();
        containerRef.current!.innerHTML = "";
      }

      const width  = containerRef.current!.clientWidth;
      const height = containerRef.current!.clientHeight;
      const s      = settingsRef.current;

      const graph = ForceGraph()(containerRef.current!)
        .width(width)
        .height(height)
        .backgroundColor("#f9fafb")
        .nodeId("id")
        .nodeLabel((n: unknown) => (n as GraphNode).label ?? "")
        .nodeColor((n: unknown) => NODE_COLORS[(n as GraphNode).type] ?? NODE_COLORS.unknown)
        .nodeRelSize(s.nodeSize)
        .nodeCanvasObjectMode(() => "after")
        .nodeCanvasObject((node: unknown, ctx: CanvasRenderingContext2D, globalScale: number) => {
          if (!settingsRef.current.showNodeLabels) return;
          const n = node as GraphNode & { x?: number; y?: number };
          if (typeof n.x !== "number" || typeof n.y !== "number") return;
          const label = n.label ?? "";
          if (!label) return;

          const r = settingsRef.current.nodeSize;
          const fontSize = Math.max(10 / globalScale, 2.5);
          ctx.font = `${fontSize}px Inter, sans-serif`;

          // Truncate long labels
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
        .linkWidth(1.5)
        .linkDirectionalArrowLength(6)
        .linkDirectionalArrowRelPos(1)
        // Edge labels drawn on canvas
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
          nodes: data.nodes.map(n => ({ ...n })),
          links: data.links.map(l => ({ ...l })),
        });

      // Apply force settings
      (graph as unknown as { d3Force: (name: string) => { distance?: (d: number) => unknown; strength?: (s: number) => unknown } | null })
        .d3Force("link")?.distance?.(s.linkDistance);
      (graph as unknown as { d3Force: (name: string) => { distance?: (d: number) => unknown; strength?: (s: number) => unknown } | null })
        .d3Force("charge")?.strength?.(s.charge);

      graphRef.current = graph;
    });

    return () => {
      if (graphRef.current) {
        (graphRef.current as { _destructor?: () => void })?._destructor?.();
        graphRef.current = null;
      }
    };
  }, [data, loading]);

  // Apply node size without rebuilding
  useEffect(() => {
    if (!graphRef.current) return;
    (graphRef.current as { nodeRelSize: (s: number) => void }).nodeRelSize(settings.nodeSize);
  }, [settings.nodeSize]);

  // Apply force settings without rebuilding
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

  // Refresh canvas on label toggles
  useEffect(() => {
    if (!graphRef.current) return;
    (graphRef.current as { refresh?: () => void }).refresh?.();
  }, [settings.showEdgeLabels, settings.showNodeLabels]);

  // Run custom Cypher query
  const runCypher = useCallback(async (query: string) => {
    const result = await apiFetch<GraphData & { error?: string }>("/graph/cypher", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (result.error) throw new Error(result.error);
    setData(result);
  }, []);

  // Delete a node and surgically remove it from the live graph
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
      // Update the live force-graph without full rebuild
      if (graphRef.current) {
        (graphRef.current as { graphData: (d: GraphData) => void }).graphData({
          nodes: filtered.nodes.map(n => ({ ...n })),
          links: filtered.links.map(l => ({ ...l })),
        });
      }
      return filtered;
    });
  }, []);

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
            {m === "full" ? "All nodes" : "Papers + People + Topics"}
          </button>
        ))}

        <span className="ml-auto text-xs text-gray-400">
          {loading ? "Loading…" : `${data.nodes.length} nodes · ${data.links.length} edges`}
        </span>

        {/* Legend */}
        <div className="flex items-center gap-3 ml-4">
          {Object.entries(NODE_COLORS).filter(([k]) => k !== "unknown").map(([type, color]) => (
            <span key={type} className="flex items-center gap-1 text-xs text-gray-500">
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: color }} />
              {type}
            </span>
          ))}
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

      {/* Graph + properties panel */}
      <div className="flex-1 flex overflow-hidden">
        {/* Canvas area */}
        <div className="flex-1 relative bg-gray-50 overflow-hidden">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-400 z-10">
              Loading graph…
            </div>
          )}
          {!loading && data.nodes.length === 0 && (
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
          />
        )}
      </div>

      {/* Cypher query bar */}
      <CypherBar onRun={runCypher} />
    </div>
  );
}
