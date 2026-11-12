/** Pure helpers of the landing dashboard: URL variant, week labels, colours, the spatial hit-test grid and label placement. */
import type { DashProject, MapCluster, MapPoint, MapProject } from "./api";

export type DashVariant = "a" | "b" | "c" | "off";
export const DEFAULT_VARIANT: DashVariant = "b";

/** `?dash=a|b|c|off`; anything else falls back to the default variant. */
export function parseVariant(params: URLSearchParams): DashVariant {
  const v = (params.get("dash") ?? "").toLowerCase();
  return v === "a" || v === "b" || v === "c" || v === "off" ? v : DEFAULT_VARIANT;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-08-24" -> "24 Aug" (no timezone maths: the date is a calendar date). */
export function weekLabel(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? ""}`.trim();
}

export function weekTooltip(week: { week_start: string; count: number }): string {
  return `Week of ${weekLabel(week.week_start)} · ${week.count} paper${week.count === 1 ? "" : "s"}`;
}

export const NEUTRAL = "#9ca3af";

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** Colour of the map cluster whose label matches a topic name (exact, else one contains the other), else null. */
export function topicColor(name: string, all: Pick<MapCluster, "label" | "color" | "muted">[]): string | null {
  const n = norm(name);
  if (!n) return null;
  const clusters = all.filter((c) => !c.muted);
  const exact = clusters.find((c) => norm(c.label) === n);
  if (exact) return exact.color;
  const loose = clusters.find((c) => {
    const l = norm(c.label);
    return l.length >= 4 && n.length >= 4 && (l.includes(n) || n.includes(l));
  });
  return loose?.color ?? null;
}

/** "#rrggbb" + alpha 0..1 -> "rgba(r,g,b,a)". */
export function rgba(hex: string, a: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return `rgba(156,163,175,${a})`;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export interface ReadingSegment { key: "unread" | "reading" | "read"; count: number; share: number }

export function readingSegments(r: { unread: number; reading: number; read: number }): ReadingSegment[] {
  const total = r.unread + r.reading + r.read;
  return (["unread", "reading", "read"] as const).map((key) => ({ key, count: r[key], share: total ? r[key] / total : 0 }));
}

/** Uniform grid over screen positions: nearest point within a radius without scanning every point. */
export class SpatialGrid {
  private cells = new Map<number, number[]>();
  private xs: ArrayLike<number>;
  private ys: ArrayLike<number>;
  private cell: number;
  private bias?: ArrayLike<number>;
  constructor(xs: ArrayLike<number>, ys: ArrayLike<number>, cell = 16, bias?: ArrayLike<number>) {
    this.xs = xs; this.ys = ys; this.cell = cell; this.bias = bias;
    for (let i = 0; i < xs.length; i++) {
      const k = this.key(xs[i], ys[i]);
      const arr = this.cells.get(k);
      if (arr) arr.push(i); else this.cells.set(k, [i]);
    }
  }
  private key(x: number, y: number) {
    return Math.floor(y / this.cell) * 100000 + Math.floor(x / this.cell);
  }
  /** Index of the nearest point within `radius` of (x, y), or -1. `bias[i]` is subtracted from the distance (favours big dots). */
  nearest(x: number, y: number, radius = 8): number {
    const c = this.cell, reach = Math.ceil(radius / c);
    const cx = Math.floor(x / c), cy = Math.floor(y / c);
    let best = -1, bestD = Infinity;
    for (let gy = cy - reach; gy <= cy + reach; gy++) {
      for (let gx = cx - reach; gx <= cx + reach; gx++) {
        const arr = this.cells.get(gy * 100000 + gx);
        if (!arr) continue;
        for (const i of arr) {
          const d = Math.hypot(this.xs[i] - x, this.ys[i] - y);
          if (d > radius) continue;
          const score = d - (this.bias ? this.bias[i] : 0);
          if (score < bestD) { bestD = score; best = i; }
        }
      }
    }
    return best;
  }
}

export interface LabelBox { text: string; x: number; y: number; w: number; h: number; weight: number }

const overlaps = (a: LabelBox, b: LabelBox, pad: number) =>
  Math.abs(a.x - b.x) * 2 < a.w + b.w + pad * 2 && Math.abs(a.y - b.y) * 2 < a.h + b.h + pad * 2;

/** Greedy label placement: biggest first, a label overlapping an already placed one is dropped. Boxes are centred on (x, y). */
export function placeLabels<T extends LabelBox>(labels: T[], pad = 3): T[] {
  const placed: T[] = [];
  for (const l of [...labels].sort((a, b) => b.weight - a.weight)) {
    if (!placed.some((p) => overlaps(l, p, pad))) placed.push(l);
  }
  return placed;
}

/** Points that count as "in a project" for the highlight (indices into the map's project list). */
export const inProject = (p: MapPoint, projectIndex: number) => p.p.includes(projectIndex);

/** Compact number: 1234 -> "1,234". */
export const fmt = (n: number) => n.toLocaleString("en-US");

export const READ_COLORS = { unread: "#cbd5e1", reading: "#eda100", read: "#1baf7a" } as const;
const FALLBACK_PROJECT = ["#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948", "#2a78d6", "#eb6834", "#1baf7a"];

/** A project's colour: the map's (stable per project), else a fallback by position. */
export const projectColor = (p: DashProject, i: number, mapProjects: MapProject[]) =>
  mapProjects.find((m) => m.id === p.id)?.color ?? FALLBACK_PROJECT[i % FALLBACK_PROJECT.length];
