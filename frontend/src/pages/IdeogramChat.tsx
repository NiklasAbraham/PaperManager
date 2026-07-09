import { useCallback, useEffect, useRef, useState } from "react";
import {
  startIdeogramSession,
  getIdeogramStatus,
  stopIdeogramSession,
  ideogramGenerate,
  ideogramMagicPrompt,
} from "../api/client";
import type { IdeogramCaption, IdeogramElement, IdeogramPreset } from "../types";
import {
  saveGeneration,
  listGenerations,
  deleteGeneration,
  clearHistory,
  newId,
  type HistoryEntry,
} from "../lib/ideogramHistory";

const PRESETS: { value: IdeogramPreset; label: string }[] = [
  { value: "V4_TURBO_12", label: "Turbo · fastest" },
  { value: "V4_DEFAULT_20", label: "Default" },
  { value: "V4_QUALITY_48", label: "Quality · best" },
];

type Resolution = { label: string; w: number; h: number };

const RESOLUTIONS: Resolution[] = [
  { label: "Square · 1024²", w: 1024, h: 1024 },
  { label: "Landscape · 1536×1024", w: 1536, h: 1024 },
  { label: "Portrait · 1024×1536", w: 1024, h: 1536 },
  { label: "Widescreen · 1920×1088", w: 1920, h: 1088 },
];

// Quick aspect-ratio chips for the Custom size mode (already multiples of 16).
const RATIO_CHIPS: { label: string; w: number; h: number }[] = [
  { label: "1:1", w: 1024, h: 1024 },
  { label: "16:9", w: 1920, h: 1088 },
  { label: "9:16", w: 1088, h: 1920 },
  { label: "4:3", w: 1360, h: 1024 },
  { label: "3:4", w: 1024, h: 1360 },
  { label: "A4", w: 1024, h: 1456 },
];

const TEMPLATE: IdeogramCaption = {
  high_level_description: "A clean minimalist poster with a bold title and a red circle",
  style_description: {
    aesthetics: "clean, minimalist, high contrast, centered composition",
    lighting: "flat even studio lighting",
    medium: "digital vector illustration",
    art_style: "flat design with bold geometric shapes",
    color_palette: ["#FFFFFF", "#E63946", "#1D3557"],
  },
  compositional_deconstruction: {
    background: "a solid off-white background",
    elements: [
      { type: "text", bbox: [120, 120, 300, 880], text: "HELLO", desc: "large bold uppercase sans-serif title in dark navy", color_palette: ["#1D3557"] },
      { type: "object", bbox: [420, 350, 820, 650], desc: "a large solid flat red circle centered in the lower half", color_palette: ["#E63946"] },
    ],
  },
};

// A blank caption — the tool starts from zero (no pre-filled example boxes). The
// TEMPLATE above is only loaded on demand via the "Template" button.
const EMPTY: IdeogramCaption = {
  high_level_description: "",
  style_description: { aesthetics: "", lighting: "", medium: "", art_style: "", color_palette: [] },
  compositional_deconstruction: { background: "", elements: [] },
};

type SessionState = "stopped" | "starting" | "ready" | "error";
type Bbox = [number, number, number, number];

const randomSeed = () => Math.floor(Math.random() * 1_000_000);
const slug = (s: string) => (s || "ideogram").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "ideogram";

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
// Ideogram requires dims that are multiples of 16 in [256, 2048].
const snap16 = (n: number) => clamp(Math.round((n || 0) / 16) * 16, 256, 2048);

