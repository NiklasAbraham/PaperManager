/* eslint-disable react-hooks/immutability -- an imperative canvas engine: `eng` is a plain mutable drawing cache (positions, layers), deliberately outside React state */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TopicMapData } from "./api";
import { NEUTRAL, SpatialGrid, placeLabels, rgba, type LabelBox } from "./helpers";

interface Props {
  data: TopicMapData;
  /** Project (map project id) to light up: its papers get a soft coloured bubble, the rest fade. */
  activeProjectId?: string | null;
  /** False: the map is only a picture (variant C before it is hovered). */
  interactive?: boolean;
  onOpenPaper?: (id: string) => void;
  className?: string;
  /** Keep the dots out of the top / bottom strip (the band variant floats cards there). */
  insetTop?: number;
  insetBottom?: number;
  /** Padding (px) around the dots on every side; the label strip variants keep the default. */
  pad?: number;
  /** Fit the dots (their bounding box) into the card, centred, stretch capped at 2:1; default stretches the unit square. */
  fit?: boolean;
}

const PAD_X = 20, PAD_Y = 18, MUTED_INK = "#9ca3af", MAX_ZOOM = 8, CELL = 16, HIT_RADIUS = 8;
const FONT = "600 11px system-ui, 'Segoe UI', Roboto, sans-serif";
const FONT_MUTED = "400 11px system-ui, 'Segoe UI', Roboto, sans-serif";

/** Mutable drawing state (screen positions, caches); lives outside React state so mousemove costs nothing. */
interface Engine {
  w: number; h: number; dpr: number; k: number; tx: number; ty: number;
  sx: Float32Array; sy: Float32Array;
  base: HTMLCanvasElement | null; baseDirty: boolean;
  blob: { key: string; canvas: HTMLCanvasElement } | null;
  sprites: Map<string, HTMLCanvasElement>;
  grid: SpatialGrid | null; gridIds: number[];
  hover: number; raf: number;
  drag: { x: number; y: number; tx: number; ty: number; moved: boolean } | null;
}

function newEngine(): Engine {
  return { w: 0, h: 0, dpr: 1, k: 1, tx: 0, ty: 0, sx: new Float32Array(0), sy: new Float32Array(0),
    base: null, baseDirty: true, blob: null, sprites: new Map(), grid: null, gridIds: [], hover: -1, raf: 0, drag: null };
}

/** Soft round brush (alpha only) that the project density is accumulated with. */
function brush(e: Engine, radius: number): HTMLCanvasElement {
  const key = `brush|${radius}`;
  let c = e.sprites.get(key);
  if (!c) {
    c = document.createElement("canvas");
    c.width = c.height = radius * 2;
    const g = c.getContext("2d");
    if (g) {
      const grad = g.createRadialGradient(radius, radius, 0, radius, radius, radius);
      grad.addColorStop(0, "rgba(0,0,0,0.16)");
      grad.addColorStop(0.45, "rgba(0,0,0,0.08)");
      grad.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = grad;
      g.fillRect(0, 0, radius * 2, radius * 2);
    }
    e.sprites.set(key, c);
  }
  return c;
}

/** Alpha of the project bubble at its densest. */
const PEAK = 0.26;

/** Density -> soft tinted cloud: alpha saturates smoothly instead of piling up to a solid patch. */
function tint(g: CanvasRenderingContext2D, w: number, h: number, color: string) {
  const img = g.getImageData(0, 0, w, h), d = img.data;
  const n = parseInt(color.slice(1), 16), r = (n >> 16) & 255, gr = (n >> 8) & 255, b = n & 255;
  for (let i = 0; i < d.length; i += 4) {
    const a = d[i + 3] / 255;
    d[i] = r; d[i + 1] = gr; d[i + 2] = b;
    d[i + 3] = Math.round(255 * Math.min(PEAK, PEAK * 1.3 * (a / (a + 0.35))));
  }
  g.putImageData(img, 0, 0);
}

