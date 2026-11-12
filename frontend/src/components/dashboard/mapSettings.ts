/** Settings of the full topic-map page: types, defaults, URL round-trip, point colours, legend, export filename. */
import type { MapCluster, MapPoint, MapProject, TopicMapData } from "./api";
import { NEUTRAL, READ_COLORS } from "./helpers";

export type ColorMode = "cluster" | "project" | "year" | "status" | "none";
export const COLOR_MODES: { value: ColorMode; label: string }[] = [
  { value: "cluster", label: "Cluster" },
  { value: "project", label: "Project" },
  { value: "year", label: "Year" },
  { value: "status", label: "Reading status" },
  { value: "none", label: "None" },
];

export interface MapSettings {
  color: ColorMode;
  refs: boolean;
  /** Dot size multiplier. */
  size: number;
  /** Dot opacity multiplier. */
  opacity: number;
  labels: boolean;
  /** Cluster label font size in px. */
  labelSize: number;
  /** Requested number of clusters; null = the backend's default. */
  clusters: number | null;
  /** Checked projects (map project ids). */
  projects: string[];
  yearMin: number | null;
  yearMax: number | null;
  q: string;
}

export const LIMITS = { size: [0.5, 2.5], opacity: [0.2, 1], labelSize: [9, 20], clusters: [4, 16] } as const;

export const DEFAULTS: MapSettings = {
  color: "cluster", refs: true, size: 1, opacity: 1, labels: true, labelSize: 11, clusters: null,
  projects: [], yearMin: null, yearMax: null, q: "",
};