function downloadPng(b64: string, name: string) {
  const a = document.createElement("a");
  a.href = `data:image/png;base64,${b64}`;
  a.download = name;
  a.click();
}
function downloadJson(obj: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Status pill ───────────────────────────────────────────────────────────────

function StatusPill({ state, detail }: { state: SessionState; detail?: string }) {
  const map: Record<SessionState, { text: string; cls: string; dot: string }> = {
    stopped: { text: "GPU stopped", cls: "bg-line-s text-ink-3", dot: "bg-ink-3" },
    starting: { text: "Spinning up GPU…", cls: "bg-amber-50 text-amber", dot: "bg-amber animate-pulse" },
    ready: { text: "GPU ready", cls: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
    error: { text: detail || "GPU error", cls: "bg-red-50 text-coral", dot: "bg-coral" },
  };
  const m = map[state];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${m.cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${m.dot}`} />
      {m.text}
    </span>
  );
}

// ── Image hero with draggable / resizable box overlays ────────────────────────

// Resize handles: corners + edge midpoints. Single-letter modes ("n"/"e"/…) are
// matched with .includes() so corners ("nw") drive both axes.
const HANDLES: { m: string; pos: string; cur: string }[] = [
  { m: "nw", pos: "-top-1 -left-1", cur: "nwse-resize" },
  { m: "ne", pos: "-top-1 -right-1", cur: "nesw-resize" },
  { m: "sw", pos: "-bottom-1 -left-1", cur: "nesw-resize" },
  { m: "se", pos: "-bottom-1 -right-1", cur: "nwse-resize" },
  { m: "n", pos: "-top-1 left-1/2 -translate-x-1/2", cur: "ns-resize" },
  { m: "s", pos: "-bottom-1 left-1/2 -translate-x-1/2", cur: "ns-resize" },
  { m: "w", pos: "top-1/2 -left-1 -translate-y-1/2", cur: "ew-resize" },
  { m: "e", pos: "top-1/2 -right-1 -translate-y-1/2", cur: "ew-resize" },
];

const SNAP_GRID = 10; // grid step to snap to (0–1000 units)
const SNAP_THR = 12;  // pull-in distance for guide/grid snapping

function ImageCanvas({
  imageB64, elements, selected, onSelect, onMoveBbox, onDragStart, onCreateBox, aspect, busy,
  drawMode, showGrid, gridStep, showBoxes,
}: {
  imageB64: string | null;
  elements: IdeogramElement[];
  selected: number | null;
  onSelect: (i: number | null) => void;
  onMoveBbox: (i: number, bbox: Bbox) => void;
  onDragStart: () => void;
  onCreateBox: (bbox: Bbox) => void;
  aspect: number;
  busy: boolean;
  drawMode: boolean;
  showGrid: boolean;
  gridStep: number;
  showBoxes: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // The generated image can come back at a slightly different aspect than we
  // requested (the model normalizes dims to a supported tier). Measure the real
  // PNG once it loads and use THAT for the canvas, so the box overlays line up
  // with the actual pixels rather than the requested size. Keyed to the current
  // image so it auto-falls back to the requested aspect when the image changes.
  const [imgAspect, setImgAspect] = useState<{ src: string; a: number } | null>(null);
  const effAspect = imageB64 && imgAspect?.src === imageB64 ? imgAspect.a : aspect;
  // Active drag of an existing box: which one, mode, pointer origin, start bbox.
  const drag = useRef<null | { i: number; mode: string; startX: number; startY: number; bbox: Bbox }>(null);
  // Active draw of a NEW box on empty canvas: the anchor corner in grid units.
  const draw = useRef<null | { x: number; y: number }>(null);
  const [draft, setDraft] = useState<Bbox | null>(null);

  const toGrid = (clientX: number, clientY: number) => {
    const r = ref.current!.getBoundingClientRect();
    return {
      gx: clamp(((clientX - r.left) / r.width) * 1000, 0, 1000),
      gy: clamp(((clientY - r.top) / r.height) * 1000, 0, 1000),
    };
  };

  // Resize-handle press (only handles call this; they stopPropagation so the
  // container's hit-test below doesn't also fire).
  const beginResize = (e: React.PointerEvent, i: number, mode: string) => {
    e.preventDefault();
    e.stopPropagation();
    onSelect(i);
    onDragStart(); // snapshot for undo, once per gesture
    ref.current?.setPointerCapture(e.pointerId);
    drag.current = { i, mode, startX: e.clientX, startY: e.clientY, bbox: [...elements[i].bbox] as Bbox };
  };

  // All body / empty-space presses are handled here by hit-testing, so a box
  // hidden UNDER another can still be grabbed: clicking a spot picks the topmost
  // box there; clicking again cycles to the next box beneath it.
  const onCanvasDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const { gx, gy } = toGrid(e.clientX, e.clientY);
    // In Draw mode (or when boxes are hidden), always start a NEW box — even over
    // existing ones — so drawing never gets blocked by a covering box.
    const hits = (drawMode || !showBoxes) ? [] : elements
      .map((el, idx) => ({ idx, el }))
      .filter(({ el }) => gy >= el.bbox[0] && gy <= el.bbox[2] && gx >= el.bbox[1] && gx <= el.bbox[3])
      .map(({ idx }) => idx)
      .sort((a, b) => b - a); // later-drawn (visually in front) first

    if (hits.length === 0) { // empty space (or draw mode) → draw a new box
      onSelect(null);
      draw.current = { x: gx, y: gy };
      setDraft([gy, gx, gy, gx]);
      ref.current?.setPointerCapture(e.pointerId);
      return;
    }

    // Cycle: if the current selection is one of the boxes under the cursor, step
    // to the NEXT one down (wrapping); otherwise grab the topmost.
    let target = hits[0];
    if (selected != null && hits.includes(selected)) {
      target = hits[(hits.indexOf(selected) + 1) % hits.length];
    }
    onSelect(target);
    onDragStart();
    ref.current?.setPointerCapture(e.pointerId);
    drag.current = { i: target, mode: "move", startX: e.clientX, startY: e.clientY, bbox: [...elements[target].bbox] as Bbox };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (draw.current) {
      const { gx, gy } = toGrid(e.clientX, e.clientY);
      setDraft([Math.min(draw.current.y, gy), Math.min(draw.current.x, gx), Math.max(draw.current.y, gy), Math.max(draw.current.x, gx)]);
      return;
    }
    const d = drag.current;
    if (!d) return;
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const dx = ((e.clientX - d.startX) / r.width) * 1000; // px → 0–1000 grid units
    const dy = ((e.clientY - d.startY) / r.height) * 1000;
    const noSnap = e.altKey; // hold Alt to move/resize freely (snapping off)
    const step = showGrid ? gridStep : SNAP_GRID; // snap to the visible grid when it's on
    // Snap guides: canvas thirds/edges + every other box's edges.
    const others = elements.filter((_, idx) => idx !== d.i);
    const gx = [0, 250, 500, 750, 1000, ...others.flatMap((o) => [o.bbox[1], o.bbox[3]])];
    const gy = [0, 250, 500, 750, 1000, ...others.flatMap((o) => [o.bbox[0], o.bbox[2]])];
    const snapEdge = (v: number, guides: number[]) => {
      if (noSnap) return v;
      for (const g of guides) if (Math.abs(v - g) < SNAP_THR) return g;
      return Math.round(v / step) * step;
    };
    const snapMove = (lo: number, hi: number, guides: number[]) => {
      const size = hi - lo;
      if (noSnap) return clamp(lo, 0, 1000 - size);
      let best: number | null = null, bd = SNAP_THR;
      for (const g of guides) {
        if (Math.abs(lo - g) < bd) { best = g; bd = Math.abs(lo - g); }
        if (Math.abs(hi - g) < bd) { best = g - size; bd = Math.abs(hi - g); }
      }
      if (best != null) return clamp(best, 0, 1000 - size);
      return clamp(Math.round(lo / step) * step, 0, 1000 - size);
    };

    let [y0, x0, y1, x1] = d.bbox;
    const MIN = 20; // smallest box the model should get
    if (d.mode === "move") {
      const w = x1 - x0, h = y1 - y0;
      x0 = snapMove(clamp(x0 + dx, 0, 1000 - w), clamp(x0 + dx, 0, 1000 - w) + w, gx); x1 = x0 + w;
      y0 = snapMove(clamp(y0 + dy, 0, 1000 - h), clamp(y0 + dy, 0, 1000 - h) + h, gy); y1 = y0 + h;
    } else {
      if (d.mode.includes("n")) y0 = clamp(snapEdge(y0 + dy, gy), 0, y1 - MIN);
      if (d.mode.includes("s")) y1 = clamp(snapEdge(y1 + dy, gy), y0 + MIN, 1000);
      if (d.mode.includes("w")) x0 = clamp(snapEdge(x0 + dx, gx), 0, x1 - MIN);
      if (d.mode.includes("e")) x1 = clamp(snapEdge(x1 + dx, gx), x0 + MIN, 1000);
    }
    onMoveBbox(d.i, [Math.round(y0), Math.round(x0), Math.round(y1), Math.round(x1)]);
  };

  const endDrag = (e: React.PointerEvent) => {
    if (draw.current) {
      const { gx, gy } = toGrid(e.clientX, e.clientY);
      const x0 = Math.min(draw.current.x, gx), x1 = Math.max(draw.current.x, gx);
      const y0 = Math.min(draw.current.y, gy), y1 = Math.max(draw.current.y, gy);
      draw.current = null;
      setDraft(null);
      if (x1 - x0 > 20 && y1 - y0 > 20) onCreateBox([Math.round(y0), Math.round(x0), Math.round(y1), Math.round(x1)]);
      return;
    }
    drag.current = null;
  };

  return (
    <div
      ref={ref}
      onPointerDown={onCanvasDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      className="relative w-full mx-auto rounded-xl overflow-hidden bg-base ring-1 ring-inset ring-line touch-none select-none cursor-crosshair"
      style={{ aspectRatio: String(effAspect), maxWidth: effAspect >= 1 ? "100%" : `calc((100vh - 20rem) * ${effAspect})` }}
    >
      {imageB64 ? (
        <img src={`data:image/png;base64,${imageB64}`} alt="generated" draggable={false} onLoad={(e) => setImgAspect({ src: imageB64, a: e.currentTarget.naturalWidth / e.currentTarget.naturalHeight })} className="absolute inset-0 w-full h-full object-contain pointer-events-none" />
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-ink-3 pointer-events-none">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-10 h-10">
            <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="m21 15-5-5L5 21" />
          </svg>
          <span className="text-sm">Drag on the canvas to add a box · drag boxes to move · corners/edges to resize</span>
        </div>
      )}

      {/* Visible grid overlay (snap target when on). */}
      {showGrid && (
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "linear-gradient(to right, rgba(128,128,160,0.30) 1px, transparent 1px), linear-gradient(to bottom, rgba(128,128,160,0.30) 1px, transparent 1px)",
            backgroundSize: `${gridStep / 10}% ${gridStep / 10}%`,
          }}
        />
      )}

      {/* Box overlays — bbox = [y_min, x_min, y_max, x_max] on 0–1000. */}
      {showBoxes && elements.map((el, i) => {
        const [y0, x0, y1, x1] = el.bbox;
        const active = selected === i;
        const label = el.type === "text" ? (el.text || "text") : (el.desc || "object");
        return (
          <div
            key={i}
            title={el.type === "text" ? `text: ${el.text ?? ""}` : el.desc}
            className={`absolute rounded-md cursor-move transition-shadow ${active ? "ring-2 ring-inset ring-accent bg-accent/10 border border-accent z-20" : "border border-accent-border/80 hover:border-accent"}`}
            style={{ left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%` }}
          >
            <span className={`absolute -top-2 -left-2 w-5 h-5 flex items-center justify-center text-[10px] font-bold rounded-full shadow pointer-events-none ${active ? "bg-accent text-white" : "bg-raised text-accent border border-accent-border"}`}>
              {i + 1}
            </span>
            {/* Live label so the box is identifiable on the image itself. */}
            <span className="absolute top-0 left-0 max-w-full px-1 py-0.5 text-[9px] leading-tight bg-accent/85 text-white rounded-br rounded-tl-md pointer-events-none truncate">
              {label}
            </span>
            {active && HANDLES.map((h) => (
              <span
                key={h.m}
                onPointerDown={(e) => beginResize(e, i, h.m)}
                className={`absolute ${h.pos} z-30 w-2.5 h-2.5 rounded-sm bg-white border border-accent shadow`}
                style={{ cursor: h.cur }}
              />
            ))}
          </div>
        );
      })}

      {/* Draft rectangle while drawing a new box. */}
      {draft && (
        <div
          className="absolute rounded-md border-2 border-dashed border-accent bg-accent/10 pointer-events-none"
          style={{ left: `${draft[1] / 10}%`, top: `${draft[0] / 10}%`, width: `${(draft[3] - draft[1]) / 10}%`, height: `${(draft[2] - draft[0]) / 10}%` }}
        />
      )}

      {busy && (
        <div className="absolute inset-0 flex items-center justify-center bg-ink/20 backdrop-blur-[1px]">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-raised shadow text-sm text-ink-2">
            <span className="w-3 h-3 rounded-full border-2 border-accent border-t-transparent animate-spin" />
            Generating…
          </div>
        </div>
      )}
    </div>
  );
}

