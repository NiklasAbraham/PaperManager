import { describe, expect, it } from "vitest";
import {
  SpatialGrid, fmt, parseVariant, placeLabels, projectColor, readingSegments, rgba, topicColor, weekLabel, weekTooltip,
} from "./helpers";

describe("parseVariant", () => {
  it("defaults to the strip", () => expect(parseVariant(new URLSearchParams())).toBe("b"));
  it("accepts a, b, c and off, case-insensitively", () => {
    for (const v of ["a", "b", "c", "off"]) expect(parseVariant(new URLSearchParams(`dash=${v}`))).toBe(v);
    expect(parseVariant(new URLSearchParams("dash=A"))).toBe("a");
  });
  it("falls back on anything else", () => expect(parseVariant(new URLSearchParams("dash=zzz"))).toBe("b"));
});

describe("weeks", () => {
  it("formats a calendar date without timezone drift", () => {
    expect(weekLabel("2026-08-24")).toBe("24 Aug");
    expect(weekLabel("2026-01-05")).toBe("5 Jan");
    expect(weekLabel("not a date")).toBe("not a date");
  });
  it("words the tooltip with a plural", () => {
    expect(weekTooltip({ week_start: "2026-11-09", count: 12 })).toBe("Week of 9 Nov · 12 papers");
    expect(weekTooltip({ week_start: "2026-11-02", count: 1 })).toBe("Week of 2 Nov · 1 paper");
  });
});

describe("colours", () => {
  const clusters = [
    { label: "Protein Design", color: "#2a78d6" },
    { label: "Structure Prediction", color: "#eb6834" },
    { label: "LLM", color: "#1baf7a" },
  ];
  it("matches a topic to a cluster by label", () => {
    expect(topicColor("protein design", clusters)).toBe("#2a78d6");
    expect(topicColor("Protein structure prediction", clusters)).toBe("#eb6834");
  });
  it("returns null without a match, for empty names and for too short labels", () => {
    expect(topicColor("Molecular docking", clusters)).toBeNull();
    expect(topicColor("", clusters)).toBeNull();
    expect(topicColor("LLM inference", clusters)).toBeNull();
  });
  it("turns hex into rgba", () => {
    expect(rgba("#7c3aed", 0.5)).toBe("rgba(124,58,237,0.5)");
    expect(rgba("nope", 0.5)).toContain("156,163,175");
  });
  it("takes the map's project colour, else a stable fallback", () => {
    const p = { id: "p1", name: "A", count: 1, read: 0, reading: 0 };
    expect(projectColor(p, 0, [{ id: "p1", name: "A", color: "#123456", count: 1 }])).toBe("#123456");
    expect(projectColor(p, 0, [])).toBe(projectColor(p, 8, []));
  });
});

describe("readingSegments", () => {
  it("gives shares that sum to one and survives an empty library", () => {
    const s = readingSegments({ unread: 50, reading: 25, read: 25 });
    expect(s.map((x) => x.share)).toEqual([0.5, 0.25, 0.25]);
    expect(readingSegments({ unread: 0, reading: 0, read: 0 }).every((x) => x.share === 0)).toBe(true);
  });
});

describe("SpatialGrid", () => {
  const xs = [10, 12, 100, 205, -30], ys = [10, 40, 100, 50, 20];
  const grid = new SpatialGrid(xs, ys, 16);
  it("finds the nearest point within the radius", () => {
    expect(grid.nearest(11, 12, 8)).toBe(0);
    expect(grid.nearest(100, 104, 8)).toBe(2);
  });
  it("returns -1 when nothing is close", () => {
    expect(grid.nearest(150, 150, 8)).toBe(-1);
    expect(grid.nearest(10, 25, 8)).toBe(-1);
  });
  it("works across cell borders and for negative coordinates", () => {
    expect(grid.nearest(15.9, 40, 8)).toBe(1);
    expect(grid.nearest(-27, 20, 8)).toBe(4);
  });
  it("agrees with a brute-force scan", () => {
    let seed = 3;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const px = Array.from({ length: 800 }, () => rnd() * 600), py = Array.from({ length: 800 }, () => rnd() * 300);
    const g = new SpatialGrid(px, py, 16);
    for (let t = 0; t < 200; t++) {
      const x = rnd() * 600, y = rnd() * 300;
      let best = -1, bd = Infinity;
      px.forEach((_, i) => { const d = Math.hypot(px[i] - x, py[i] - y); if (d <= 8 && d < bd) { bd = d; best = i; } });
      expect(g.nearest(x, y, 8)).toBe(best);
    }
  });
  it("prefers a biased (library) dot over a slightly closer reference", () => {
    const g = new SpatialGrid([50, 54], [50, 50], 16, [0, 4]);
    expect(g.nearest(51, 50, 8)).toBe(1);
  });
});

describe("placeLabels", () => {
  const box = (text: string, x: number, y: number, weight: number) => ({ text, x, y, w: 80, h: 14, weight });
  it("keeps the bigger of two overlapping labels", () => {
    const out = placeLabels([box("small", 100, 50, 1), box("big", 110, 52, 9)]);
    expect(out.map((l) => l.text)).toEqual(["big"]);
  });
  it("keeps labels that do not touch", () => {
    expect(placeLabels([box("a", 50, 20, 1), box("b", 200, 20, 2), box("c", 50, 60, 3)])).toHaveLength(3);
  });
  it("counts the padding as part of the collision", () => {
    // edges 2px apart: collides with padding 3, not with 0
    const l = [box("a", 0, 0, 2), box("b", 82, 0, 1)];
    expect(placeLabels(l, 3)).toHaveLength(1);
    expect(placeLabels(l, 0)).toHaveLength(2);
  });
});

describe("fmt", () => {
  it("groups thousands", () => expect(fmt(9462)).toBe("9,462"));
});