const clamp = (v: number, [lo, hi]: readonly [number, number]) => Math.min(hi, Math.max(lo, v));
const num = (s: string | null): number | null => {
  if (s === null || s.trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
};
const r2 = (n: number) => Math.round(n * 100) / 100;

/** Query string -> settings; anything unknown or out of range falls back to the default (a hand-edited URL never breaks the page). */
export function parseSettings(params: URLSearchParams): MapSettings {
  const c = (params.get("color") ?? "").toLowerCase();
  const color = (COLOR_MODES.some((m) => m.value === c) ? c : DEFAULTS.color) as ColorMode;
  const size = num(params.get("size")), op = num(params.get("op")), ls = num(params.get("ls")), k = num(params.get("k"));
  const y0 = num(params.get("y0")), y1 = num(params.get("y1"));
  const lo = y0 !== null && y1 !== null ? Math.min(y0, y1) : y0, hi = y0 !== null && y1 !== null ? Math.max(y0, y1) : y1;
  return {
    color,
    refs: params.get("refs") !== "0",
    size: size === null ? DEFAULTS.size : r2(clamp(size, LIMITS.size)),
    opacity: op === null ? DEFAULTS.opacity : r2(clamp(op, LIMITS.opacity)),
    labels: params.get("labels") !== "0",
    labelSize: ls === null ? DEFAULTS.labelSize : Math.round(clamp(ls, LIMITS.labelSize)),
    clusters: k === null ? null : Math.round(clamp(k, LIMITS.clusters)),
    projects: (params.get("proj") ?? "").split(",").map((s) => s.trim()).filter(Boolean),
    yearMin: lo === null ? null : Math.round(lo),
    yearMax: hi === null ? null : Math.round(hi),
    q: (params.get("q") ?? "").slice(0, 200),
  };
}

/** Settings -> query string with only the non-default values, so a default view has a clean URL. */
export function settingsToParams(s: MapSettings): URLSearchParams {
  const p = new URLSearchParams();
  if (s.color !== DEFAULTS.color) p.set("color", s.color);
  if (!s.refs) p.set("refs", "0");
  if (s.size !== DEFAULTS.size) p.set("size", String(s.size));
  if (s.opacity !== DEFAULTS.opacity) p.set("op", String(s.opacity));
  if (!s.labels) p.set("labels", "0");
  if (s.labelSize !== DEFAULTS.labelSize) p.set("ls", String(s.labelSize));
  if (s.clusters !== null) p.set("k", String(s.clusters));
  if (s.projects.length) p.set("proj", s.projects.join(","));
  if (s.yearMin !== null) p.set("y0", String(s.yearMin));
  if (s.yearMax !== null) p.set("y1", String(s.yearMax));
  if (s.q.trim()) p.set("q", s.q);
  return p;
}

export const isDefault = (s: MapSettings) => settingsToParams(s).toString() === "";

// ---------------------------------------------------------------------------- colours

/** Sequential year scale: light teal (old) to deep indigo (new). */
const YEAR_STOPS: [number, number, number][] = [[198, 232, 224], [74, 180, 170], [42, 120, 214], [60, 40, 140]];
export function yearColor(t: number): string {
  const x = Math.min(1, Math.max(0, t)) * (YEAR_STOPS.length - 1);
  const i = Math.min(YEAR_STOPS.length - 2, Math.floor(x)), f = x - i;
  const [a, b] = [YEAR_STOPS[i], YEAR_STOPS[i + 1]];
  const h = (k: number) => Math.round(a[k] + (b[k] - a[k]) * f).toString(16).padStart(2, "0");
  return `#${h(0)}${h(1)}${h(2)}`;
}

export const STATUS_LABEL = { unread: "Unread", reading: "Reading", read: "Read" } as const;
export const STATUS_COLORS = { unread: "#b6c0cc", reading: READ_COLORS.reading, read: READ_COLORS.read } as const;
export const MAP_NEUTRAL = "#6b7280";

export interface YearRange { min: number; max: number }

/** Min / max year over the points that have one, or null. */
export function yearExtent(points: Pick<MapPoint, "yr">[]): YearRange | null {
  let min = Infinity, max = -Infinity;
  for (const p of points) if (typeof p.yr === "number") { if (p.yr < min) min = p.yr; if (p.yr > max) max = p.yr; }
  return min <= max ? { min, max } : null;
}

const YEAR_BUCKETS = 12;

/** Colour of every point under a colour mode. Year colours are quantised to a few buckets so the canvas can batch draws. */
export function pointColors(
  pts: MapPoint[], mode: ColorMode, clusters: MapCluster[], projects: MapProject[], checked: string[], range: YearRange | null,
): string[] {
  if (mode === "none") return pts.map(() => MAP_NEUTRAL);
  if (mode === "status") return pts.map((p) => STATUS_COLORS[p.s ?? "unread"]);
  if (mode === "year") {
    return pts.map((p) => {
      if (typeof p.yr !== "number" || !range) return NEUTRAL;
      const t = range.max > range.min ? (p.yr - range.min) / (range.max - range.min) : 1;
      return yearColor(Math.round(t * (YEAR_BUCKETS - 1)) / (YEAR_BUCKETS - 1));
    });
  }
  if (mode === "project") {
    const idx = checked.length ? checked.map((id) => projects.findIndex((q) => q.id === id)).filter((i) => i >= 0) : projects.map((_, i) => i);
    return pts.map((p) => {
      const hit = idx.find((i) => p.p.includes(i));
      return hit === undefined ? NEUTRAL : projects[hit].color;
    });
  }
  const colorOf = new Map(clusters.map((c) => [c.id, c.color]));
  return pts.map((p) => colorOf.get(p.c) ?? NEUTRAL);
}

// ---------------------------------------------------------------------------- legend

export type Legend =
  | { kind: "swatches"; title: string; items: { color: string; label: string; muted?: boolean }[] }
  | { kind: "gradient"; title: string; from: string; to: string; stops: string[]; minLabel: string; maxLabel: string };

export function legendFor(mode: ColorMode, data: TopicMapData, s: Pick<MapSettings, "projects">, range: YearRange | null): Legend | null {
  if (mode === "none") return null;
  if (mode === "cluster") {
    return { kind: "swatches", title: "Clusters",
      items: [...data.clusters].sort((a, b) => b.size - a.size).map((c) => ({ color: c.color, label: c.label, muted: c.muted })) };
  }
  if (mode === "project") {
    const list = s.projects.length ? data.projects.filter((p) => s.projects.includes(p.id)) : data.projects;
    return { kind: "swatches", title: "Projects",
      items: [...list.map((p) => ({ color: p.color, label: p.name })), { color: NEUTRAL, label: "No project", muted: true }] };
  }
  if (mode === "status") {
    return { kind: "swatches", title: "Reading status",
      items: (["unread", "reading", "read"] as const).map((k) => ({ color: STATUS_COLORS[k], label: STATUS_LABEL[k] })) };
  }
  if (!range) return null;
  return { kind: "gradient", title: "Year", from: yearColor(0), to: yearColor(1),
    stops: Array.from({ length: 5 }, (_, i) => yearColor(i / 4)), minLabel: String(range.min), maxLabel: String(range.max) };
}

// ---------------------------------------------------------------------------- filters

/** Points kept by the reference toggle and the year range (a point without a year only survives an open range). */
export function filterPoints(pts: MapPoint[], s: Pick<MapSettings, "refs" | "yearMin" | "yearMax">): MapPoint[] {
  const ranged = s.yearMin !== null || s.yearMax !== null;
  return pts.filter((p) => {
    if (p.r && !s.refs) return false;
    if (!ranged) return true;
    if (typeof p.yr !== "number") return false;
    return (s.yearMin === null || p.yr >= s.yearMin) && (s.yearMax === null || p.yr <= s.yearMax);
  });
}

/** Ids of the points whose title contains every word of the query (case-insensitive); null when the query is empty. */
export function matchingIds(pts: MapPoint[], q: string): Set<string> | null {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  const out = new Set<string>();
  for (const p of pts) {
    const t = p.t.toLowerCase();
    if (words.every((w) => t.includes(w))) out.add(p.id);
  }
  return out;
}

export function exportFilename(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `topic-map-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}.png`;
}