// ── Color swatches editor ─────────────────────────────────────────────────────

function Swatches({ colors, onChange }: { colors: string[]; onChange: (c: string[]) => void }) {
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {colors.map((c, i) => (
        <span key={i} className="inline-flex items-center gap-1 rounded border border-line pl-1 pr-1.5 py-0.5 text-[10px] font-mono bg-raised">
          <span className="w-3 h-3 rounded-sm border border-line" style={{ background: c }} />
          {c}
          <button type="button" className="text-ink-3 hover:text-coral" onClick={(e) => { e.stopPropagation(); onChange(colors.filter((_, j) => j !== i)); }}>×</button>
        </span>
      ))}
      <input
        placeholder="+ #hex"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          const v = (e.target as HTMLInputElement).value.trim();
          if (e.key === "Enter" && /^#?[0-9a-fA-F]{6}$/.test(v)) {
            onChange([...colors, v.startsWith("#") ? v.toUpperCase() : `#${v.toUpperCase()}`]);
            (e.target as HTMLInputElement).value = "";
          }
        }}
        className="w-16 text-[10px] font-mono border border-line rounded px-1 py-0.5 focus:outline-none focus:ring-2 focus:ring-violet-300"
      />
    </div>
  );
}

// ── Box (element) editor card ─────────────────────────────────────────────────

function ElementCard({
  el, index, count, selected, collapseDefault, collapseKey, onSelect, onChange, onRemove, onDuplicate, onReorder, onRegenerate, busy,
}: {
  el: IdeogramElement; index: number; count: number; selected: boolean;
  collapseDefault: boolean; collapseKey: number;
  onSelect: () => void; onChange: (el: IdeogramElement) => void;
  onRemove: () => void; onDuplicate: () => void; onReorder: (dir: number) => void; onRegenerate: () => void; busy: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  // Collapsed state follows the global Collapse-all/Expand-all signal
  // (collapseKey/Default) unless the user has overridden it for this signal.
  const [override, setOverride] = useState<{ key: number; v: boolean } | null>(null);
  const collapsed = override && override.key === collapseKey ? override.v : collapseDefault;
  const toggleCollapsed = () => setOverride({ key: collapseKey, v: !collapsed });
  const label = el.type === "text" ? (el.text || "text") : (el.desc || "object");
  const setBbox = (i: number, v: number) => {
    const bbox = [...el.bbox] as Bbox;
    bbox[i] = clamp(v || 0, 0, 1000);
    onChange({ ...el, bbox });
  };
  return (
    <div
      onClick={onSelect}
      className={`rounded-xl border p-3 cursor-pointer transition-colors ${selected ? "border-accent bg-accent-lo" : "border-line bg-raised hover:border-accent-border"}`}
    >
      <div className={`flex items-center gap-2 ${collapsed ? "" : "mb-2"}`}>
        <button type="button" onClick={(e) => { e.stopPropagation(); toggleCollapsed(); }} title={collapsed ? "Expand fields" : "Collapse fields"} className="text-ink-3 hover:text-accent shrink-0">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`w-4 h-4 transition-transform ${collapsed ? "-rotate-90" : ""}`}><path d="m6 9 6 6 6-6" /></svg>
        </button>
        <span className={`w-5 h-5 shrink-0 flex items-center justify-center text-[10px] font-bold rounded-full ${selected ? "bg-accent text-white" : "bg-line-s text-ink-2"}`}>{index + 1}</span>
        {collapsed ? (
          <span className="text-xs text-ink-2 truncate flex-1 min-w-0">{label}</span>
        ) : (
          <select
            value={el.type}
            onChange={(e) => onChange({ ...el, type: e.target.value as IdeogramElement["type"] })}
            onClick={(e) => e.stopPropagation()}
            className="text-xs border border-line rounded px-1.5 py-1 focus:outline-none focus:ring-2 focus:ring-violet-300"
          >
            <option value="text">text</option>
            <option value="object">object</option>
          </select>
        )}
        {!collapsed && <span className="text-[10px] text-ink-3">{index === 0 ? "back" : index === count - 1 ? "front" : `layer ${index + 1}`}</span>}
        <div className="ml-auto flex items-center gap-1">
          <button type="button" onClick={(e) => { e.stopPropagation(); onReorder(1); }} disabled={index === count - 1} title="Bring forward (draw in front)" className="text-ink-3 hover:text-accent px-0.5 disabled:opacity-30">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><path d="m6 15 6-6 6 6" /></svg>
          </button>
          <button type="button" onClick={(e) => { e.stopPropagation(); onReorder(-1); }} disabled={index === 0} title="Send backward (draw behind)" className="text-ink-3 hover:text-accent px-0.5 disabled:opacity-30">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><path d="m6 9 6 6 6-6" /></svg>
          </button>
          {!collapsed && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }}
              title={expanded ? "Shrink fields" : "Enlarge fields for more room"}
              className="text-ink-3 hover:text-accent px-1"
            >
              {expanded
                ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><path d="M9 9 4 4m0 0v4m0-4h4m6 6 5 5m0 0v-4m0 4h-4" /></svg>
                : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><path d="M8 4H4v4m0-4 6 6m6-6h4v4m0-4-6 6M8 20H4v-4m0 4 6-6m6 6h4v-4m0 4-6-6" /></svg>}
            </button>
          )}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onRegenerate(); }}
            disabled={busy}
            title="Regenerate with the same seed so the rest of the image stays stable"
            className="text-[11px] px-2 py-1 rounded-lg bg-accent text-white hover:bg-violet-700 disabled:opacity-40"
          >
            Regenerate box
          </button>
          <button type="button" onClick={(e) => { e.stopPropagation(); onDuplicate(); }} title="Duplicate box" className="text-ink-3 hover:text-accent px-1">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></svg>
          </button>
          <button type="button" onClick={(e) => { e.stopPropagation(); onRemove(); }} title="Remove box" className="text-ink-3 hover:text-coral px-1">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14" /></svg>
          </button>
        </div>
      </div>

      {!collapsed && (
        <>
          {el.type === "text" && (
            <textarea
              value={el.text ?? ""}
              onChange={(e) => onChange({ ...el, text: e.target.value })}
              onClick={(e) => e.stopPropagation()}
              placeholder="Text to render (use Enter for line breaks)"
              rows={expanded ? 4 : 1}
              className="w-full mb-2 text-sm font-medium border border-line rounded px-2 py-1.5 resize-y min-h-[2rem] focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
          )}
          <textarea
            value={el.desc ?? ""}
            onChange={(e) => onChange({ ...el, desc: e.target.value })}
            onClick={(e) => e.stopPropagation()}
            placeholder="Describe this box"
            rows={expanded ? 8 : 2}
            className="w-full mb-2 text-sm border border-line rounded px-2 py-1.5 resize-y min-h-[3rem] focus:outline-none focus:ring-2 focus:ring-violet-300"
          />
          <div className="flex items-center gap-1 mb-2">
            {(["y", "x", "y2", "x2"] as const).map((lbl, i) => (
              <label key={lbl} className="flex-1">
                <span className="block text-[9px] uppercase tracking-wide text-ink-3">{lbl}</span>
                <input
                  type="number" min={0} max={1000} value={el.bbox[i]}
                  onChange={(e) => setBbox(i, parseInt(e.target.value, 10))}
                  onClick={(e) => e.stopPropagation()}
                  className="w-full text-xs font-mono border border-line rounded px-1 py-0.5 focus:outline-none focus:ring-2 focus:ring-violet-300"
                />
              </label>
            ))}
          </div>
          <Swatches colors={el.color_palette ?? []} onChange={(c) => onChange({ ...el, color_palette: c })} />
        </>
      )}
    </div>
  );
}