export default function TopicMap({ data, activeProjectId = null, interactive = true, onOpenPaper, className = "", insetTop, insetBottom, pad, fit = false }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [eng] = useState(newEngine);
  const [showRefs, setShowRefs] = useState(true);
  const [zoomed, setZoomed] = useState(false);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  // Library papers last so they sit on top of the faint references.
  const model = useMemo(() => {
    const pts = [...data.points.filter((p) => p.r), ...data.points.filter((p) => !p.r)];
    const colorOf = new Map(data.clusters.map((c) => [c.id, c.color]));
    const mutedIds = new Set(data.clusters.filter((c) => c.muted).map((c) => c.id));
    const colors = pts.map((p) => colorOf.get(p.c) ?? NEUTRAL);
    const groups = new Map<string, { color: string; muted: boolean; ref: number[]; lib: number[] }>();
    pts.forEach((p, i) => {
      const muted = mutedIds.has(p.c);
      const key = `${colors[i]}|${muted ? 1 : 0}`;
      const g = groups.get(key) ?? { color: colors[i], muted, ref: [], lib: [] };
      (p.r ? g.ref : g.lib).push(i);
      groups.set(key, g);
    });
    const hasRefs = pts.some((p) => p.r);
    let x0 = 1, x1 = 0, y0 = 1, y1 = 0;
    for (const p of pts) { if (p.x < x0) x0 = p.x; if (p.x > x1) x1 = p.x; if (p.y < y0) y0 = p.y; if (p.y > y1) y1 = p.y; }
    const box = x1 > x0 && y1 > y0 ? { x0, y0, bw: x1 - x0, bh: y1 - y0 } : { x0: 0, y0: 0, bw: 1, bh: 1 };
    return { pts, colors, groups: [...groups.values()], hasRefs, box };
  }, [data]);

  const projIndex = useMemo(() => data.projects.findIndex((p) => p.id === activeProjectId), [data.projects, activeProjectId]);
  const refsOn = showRefs && model.hasRefs;

  // Everything drawn is derived from `eng` + the props below; `draw` is the only writer of the canvas.
  const padX = pad ?? PAD_X, padY = pad ?? PAD_Y;
  const top = insetTop ?? padY, bottom = insetBottom ?? padY;
  const latest = useRef({ model, projIndex, refsOn, data, insetTop: top, insetBottom: bottom, padX, fit });
  useEffect(() => { latest.current = { model, projIndex, refsOn, data, insetTop: top, insetBottom: bottom, padX, fit }; });

  /** Unit-square coordinates -> unzoomed card pixels (stretched, or aspect-preserving fit of the bounding box, centred). */
  const place = useCallback((x: number, y: number) => {
    const { insetTop: pt, insetBottom: pb, padX: px, fit: f, model: m } = latest.current;
    const aw = eng.w - 2 * px, ah = eng.h - pt - pb;
    if (!f) return { x: px + x * aw, y: pt + y * ah };
    const { x0, y0, bw, bh } = m.box;
    // The layout has no true aspect (axes are normalised): stretch to the card, but at most 2:1 so clusters keep their shape.
    let kx = aw / bw, ky = ah / bh;
    if (kx > 2 * ky) kx = 2 * ky; else if (ky > 2 * kx) ky = 2 * kx;
    return { x: px + (aw - bw * kx) / 2 + (x - x0) * kx, y: pt + (ah - bh * ky) / 2 + (y - y0) * ky };
  }, [eng]);

  const project = useCallback(() => {
    const { pts } = latest.current.model;
    if (eng.sx.length !== pts.length) { eng.sx = new Float32Array(pts.length); eng.sy = new Float32Array(pts.length); }
    for (let i = 0; i < pts.length; i++) {
      const q = place(pts[i].x, pts[i].y);
      eng.sx[i] = q.x * eng.k + eng.tx;
      eng.sy[i] = q.y * eng.k + eng.ty;
    }
  }, [eng, place]);

  const dotR = useCallback(() => {
    const s = Math.min(2.2, Math.sqrt(eng.k));
    return { lib: 2.7 * s, ref: 1.15 * s };
  }, [eng]);

  const drawBase = useCallback(() => {
    const { model: m, refsOn: refs } = latest.current;
    if (!eng.base) eng.base = document.createElement("canvas");
    const c = eng.base;
    c.width = Math.max(1, Math.round(eng.w * eng.dpr)); c.height = Math.max(1, Math.round(eng.h * eng.dpr));
    const g = c.getContext("2d");
    if (!g) return;
    g.setTransform(eng.dpr, 0, 0, eng.dpr, 0, 0);
    const r = dotR();
    const inView = (i: number) => eng.sx[i] > -4 && eng.sx[i] < eng.w + 4 && eng.sy[i] > -4 && eng.sy[i] < eng.h + 4;
    if (refs) {
      for (const grp of m.groups) {
        const rr = grp.muted ? r.ref * 0.8 : r.ref;
        g.beginPath();
        for (const i of grp.ref) if (inView(i)) { g.moveTo(eng.sx[i] + rr, eng.sy[i]); g.arc(eng.sx[i], eng.sy[i], rr, 0, 6.2832); }
        g.fillStyle = rgba(grp.color, grp.muted ? 0.18 : 0.3);
        g.fill();
      }
    }
    for (const grp of m.groups) {
      const rl = grp.muted ? r.lib * 0.7 : r.lib;
      g.beginPath();
      for (const i of grp.lib) if (inView(i)) { g.moveTo(eng.sx[i] + rl, eng.sy[i]); g.arc(eng.sx[i], eng.sy[i], rl, 0, 6.2832); }
      g.fillStyle = rgba(grp.color, grp.muted ? 0.5 : 0.92);
      g.fill();
      g.lineWidth = 0.8;
      g.strokeStyle = grp.muted ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.85)";
      g.stroke();
    }
    eng.baseDirty = false;
  }, [eng, dotR]);

  const blobFor = useCallback((): HTMLCanvasElement | null => {
    const { model: m, projIndex: pi, data: d } = latest.current;
    if (pi < 0) return null;
    const key = `${pi}|${eng.k}|${eng.tx}|${eng.ty}|${eng.w}|${eng.h}|${m.pts.length}`;
    if (eng.blob?.key === key) return eng.blob.canvas;
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(eng.w / 2)); c.height = Math.max(1, Math.round(eng.h / 2));
    const g = c.getContext("2d");
    if (g) {
      // Kernel ~3 % of the shorter canvas side (more for sparse projects), in half-resolution pixels.
      const members = d.projects[pi].count || 0;
      const sparse = members < 25 ? 1.7 : members < 80 ? 1.35 : 1;
      const radius = Math.max(5, Math.round(0.03 * Math.min(eng.w, eng.h) * sparse * Math.min(2.5, Math.sqrt(eng.k)) / 2));
      const sp = brush(eng, radius);
      m.pts.forEach((p, i) => {
        if (!p.r && p.p.includes(pi)) g.drawImage(sp, eng.sx[i] / 2 - radius, eng.sy[i] / 2 - radius);
      });
      tint(g, c.width, c.height, d.projects[pi].color);
    }
    eng.blob = { key, canvas: c };
    return c;
  }, [eng]);

  const compose = useCallback(() => {
    const cv = canvasRef.current;
    const g = cv?.getContext("2d");
    if (!cv || !g || eng.w < 2) return;
    const { model: m, projIndex: pi, data: d } = latest.current;
        if (eng.baseDirty) { project(); drawBase(); }
    g.setTransform(eng.dpr, 0, 0, eng.dpr, 0, 0);
    g.clearRect(0, 0, eng.w, eng.h);
    const blob = blobFor();
    if (blob) {
      g.save();
      g.filter = "blur(3px)";
      g.drawImage(blob, 0, 0, eng.w, eng.h);
      g.restore();
    }
    if (eng.base) { g.globalAlpha = pi >= 0 ? 0.15 : 1; g.drawImage(eng.base, 0, 0, eng.w, eng.h); g.globalAlpha = 1; }
    const r = dotR();
    if (pi >= 0) {
      for (let i = 0; i < m.pts.length; i++) {
        const p = m.pts[i];
        if (p.r || !p.p.includes(pi)) continue;
        g.beginPath(); g.arc(eng.sx[i], eng.sy[i], r.lib + 0.8, 0, 6.2832);
        g.fillStyle = m.colors[i]; g.fill();
        g.lineWidth = 1; g.strokeStyle = "#fff"; g.stroke();
      }
    }
    if (eng.hover >= 0) {
      const i = eng.hover;
      g.beginPath(); g.arc(eng.sx[i], eng.sy[i], (m.pts[i].r ? r.ref : r.lib) + 3.2, 0, 6.2832);
      g.fillStyle = "rgba(255,255,255,0.95)"; g.fill();
      g.lineWidth = 1.6; g.strokeStyle = m.colors[i]; g.stroke();
      g.beginPath(); g.arc(eng.sx[i], eng.sy[i], (m.pts[i].r ? r.ref : r.lib) + 0.6, 0, 6.2832);
      g.fillStyle = m.colors[i]; g.fill();
    }
    // Cluster labels: text with a white halo, biggest first, an overlapping one is skipped.
    const small = eng.w < 380;
    const fontFor = (muted: boolean) => (muted ? FONT_MUTED : FONT).replace("11px", small ? "10px" : "11px");
    g.textAlign = "center"; g.textBaseline = "middle";
    const boxes: (LabelBox & { muted: boolean })[] = d.clusters.map((c) => {
      const text = c.label;
      g.font = fontFor(!!c.muted);
      const w = g.measureText(text).width + 8, h = 15;
      const q = place(c.x, c.y);
      const x = Math.min(eng.w - w / 2 - 2, Math.max(w / 2 + 2, q.x * eng.k + eng.tx));
      const y = Math.min(eng.h - h / 2 - 2, Math.max(h / 2 + 2, q.y * eng.k + eng.ty));
      return { text, x, y, w, h, weight: c.muted ? c.size * 0.01 : c.size, muted: !!c.muted };
    });
    g.lineJoin = "round"; g.lineWidth = 3.5;
    for (const l of placeLabels(boxes)) {
      g.font = fontFor(l.muted);
      g.strokeStyle = "rgba(255,255,255,0.92)"; g.strokeText(l.text, l.x, l.y);
      g.fillStyle = l.muted ? MUTED_INK : "#1f2937"; g.fillText(l.text, l.x, l.y);
    }
  }, [eng, project, drawBase, blobFor, dotR, place]);

  const schedule = useCallback(() => {
    if (eng.raf) return;
    eng.raf = requestAnimationFrame(() => { eng.raf = 0; compose(); });
  }, [eng, compose]);

  const invalidateBase = useCallback(() => {
    eng.baseDirty = true; eng.blob = null; eng.grid = null; schedule();
  }, [eng, schedule]);

  // Size + device pixel ratio.
  useEffect(() => {
    const wrap = wrapRef.current, cv = canvasRef.current;
    if (!wrap || !cv) return;
    const apply = () => {
      const w = wrap.clientWidth, h = wrap.clientHeight, dpr = window.devicePixelRatio || 1;
      if (w === eng.w && h === eng.h && dpr === eng.dpr) return;
      eng.w = w; eng.h = h; eng.dpr = dpr;
      cv.width = Math.max(1, Math.round(w * dpr)); cv.height = Math.max(1, Math.round(h * dpr));
      setSize({ w, h });
      invalidateBase();
    };
    apply();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(apply);
    ro?.observe(wrap);
    return () => { ro?.disconnect(); cancelAnimationFrame(eng.raf); eng.raf = 0; };
  }, [eng, invalidateBase]);

  // Data, references toggle or highlighted project changed.
  useEffect(() => { invalidateBase(); }, [model, refsOn, top, bottom, padX, fit, invalidateBase]);
  useEffect(() => { schedule(); }, [projIndex, schedule]);

  const gridFor = () => {
    if (eng.grid) return eng.grid;
    const { model: m, refsOn: refs } = latest.current;
    const ids: number[] = [];
    m.pts.forEach((p, i) => { if ((!p.r || refs) && eng.sx[i] >= 0 && eng.sx[i] <= eng.w && eng.sy[i] >= 0 && eng.sy[i] <= eng.h) ids.push(i); });
    eng.gridIds = ids;
    eng.grid = new SpatialGrid(ids.map((i) => eng.sx[i]), ids.map((i) => eng.sy[i]), CELL, ids.map((i) => (m.pts[i].r ? 0 : 4)));
    return eng.grid;
  };

  const hit = (x: number, y: number) => {
    const j = gridFor().nearest(x, y, HIT_RADIUS);
    return j < 0 ? -1 : eng.gridIds[j];
  };

  const local = (e: React.PointerEvent | React.MouseEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const setHoverIdx = (i: number, x: number, y: number) => {
    if (i !== eng.hover) { eng.hover = i; schedule(); }
    setHover((h) => (i < 0 ? (h ? null : h) : { i, x, y }));
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!interactive) return;
    const { x, y } = local(e);
    if (eng.drag) {
      const dx = x - eng.drag.x, dy = y - eng.drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) eng.drag.moved = true;
      if (eng.drag.moved) { setView(eng.k, eng.drag.tx + dx, eng.drag.ty + dy); setHoverIdx(-1, 0, 0); }
      return;
    }
    if (e.pointerType === "touch") return;
    setHoverIdx(hit(x, y), x, y);
  };

  const setView = (k: number, tx: number, ty: number) => {
    k = Math.min(MAX_ZOOM, Math.max(1, k));
    eng.k = k;
    eng.tx = Math.min(0, Math.max(eng.w - eng.w * k, tx));
    eng.ty = Math.min(0, Math.max(eng.h - eng.h * k, ty));
    setZoomed(k > 1.001);
    invalidateBase();
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!interactive || e.button !== 0 || e.pointerType === "touch") return;
    const { x, y } = local(e);
    eng.drag = { x, y, tx: eng.tx, ty: eng.ty, moved: false };
    canvasRef.current?.setPointerCapture?.(e.pointerId);
  };

  const onPointerUp = () => { window.setTimeout(() => { eng.drag = null; }, 0); };

  const onClick = (e: React.MouseEvent) => {

    if (!interactive || eng.drag?.moved) return;
    const { x, y } = local(e);
    const touch = (e.nativeEvent as PointerEvent).pointerType === "touch";
    const i = !touch && eng.hover >= 0 ? eng.hover : hit(x, y);   // the dot under the pointer is the one the tooltip shows
    if (i < 0) return;
    if (touch && eng.hover !== i) { setHoverIdx(i, x, y); return; }   // first tap shows the tooltip
    onOpenPaper?.(latest.current.model.pts[i].id);
  };

  // Ctrl/Cmd + wheel (and trackpad pinch) zooms around the cursor; plain wheel keeps scrolling the page.
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !interactive) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const rect = cv.getBoundingClientRect();
      const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
      const k2 = Math.min(MAX_ZOOM, Math.max(1, eng.k * Math.exp(-e.deltaY * 0.01)));
      const bx = (cx - eng.tx) / eng.k, by = (cy - eng.ty) / eng.k;
      eng.k = k2;
      eng.tx = Math.min(0, Math.max(eng.w - eng.w * k2, cx - bx * k2));
      eng.ty = Math.min(0, Math.max(eng.h - eng.h * k2, cy - by * k2));
      setZoomed(k2 > 1.001);
      eng.hover = -1;
      invalidateBase();
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    return () => cv.removeEventListener("wheel", onWheel);
  }, [eng, interactive, invalidateBase]);

  const reset = () => { setView(1, 0, 0); };

  const pt = hover ? model.pts[hover.i] : null;
  const cluster = pt ? data.clusters.find((c) => c.id === pt.c) : null;
  const projNames = pt ? pt.p.map((i) => data.projects[i]?.name).filter(Boolean) : [];
  const flipLeft = hover ? hover.x > size.w * 0.55 : false;

  return (
    <div ref={wrapRef} className={`select-none ${className || "relative h-full w-full"}`}
      onPointerLeave={() => { if (!eng.drag) setHoverIdx(-1, 0, 0); }}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label="Map of all papers by topic"
        className="absolute inset-0 w-full h-full"
        style={{ touchAction: "pan-y", cursor: hover ? "pointer" : zoomed ? "grab" : "default" }}
        onPointerMove={onPointerMove} onPointerDown={onPointerDown} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
        onClick={onClick}
      />
      {interactive && (model.hasRefs || zoomed) && (
        <div className="absolute right-2 top-2 flex items-center gap-1.5">
          {zoomed && (
            <button type="button" onClick={reset}
              className="h-6 px-2 rounded-full bg-raised/90 border border-line text-[11px] text-ink-2 hover:border-accent-border hover:text-accent">
              Reset zoom
            </button>
          )}
          {model.hasRefs && (
            <button type="button" aria-pressed={refsOn} onClick={() => setShowRefs((v) => !v)}
              title="Cited papers without a PDF in your library (faint dots)"
              className={`h-6 px-2 rounded-full border text-[11px] ${refsOn ? "bg-accent-lo border-accent-border text-accent" : "bg-raised/90 border-line text-ink-3 hover:text-ink-2"}`}>
              references
            </button>
          )}
        </div>
      )}
      {interactive && pt && hover && (
        <div
          className="pointer-events-none absolute z-10 w-max max-w-[230px] rounded-lg bg-raised border border-line shadow-lg px-2.5 py-1.5"
          style={{ top: Math.max(4, Math.min(size.h - 70, hover.y + 14)),
                   ...(flipLeft ? { right: size.w - hover.x + 12 } : { left: hover.x + 12 }) }}
        >
          <p className="text-xs font-medium text-ink line-clamp-3">{pt.t}</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-2">
            <span className="inline-block w-2 h-2 rounded-full shrink-0 mt-px" style={{ background: model.colors[hover.i] }} />
            <span>{pt.topic ?? cluster?.label ?? "No topic"}{pt.r ? " · reference" : ""}</span>
          </p>
          {projNames.length > 0 && <p className="text-[11px] text-ink-3">in {projNames.join(", ")}</p>}
        </div>
      )}
    </div>
  );
}
