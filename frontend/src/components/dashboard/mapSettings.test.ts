import { describe, expect, it, vi } from "vitest";
import { DEFAULTS, exportFilename, filterPoints, isDefault, matchingIds, parseSettings, pointColors, settingsToParams, yearExtent } from "./mapSettings";
import { exportTitle, renderExport } from "./mapExport";
import type { MapPoint } from "./api";

const q = (s: string) => new URLSearchParams(s);
const pt = (id: string, o: Partial<MapPoint> = {}): MapPoint => ({ id, x: 0, y: 0, c: 0, t: `Title ${id}`, r: 0, p: [], topic: null, ...o });

describe("URL state", () => {
  it("empty query gives the defaults and the defaults give an empty query", () => {
    expect(parseSettings(q(""))).toEqual(DEFAULTS);
    expect(settingsToParams(DEFAULTS).toString()).toBe("");
    expect(isDefault(DEFAULTS)).toBe(true);
  });

  it("round-trips every setting", () => {
    const s = { color: "year" as const, refs: false, size: 1.5, opacity: 0.6, labels: false, labelSize: 14, clusters: 9,
      projects: ["a", "b"], yearMin: 2018, yearMax: 2024, q: "diffusion models" };
    const back = parseSettings(settingsToParams(s));
    expect(back).toEqual(s);
  });

  it("clamps and ignores garbage", () => {
    const s = parseSettings(q("color=rainbow&size=99&op=-3&ls=abc&k=100&y0=2030&y1=2010&refs=0"));
    expect(s.color).toBe("cluster");
    expect(s.size).toBe(2.5);
    expect(s.opacity).toBe(0.2);
    expect(s.labelSize).toBe(11);
    expect(s.clusters).toBe(16);
    expect([s.yearMin, s.yearMax]).toEqual([2010, 2030]);
    expect(s.refs).toBe(false);
  });
});

describe("filters and colours", () => {
  const pts = [pt("a", { yr: 2019, s: "read" }), pt("b", { yr: 2024 }), pt("c", { r: 1, yr: 2021 }), pt("d")];
  it("filters references and years", () => {
    expect(filterPoints(pts, DEFAULTS).length).toBe(4);
    expect(filterPoints(pts, { ...DEFAULTS, refs: false }).map((p) => p.id)).toEqual(["a", "b", "d"]);
    expect(filterPoints(pts, { ...DEFAULTS, yearMin: 2020 }).map((p) => p.id)).toEqual(["b", "c"]);
  });
  it("search matches every word, case-insensitively", () => {
    expect([...matchingIds(pts, "title A")!]).toEqual(["a"]);
    expect(matchingIds(pts, "  ")).toBeNull();
  });
  it("colours by status and year", () => {
    expect(pointColors(pts, "status", [], [], [], null)[0]).not.toBe(pointColors(pts, "status", [], [], [], null)[1]);
    const ext = yearExtent(pts)!;
    expect(ext).toEqual({ min: 2019, max: 2024 });
    const c = pointColors(pts, "year", [], [], [], ext);
    expect(c[0]).not.toBe(c[1]);
  });
});

describe("export", () => {
  it("names the file topic-map-YYYY-MM-DD.png", () => {
    expect(exportFilename(new Date(2026, 10, 5))).toBe("topic-map-2026-11-05.png");
    expect(exportTitle(new Date(2026, 10, 5))).toBe("PaperManager · Topic map · 2026-11-05");
  });

  it("paints white background, title, the map and the legend at the requested scale", () => {
    const calls: string[] = [];
    const g = new Proxy({} as Record<string, unknown>, {
      get: (_t, k: string) => k === "measureText" ? () => ({ width: 40 }) : (...a: unknown[]) => { calls.push(k + (k === "fillText" ? `:${a[0]}` : "")); },
      set: () => true,
    });
    const canvases: { width: number; height: number }[] = [];
    const createCanvas = () => { const c = { width: 0, height: 0, getContext: () => g }; canvases.push(c); return c as unknown as HTMLCanvasElement; };
    const paint = vi.fn();
    renderExport({ paint, width: 800, height: 500, scale: 4, date: new Date(2026, 10, 5), createCanvas,
      legend: { kind: "swatches", title: "Clusters", items: [{ color: "#fff", label: "Alpha" }] } });
    expect(paint).toHaveBeenCalledTimes(1);
    const out = canvases[canvases.length - 1];
    expect(out.width).toBe((800 + 40) * 4);
    expect(calls).toContain("fillRect");
    expect(calls).toContain("fillText:PaperManager · Topic map · 2026-11-05");
    expect(calls).toContain("fillText:Alpha");
  });
});