// ── History drawer ────────────────────────────────────────────────────────────

function HistoryDrawer({
  open, entries, onClose, onRestore, onDelete, onClear,
}: {
  open: boolean; entries: HistoryEntry[]; onClose: () => void;
  onRestore: (e: HistoryEntry) => void; onDelete: (id: string) => void; onClear: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40" onClick={onClose}>
      <div className="absolute inset-0 bg-ink/20" />
      <div
        className="absolute right-0 top-0 h-full w-80 max-w-[90vw] bg-raised border-l border-line shadow-xl flex flex-col animate-slide-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-4 py-3 border-b border-line-s flex items-center">
          <h3 className="font-semibold text-ink">History</h3>
          <span className="ml-2 text-xs text-ink-3">{entries.length}</span>
          <div className="ml-auto flex items-center gap-2">
            {entries.length > 0 && (
              <button type="button" onClick={onClear} className="text-xs text-ink-3 hover:text-coral">Clear all</button>
            )}
            <button type="button" onClick={onClose} className="text-ink-3 hover:text-ink-2">✕</button>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-3 grid grid-cols-2 gap-3">
          {entries.length === 0 && <div className="col-span-2 text-sm text-ink-3 text-center py-8">No saved generations yet.</div>}
          {entries.map((e) => {
            const boxes = e.caption?.compositional_deconstruction?.elements?.length ?? 0;
            return (
              <div key={e.id} className="group relative rounded-lg border border-line overflow-hidden bg-base">
                <button type="button" onClick={() => onRestore(e)} className="block w-full" title="Restore boxes & settings">
                  {e.imageB64 ? (
                    <img src={`data:image/png;base64,${e.imageB64}`} alt="history" className="w-full aspect-square object-cover" />
                  ) : (
                    <div className="w-full aspect-square flex flex-col items-center justify-center gap-1 bg-accent-lo text-accent">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-7 h-7"><rect x="3" y="3" width="8" height="8" rx="1" /><rect x="13" y="8" width="8" height="8" rx="1" /></svg>
                      <span className="text-[10px] font-medium">boxes only</span>
                    </div>
                  )}
                </button>
                <span className="absolute top-1 left-1 px-1.5 py-0.5 rounded bg-ink/70 text-white text-[9px] font-medium">{boxes} {boxes === 1 ? "box" : "boxes"}</span>
                {e.autosave && <span className="absolute bottom-1 left-1 px-1.5 py-0.5 rounded bg-accent/80 text-white text-[9px] font-medium">autosaved</span>}
                <div className="px-2 py-1.5">
                  <div className="text-[11px] text-ink-2 truncate">{e.prompt || "(manual boxes)"}</div>
                  <div className="text-[10px] text-ink-3">{new Date(e.ts).toLocaleString()}</div>
                </div>
                <div className="absolute top-1 right-1 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {e.imageB64 && (
                    <button type="button" onClick={() => downloadPng(e.imageB64, `${slug(e.prompt)}.png`)} title="Download PNG" className="w-6 h-6 rounded bg-raised/90 text-ink-2 hover:text-accent flex items-center justify-center shadow">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" /></svg>
                    </button>
                  )}
                  <button type="button" onClick={() => onDelete(e.id)} title="Delete" className="w-6 h-6 rounded bg-raised/90 text-ink-2 hover:text-coral flex items-center justify-center shadow">✕</button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function IdeogramChat() {
  const [session, setSession] = useState<SessionState>("starting");
  const [sessionDetail, setSessionDetail] = useState("");
  const magicAvailable = true;

  const [prompt, setPrompt] = useState("");
  const [magicModel, setMagicModel] = useState<"gemma" | "claude">("gemma");
  const [caption, setCaption] = useState<IdeogramCaption>(EMPTY);
  const [selected, setSelected] = useState<number | null>(null);

  const [imageB64, setImageB64] = useState<string | null>(null);
  const [seed, setSeed] = useState(42);
  const [preset, setPreset] = useState<IdeogramPreset>("V4_DEFAULT_20");
  const [res, setRes] = useState<Resolution>(RESOLUTIONS[0]);
  const [aspectLock, setAspectLock] = useState(false);
  const lockRatio = useRef(1); // w/h captured when the lock is engaged

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showStyle, setShowStyle] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  // Right pane: drag-resizable width (persisted), full-collapse, and a
  // collapse-all/expand-all signal for the box cards.
  const [rightWidth, setRightWidth] = useState(() => {
    try { return clamp(parseInt(localStorage.getItem("ideogram-right-width") || "", 10) || 440, 320, 900); } catch { return 440; }
  });
  const [paneOpen, setPaneOpen] = useState(true);
  const [collapseAll, setCollapseAll] = useState({ v: false, n: 0 });
  // Canvas tools: draw-new-box mode, visible grid + snap step, box-overlay toggle.
  const [drawMode, setDrawMode] = useState(false);
  const [showGrid, setShowGrid] = useState(false);
  const [gridStep, setGridStep] = useState(50); // 0–1000 units between grid lines
  const [showBoxes, setShowBoxes] = useState(true);
  const dragging = useRef(false);
  const startPaneDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    let latest = rightWidth;
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      latest = clamp(window.innerWidth - ev.clientX, 320, 900);
      setRightWidth(latest);
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      try { localStorage.setItem("ideogram-right-width", String(latest)); } catch { /* ignore */ }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };
  const lastPrompt = useRef("");
  // Stable id for the rolling auto-saved draft (one per browser, survives reloads).
  const [draftId] = useState(() => {
    try {
      const KEY = "papermanager-ideogram-draft-id";
      let id = localStorage.getItem(KEY);
      if (!id) { id = newId(); localStorage.setItem(KEY, id); }
      return id;
    } catch { return "ideogram-draft"; }
  });

  // ── Undo / redo (caption edits) ──────────────────────────────────────────────
  const past = useRef<IdeogramCaption[]>([]);
  const future = useRef<IdeogramCaption[]>([]);
  const captionRef = useRef(caption);
  const selectedRef = useRef(selected);
  const [hist, setHist] = useState({ u: false, r: false });
  useEffect(() => { captionRef.current = caption; }, [caption]);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  const syncHist = () => setHist({ u: past.current.length > 0, r: future.current.length > 0 });
  const pushPast = useCallback(() => {
    past.current = [...past.current.slice(-49), captionRef.current];
    future.current = [];
    syncHist();
  }, []);
  // commit = record history, then apply a caption update (for discrete edits).
  const commit = useCallback((updater: (c: IdeogramCaption) => IdeogramCaption) => {
    pushPast();
    setCaption(updater);
  }, [pushPast]);
  const undo = useCallback(() => {
    if (!past.current.length) return;
    const prev = past.current[past.current.length - 1];
    past.current = past.current.slice(0, -1);
    future.current = [captionRef.current, ...future.current].slice(0, 50);
    captionRef.current = prev;
    setCaption(prev);
    syncHist();
  }, []);
  const redo = useCallback(() => {
    if (!future.current.length) return;
    const next = future.current[0];
    future.current = future.current.slice(1);
    past.current = [...past.current, captionRef.current].slice(-50);
    captionRef.current = next;
    setCaption(next);
    syncHist();
  }, []);

  const refreshHistory = useCallback(() => {
    listGenerations().then(setHistory).catch(() => {});
  }, []);

  const startSession = useCallback(async () => {
    setSession("starting"); setSessionDetail("");
    try {
      const s = await startIdeogramSession();
      setSession((s.status as SessionState) ?? "starting");
    } catch (e) {
      setSession("error"); setSessionDetail(String(e));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    refreshHistory();
    (async () => {
      try {
        const s = await startIdeogramSession();
        if (alive) setSession((s.status as SessionState) ?? "starting");
      } catch (e) {
        if (alive) { setSession("error"); setSessionDetail(String(e)); }
      }
      timer = setInterval(async () => {
        try {
          const s = await getIdeogramStatus();
          if (!alive) return;
          setSession((s.status as SessionState) ?? "stopped");
          if (s.error_message) setSessionDetail(s.error_message);
        } catch { /* keep last */ }
      }, 5000);
    })();
    return () => {
      alive = false;
      if (timer) clearInterval(timer);
      stopIdeogramSession().catch(() => {});
    };
  }, [refreshHistory]);

  // Warn before closing the tab mid-work (a generated image would be lost, and the
  // GPU is torn down on unload).
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (imageB64) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [imageB64]);

  const elements = caption.compositional_deconstruction.elements;
  const canGenerate = session === "ready" && !busy;

  const updateElement = (i: number, el: IdeogramElement) =>
    commit((c) => {
      const els = [...c.compositional_deconstruction.elements];
      els[i] = el;
      return { ...c, compositional_deconstruction: { ...c.compositional_deconstruction, elements: els } };
    });
  // Continuous drag: no per-move history (pushPast fires once at gesture start).
  const moveBbox = (i: number, bbox: Bbox) =>
    setCaption((c) => {
      const els = [...c.compositional_deconstruction.elements];
      els[i] = { ...els[i], bbox };
      return { ...c, compositional_deconstruction: { ...c.compositional_deconstruction, elements: els } };
    });
  const addElement = () => {
    commit((c) => ({ ...c, compositional_deconstruction: { ...c.compositional_deconstruction, elements: [...c.compositional_deconstruction.elements, { type: "object", bbox: [400, 400, 600, 600], desc: "" }] } }));
    setSelected(elements.length);
  };
  const createBox = (bbox: Bbox) => {
    commit((c) => ({ ...c, compositional_deconstruction: { ...c.compositional_deconstruction, elements: [...c.compositional_deconstruction.elements, { type: "object", bbox, desc: "" }] } }));
    setSelected(elements.length);
  };
  const duplicateElement = (i: number) => {
    commit((c) => {
      const els = [...c.compositional_deconstruction.elements];
      const src = els[i];
      if (!src) return c;
      const [y0, x0, y1, x1] = src.bbox;
      const oy = Math.min(40, 1000 - y1), ox = Math.min(40, 1000 - x1);
      els.splice(i + 1, 0, { ...src, color_palette: src.color_palette ? [...src.color_palette] : undefined, bbox: [y0 + oy, x0 + ox, y1 + oy, x1 + ox] });
      return { ...c, compositional_deconstruction: { ...c.compositional_deconstruction, elements: els } };
    });
    setSelected(i + 1);
  };
  const removeElement = (i: number) => {
    commit((c) => ({ ...c, compositional_deconstruction: { ...c.compositional_deconstruction, elements: c.compositional_deconstruction.elements.filter((_, j) => j !== i) } }));
    setSelected(null);
  };
  // Reorder = change paint order: later in the list draws in FRONT (painter's
  // algorithm). dir +1 brings the box forward, -1 sends it back.
  const reorderElement = (i: number, dir: number) => {
    const j = i + dir;
    if (j < 0 || j >= elements.length) return;
    commit((c) => {
      const els = [...c.compositional_deconstruction.elements];
      [els[i], els[j]] = [els[j], els[i]];
      return { ...c, compositional_deconstruction: { ...c.compositional_deconstruction, elements: els } };
    });
    setSelected(j);
  };
  // Keyboard nudge / resize of the selected box.
  const nudge = useCallback((dx: number, dy: number, resize: boolean) => {
    const sel = selectedRef.current;
    if (sel == null) return;
    commit((c) => {
      const els = [...c.compositional_deconstruction.elements];
      const el = els[sel];
      if (!el) return c;
      let [y0, x0, y1, x1] = el.bbox;
      const MIN = 20;
      if (resize) {
        x1 = clamp(x1 + dx, x0 + MIN, 1000);
        y1 = clamp(y1 + dy, y0 + MIN, 1000);
      } else {
        const w = x1 - x0, h = y1 - y0;
        x0 = clamp(x0 + dx, 0, 1000 - w); y0 = clamp(y0 + dy, 0, 1000 - h); x1 = x0 + w; y1 = y0 + h;
      }
      els[sel] = { ...el, bbox: [Math.round(y0), Math.round(x0), Math.round(y1), Math.round(x1)] };
      return { ...c, compositional_deconstruction: { ...c.compositional_deconstruction, elements: els } };
    });
  }, [commit]);

  // Global keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const ae = document.activeElement as HTMLElement | null;
      const tag = ae?.tagName.toLowerCase();
      const typing = tag === "input" || tag === "textarea" || tag === "select" || ae?.isContentEditable;
      const meta = e.metaKey || e.ctrlKey;
      if (meta && (e.key === "z" || e.key === "Z")) { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
      if (meta && (e.key === "y" || e.key === "Y")) { e.preventDefault(); redo(); return; }
      if (e.key === "Escape") { setDrawMode(false); return; }
      if (typing) return;
      const sel = selectedRef.current;
      if (sel == null) return;
      const step = e.shiftKey ? 10 : 1;
      const rz = e.altKey;
      if (e.key === "ArrowLeft") { e.preventDefault(); nudge(-step, 0, rz); }
      else if (e.key === "ArrowRight") { e.preventDefault(); nudge(step, 0, rz); }
      else if (e.key === "ArrowUp") { e.preventDefault(); nudge(0, -step, rz); }
      else if (e.key === "ArrowDown") { e.preventDefault(); nudge(0, step, rz); }
      else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeElement(sel); }
      else if (e.key === "d" || e.key === "D") { e.preventDefault(); duplicateElement(sel); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [undo, redo, nudge]);

  const runGenerate = useCallback(async (useSeed: number) => {
    setBusy(true); setError(null);
    try {
      // Send the boxes EXACTLY as shown on screen.
      const sent = caption;
      const result = await ideogramGenerate({ caption_json: sent, width: snap16(res.w), height: snap16(res.h), seed: useSeed, sampler_preset: preset });
      setImageB64(result.image_base64);
      setSeed(result.seed);
      // If the server returns the caption the model actually used (normalized /
      // adjusted), adopt it — it's the more accurate description of the result.
      // Guard against an empty/malformed response wiping the boxes.
      const srv = result.caption;
      const valid = !!srv && typeof srv !== "string" && Array.isArray(srv.compositional_deconstruction?.elements) && srv.compositional_deconstruction.elements.length > 0;
      const finalCaption = valid ? srv : sent;
      if (valid) setCaption(srv);
      try {
        await saveGeneration({ id: newId(), ts: Date.now(), prompt: lastPrompt.current, caption: finalCaption, imageB64: result.image_base64, seed: result.seed, preset, width: snap16(res.w), height: snap16(res.h), magicModel });
        refreshHistory();
      } catch { /* history is best-effort */ }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [caption, res, preset, magicModel, refreshHistory]);

  const regenerateBox = () => runGenerate(seed);
  const regenerateAll = () => { const s = randomSeed(); setSeed(s); runGenerate(s); };

  // Manually snapshot the current boxes + settings (and the image if there is
  // one) into history — lets you keep a permanent, separate copy.
  const saveSnapshot = useCallback(async () => {
    try {
      await saveGeneration({ id: newId(), ts: Date.now(), prompt: lastPrompt.current || prompt, caption, imageB64: imageB64 ?? "", seed, preset, width: snap16(res.w), height: snap16(res.h), magicModel });
      refreshHistory();
    } catch { /* history is best-effort */ }
  }, [caption, imageB64, seed, preset, res, prompt, magicModel, refreshHistory]);

  // Autosave: whenever the boxes / settings change, persist the current working
  // state into a single rolling draft entry (debounced) so nothing is ever lost,
  // without spamming a new entry per edit. Generations keep their own entries.
  useEffect(() => {
    if (!elements.length) return; // nothing worth saving yet
    const t = setTimeout(() => {
      saveGeneration({ id: draftId, ts: Date.now(), prompt: lastPrompt.current || prompt, caption, imageB64: imageB64 ?? "", seed, preset, width: snap16(res.w), height: snap16(res.h), magicModel, autosave: true })
        .then(refreshHistory)
        .catch(() => { /* history is best-effort */ });
    }, 900);
    return () => clearTimeout(t);
  }, [caption, imageB64, seed, preset, res, prompt, magicModel, elements.length, draftId, refreshHistory]);

  const expandPrompt = async () => {
    if (!prompt.trim()) return;
    setBusy(true); setError(null);
    try {
      const { caption: c } = await ideogramMagicPrompt(prompt, snap16(res.w), snap16(res.h), magicModel);
      if (c && typeof c !== "string") { commit(() => c); setSelected(c.compositional_deconstruction?.elements?.length ? 0 : null); lastPrompt.current = prompt; }
      else setError("Couldn't turn that prompt into boxes — try rephrasing.");
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };

  const restore = (e: HistoryEntry) => {
    commit(() => e.caption); setImageB64(e.imageB64 || null); setSeed(e.seed);
    setPreset(e.preset as IdeogramPreset);
    setRes(RESOLUTIONS.find((x) => x.w === e.width && x.h === e.height) ?? { label: "Custom", w: e.width, h: e.height });
    if (e.magicModel) setMagicModel(e.magicModel);
    lastPrompt.current = e.prompt; setPrompt(e.prompt);
    setSelected(e.caption.compositional_deconstruction.elements.length ? 0 : null);
    setHistoryOpen(false);
  };

  // ── Custom resolution helpers ────────────────────────────────────────────────
  const isCustom = res.label === "Custom";
  const toggleLock = () => { setAspectLock((v) => { if (!v) lockRatio.current = res.w / res.h; return !v; }); };
  const setCustomW = (raw: number, snap: boolean) => {
    const w = snap ? snap16(raw) : clamp(raw || 0, 0, 2048);
    setRes(() => (aspectLock ? { label: "Custom", w, h: snap16(w / lockRatio.current) } : { label: "Custom", w, h: res.h }));
  };
  const setCustomH = (raw: number, snap: boolean) => {
    const h = snap ? snap16(raw) : clamp(raw || 0, 0, 2048);
    setRes(() => (aspectLock ? { label: "Custom", w: snap16(h * lockRatio.current), h } : { label: "Custom", w: res.w, h }));
  };
  const swapWH = () => { lockRatio.current = res.h / res.w; setRes((r) => ({ label: "Custom", w: r.h, h: r.w })); };
  const pickChip = (w: number, h: number) => { lockRatio.current = w / h; setRes({ label: "Custom", w, h }); };
  const snappedW = snap16(res.w), snappedH = snap16(res.h);
  const sizeDiffers = snappedW !== res.w || snappedH !== res.h;

  const btnPrimary = "px-3 py-1.5 rounded-lg text-sm font-medium bg-accent text-white hover:bg-violet-700 disabled:opacity-40";
  const btnSecondary = "px-3 py-1.5 rounded-lg text-sm border border-line text-ink-2 hover:border-accent-border hover:text-accent disabled:opacity-40";
  const inputCls = "border border-line rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 bg-raised";
  const iconBtn = "w-8 h-8 flex items-center justify-center rounded-lg border border-line text-ink-2 hover:border-accent-border hover:text-accent disabled:opacity-30";

  return (
    <div className="h-full flex flex-col bg-base">
      {/* Header */}
      <header className="px-6 py-3 border-b border-line bg-raised flex items-center gap-3">
        <span className="text-lg">🎨</span>
        <h1 className="font-semibold text-ink">Ideogram Chat</h1>
        <StatusPill state={session} detail={sessionDetail} />
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={undo} disabled={!hist.u} title="Undo (⌘Z)" className={iconBtn}>↶</button>
          <button type="button" onClick={redo} disabled={!hist.r} title="Redo (⇧⌘Z)" className={iconBtn}>↷</button>
          <button type="button" onClick={saveSnapshot} disabled={!elements.length} title="Save current boxes & settings to history" className={btnSecondary}>Save</button>
          <button type="button" onClick={() => setPaneOpen((v) => !v)} title={paneOpen ? "Hide the boxes panel" : "Show the boxes panel"} className={iconBtn}>
            {paneOpen
              ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></svg>
              : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16M18 9l2 3-2 3" /></svg>}
          </button>
          <button type="button" onClick={() => { refreshHistory(); setHistoryOpen(true); }} className={btnSecondary}>History</button>
          <button type="button" onClick={() => imageB64 && downloadPng(imageB64, `${slug(lastPrompt.current)}.png`)} disabled={!imageB64} className={btnSecondary}>Export PNG</button>
        </div>
      </header>

      {/* GPU asleep / error banner — boxes are safe, offer to spin back up. */}
      {(session === "stopped" || session === "error") && (
        <div className="px-6 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber flex items-center gap-3">
          <span>⚠️ GPU is {session === "error" ? "in an error state" : "asleep"} — your boxes and settings are kept. Spin it back up to generate.</span>
          <button type="button" onClick={startSession} className="px-2 py-1 rounded-lg bg-amber text-white hover:opacity-90">Spin GPU back up</button>
        </div>
      )}

      <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
        {/* Left: prompt + image */}
        <div className="min-h-0 flex-1 min-w-0 overflow-auto p-5 flex flex-col gap-4">
          {/* Prompt card */}
          <div className="rounded-xl border border-line bg-raised p-4 shadow-sm">
            <label className="block text-xs font-semibold text-ink-2 mb-1.5">Describe your image</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={2}
              placeholder="e.g. a motivational poster that says RUN FAST with a lightning bolt"
              className="w-full text-sm border border-line rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-violet-300"
            />
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <button type="button" onClick={expandPrompt} disabled={busy || !magicAvailable || !prompt.trim()} className={btnPrimary}>
                ✨ Expand into boxes
              </button>
              <label className="text-xs text-ink-3">via</label>
              <select value={magicModel} onChange={(e) => setMagicModel(e.target.value as "gemma" | "claude")} className={inputCls}>
                <option value="gemma">Gemma · local</option>
                <option value="claude">Claude · best</option>
              </select>
            </div>
          </div>

          {/* Image hero */}
          <div className="flex-1 flex flex-col items-center justify-center min-h-0">
            {/* Canvas tools */}
            <div className="w-full max-w-full flex items-center gap-2 mb-2 flex-wrap">
              <button type="button" onClick={() => { setDrawMode((v) => !v); if (!drawMode) setSelected(null); }} title="Draw new boxes by dragging on the canvas (even over existing boxes)" className={`text-xs px-2 py-1 rounded-lg border ${drawMode ? "border-accent bg-accent text-white" : "border-line text-ink-2 hover:border-accent-border hover:text-accent"}`}>✏️ Draw box</button>
              <button type="button" onClick={() => setShowGrid((v) => !v)} title="Show a grid and snap to it" className={`text-xs px-2 py-1 rounded-lg border ${showGrid ? "border-accent bg-accent text-white" : "border-line text-ink-2 hover:border-accent-border hover:text-accent"}`}>▦ Grid</button>
              {showGrid && (
                <select value={gridStep} onChange={(e) => setGridStep(parseInt(e.target.value, 10))} title="Grid spacing" className="text-xs border border-line rounded px-1.5 py-1 bg-raised focus:outline-none focus:ring-2 focus:ring-violet-300">
                  <option value={25}>fine · 25</option>
                  <option value={50}>medium · 50</option>
                  <option value={100}>coarse · 100</option>
                </select>
              )}
              <button type="button" onClick={() => setShowBoxes((v) => !v)} title="Show or hide the box overlays on the image" className={`text-xs px-2 py-1 rounded-lg border ${showBoxes ? "border-line text-ink-2 hover:border-accent-border hover:text-accent" : "border-accent bg-accent text-white"}`}>{showBoxes ? "👁 Boxes shown" : "🚫 Boxes hidden"}</button>
            </div>
            <ImageCanvas
              imageB64={imageB64} elements={elements} selected={selected}
              onSelect={setSelected} onMoveBbox={moveBbox} onDragStart={pushPast} onCreateBox={createBox}
              aspect={snap16(res.w) / snap16(res.h)} busy={busy}
              drawMode={drawMode} showGrid={showGrid} gridStep={gridStep} showBoxes={showBoxes}
            />
            <p className="mt-2 text-[11px] text-ink-3 text-center">
              {drawMode ? <b>Draw mode: drag anywhere to create a box.</b> : "Drag to move · corners/edges to resize · draw on empty space to add · click again to cycle overlapping boxes"} · ⌥arrows resize · hold ⌥ to disable snapping · ⌘Z undo
            </p>
          </div>

          {error && <div className="text-xs text-coral bg-red-50 border border-red-200 rounded-lg px-3 py-2 whitespace-pre-wrap">{error}</div>}

          {/* Generate toolbar */}
          <div className="rounded-xl border border-line bg-raised p-3 flex items-center gap-2 flex-wrap shadow-sm">
            <select value={preset} onChange={(e) => setPreset(e.target.value as IdeogramPreset)} className={inputCls}>
              {PRESETS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
            <select
              value={res.label}
              onChange={(e) => {
                if (e.target.value === "Custom") setRes((r) => ({ label: "Custom", w: r.w, h: r.h }));
                else setRes(RESOLUTIONS.find((r) => r.label === e.target.value) ?? RESOLUTIONS[0]);
              }}
              className={inputCls}
            >
              {RESOLUTIONS.map((r) => <option key={r.label} value={r.label}>{r.label}</option>)}
              <option value="Custom">Custom…</option>
            </select>
            {isCustom && (
              <>
                <div className="flex items-center gap-1">
                  <input
                    type="number" min={256} max={2048} step={16} value={res.w} aria-label="width"
                    onChange={(e) => setCustomW(parseInt(e.target.value, 10), false)}
                    onBlur={(e) => setCustomW(parseInt(e.target.value, 10), true)}
                    className={`w-20 font-mono ${inputCls}`}
                  />
                  <span className="text-ink-3 text-xs">×</span>
                  <input
                    type="number" min={256} max={2048} step={16} value={res.h} aria-label="height"
                    onChange={(e) => setCustomH(parseInt(e.target.value, 10), false)}
                    onBlur={(e) => setCustomH(parseInt(e.target.value, 10), true)}
                    className={`w-20 font-mono ${inputCls}`}
                  />
                  <button type="button" onClick={toggleLock} title="Lock aspect ratio" className={`${iconBtn} ${aspectLock ? "border-accent text-accent" : ""}`}>{aspectLock ? "🔒" : "🔗"}</button>
                  <button type="button" onClick={swapWH} title="Swap width / height" className={iconBtn}>⇄</button>
                </div>
                {sizeDiffers && <span className="text-[11px] text-ink-3">→ {snappedW}×{snappedH}</span>}
                <div className="flex items-center gap-1 flex-wrap">
                  {RATIO_CHIPS.map((c) => (
                    <button key={c.label} type="button" onClick={() => pickChip(c.w, c.h)} className="text-[11px] px-1.5 py-0.5 rounded border border-line text-ink-2 hover:border-accent-border hover:text-accent">{c.label}</button>
                  ))}
                </div>
              </>
            )}
            <label className="flex items-center gap-1 text-xs text-ink-3">seed
              <input type="number" value={seed} onChange={(e) => setSeed(parseInt(e.target.value, 10) || 0)} className={`w-20 font-mono ${inputCls}`} />
            </label>
            <div className="ml-auto flex items-center gap-2">
              <button type="button" onClick={regenerateBox} disabled={!canGenerate} className={btnPrimary}>{busy ? "Generating…" : "Generate"}</button>
              <button type="button" onClick={regenerateAll} disabled={!canGenerate} title="New random seed" className={btnSecondary}>Regenerate all</button>
            </div>
          </div>
        </div>

        {/* Drag handle — resize the right pane (lg only). */}
        {paneOpen && (
          <div onMouseDown={startPaneDrag} title="Drag to resize" className="hidden lg:flex shrink-0 w-2 cursor-col-resize group items-stretch justify-center">
            <div className="w-px h-full bg-line group-hover:bg-accent transition-colors" />
          </div>
        )}

        {/* Collapsed rail — click to reopen the pane (lg only). */}
        {!paneOpen && (
          <button type="button" onClick={() => setPaneOpen(true)} title="Show the boxes panel" className="hidden lg:flex shrink-0 w-8 border-l border-line bg-base hover:bg-accent-lo text-ink-3 hover:text-accent flex-col items-center justify-center gap-2">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4"><path d="m15 6-6 6 6 6" /></svg>
            <span className="text-[10px] font-medium [writing-mode:vertical-rl] rotate-180">Boxes ({elements.length})</span>
          </button>
        )}

        {/* Right: boxes + style */}
        {paneOpen && (
        <aside style={{ "--rw": `${rightWidth}px` } as React.CSSProperties} className="min-h-0 w-full lg:w-[var(--rw)] shrink-0 overflow-auto border-t lg:border-t-0 lg:border-l border-line bg-base p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-ink shrink-0">Boxes <span className="text-ink-3 font-normal">({elements.length})</span></h2>
            <div className="flex gap-2 flex-wrap justify-end">
              {elements.length > 0 && (
                <button type="button" onClick={() => setCollapseAll((s) => ({ v: !s.v, n: s.n + 1 }))} title="Collapse or expand all box fields" className="text-xs px-2 py-1 rounded-lg border border-line text-ink-2 hover:border-accent-border hover:text-accent">{collapseAll.v ? "Expand all" : "Collapse all"}</button>
              )}
              <button type="button" onClick={() => { commit(() => EMPTY); setSelected(null); }} disabled={!elements.length} className="text-xs px-2 py-1 rounded-lg border border-line text-ink-2 hover:border-accent-border hover:text-coral disabled:opacity-40">Clear</button>
              <button type="button" onClick={() => commit(() => TEMPLATE)} className="text-xs px-2 py-1 rounded-lg border border-line text-ink-2 hover:border-accent-border hover:text-accent">Template</button>
              <button type="button" onClick={addElement} className="text-xs px-2 py-1 rounded-lg bg-ink text-white hover:opacity-90">+ Add box</button>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            {elements.length === 0 && <p className="text-xs text-ink-3 py-6 text-center">No boxes yet — draw on the canvas, click <b>+ Add box</b>, or <b>Template</b>.</p>}
            {elements.map((el, i) => (
              <ElementCard
                key={i} el={el} index={i} count={elements.length} selected={selected === i}
                collapseDefault={collapseAll.v} collapseKey={collapseAll.n}
                onSelect={() => setSelected(i)}
                onChange={(next) => updateElement(i, next)}
                onRemove={() => removeElement(i)}
                onDuplicate={() => duplicateElement(i)}
                onReorder={(dir) => reorderElement(i, dir)}
                onRegenerate={regenerateBox}
                busy={!canGenerate}
              />
            ))}
          </div>

          {/* Style */}
          <div className="rounded-xl border border-line bg-raised">
            <button type="button" onClick={() => setShowStyle((v) => !v)} className="w-full px-3 py-2 flex items-center justify-between text-xs font-semibold text-ink-2">
              Style &amp; background
              <span className="text-ink-3">{showStyle ? "▲" : "▼"}</span>
            </button>
            {showStyle && (
              <div className="px-3 pb-3 flex flex-col gap-2">
                <textarea rows={2} value={caption.high_level_description ?? ""} onChange={(e) => commit((c) => ({ ...c, high_level_description: e.target.value }))} placeholder="High-level description" className="w-full text-sm border border-line rounded px-2 py-1.5 resize-y min-h-[2.5rem] focus:outline-none focus:ring-2 focus:ring-violet-300" />
                <textarea rows={2} value={caption.compositional_deconstruction.background} onChange={(e) => commit((c) => ({ ...c, compositional_deconstruction: { ...c.compositional_deconstruction, background: e.target.value } }))} placeholder="Background" className="w-full text-sm border border-line rounded px-2 py-1.5 resize-y min-h-[2.5rem] focus:outline-none focus:ring-2 focus:ring-violet-300" />
                {(["aesthetics", "lighting", "medium", "art_style"] as const).map((k) => (
                  <textarea key={k} rows={2} value={caption.style_description?.[k] ?? ""} onChange={(e) => commit((c) => ({ ...c, style_description: { ...c.style_description, [k]: e.target.value } }))} placeholder={k} className="w-full text-sm border border-line rounded px-2 py-1.5 resize-y min-h-[2.5rem] focus:outline-none focus:ring-2 focus:ring-violet-300" />
                ))}
              </div>
            )}
          </div>

          {imageB64 && (
            <button type="button" onClick={() => downloadJson(caption, `${slug(lastPrompt.current)}-caption.json`)} className="text-xs text-ink-3 hover:text-accent self-start">
              Export caption JSON
            </button>
          )}
        </aside>
        )}
      </div>

      <HistoryDrawer
        open={historyOpen}
        entries={history}
        onClose={() => setHistoryOpen(false)}
        onRestore={restore}
        onDelete={(id) => deleteGeneration(id).then(refreshHistory).catch(() => {})}
        onClear={() => clearHistory().then(refreshHistory).catch(() => {})}
      />
    </div>
  );
}
