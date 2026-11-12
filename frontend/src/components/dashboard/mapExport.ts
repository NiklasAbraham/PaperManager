/** PNG export of the topic map: the current view (painted by TopicMap) on a white page with a title and the legend. */
import type { Legend } from "./mapSettings";
import { exportFilename } from "./mapSettings";

export type Painter = (g: CanvasRenderingContext2D) => void;

export interface ExportOptions {
  /** Paints the map at its on-screen size (width x height logical px); the scale is already applied to `g`. */
  paint: Painter;
  width: number;
  height: number;
  /** 2 or 4: output pixels per logical px. */
  scale: number;
  legend: Legend | null;
  date?: Date;
  /** Overridable for tests (jsdom has no canvas). */
  createCanvas?: () => HTMLCanvasElement;
}

const FONT = "system-ui, 'Segoe UI', Roboto, sans-serif";
const M = 20, TITLE_H = 40, ROW_H = 18, SWATCH = 9;

export const exportTitle = (d: Date) => `PaperManager · Topic map · ${exportFilename(d).slice(10, 20)}`;

/** Lays the swatch legend out in rows of at most `maxW`; returns rows of {x, item} and the block height. */
export function layoutLegend(g: CanvasRenderingContext2D, legend: Legend | null, maxW: number) {
  if (!legend) return { rows: [] as { x: number; i: number; w: number }[][], height: 0 };
  if (legend.kind === "gradient") return { rows: [], height: 40 };
  g.font = `11px ${FONT}`;
  const rows: { x: number; i: number; w: number }[][] = [[]];
  let x = 0;
  legend.items.forEach((it, i) => {
    const w = SWATCH + 6 + g.measureText(it.label).width + 16;
    if (x + w > maxW && rows[rows.length - 1].length) { rows.push([]); x = 0; }
    rows[rows.length - 1].push({ x, i, w });
    x += w;
  });
  return { rows, height: 20 + rows.length * ROW_H };
}

/** The finished export canvas: white background, title, the map, the legend. */
export function renderExport(o: ExportOptions): HTMLCanvasElement {
  const date = o.date ?? new Date();
  const mk = o.createCanvas ?? (() => document.createElement("canvas"));
  const probe = mk().getContext("2d");
  const inner = o.width;
  const lay = probe ? layoutLegend(probe, o.legend, inner) : { rows: [], height: 0 };
  const W = inner + 2 * M, H = M + TITLE_H + o.height + (lay.height ? lay.height + 8 : 0) + M;
  const cv = mk();
  cv.width = Math.round(W * o.scale); cv.height = Math.round(H * o.scale);
  const g = cv.getContext("2d");
  if (!g) throw new Error("Canvas is not available");
  g.setTransform(o.scale, 0, 0, o.scale, 0, 0);
  g.fillStyle = "#ffffff"; g.fillRect(0, 0, W, H);
  g.textBaseline = "alphabetic"; g.textAlign = "left";
  g.fillStyle = "#111827"; g.font = `600 15px ${FONT}`;
  g.fillText(exportTitle(date), M, M + 16);
  // the map, clipped to its frame
  g.save();
  g.translate(M, M + TITLE_H);
  g.beginPath(); g.rect(0, 0, o.width, o.height); g.clip();
  o.paint(g);
  g.restore();
  g.strokeStyle = "#e5e7eb"; g.lineWidth = 1;
  g.strokeRect(M + 0.5, M + TITLE_H + 0.5, o.width - 1, o.height - 1);
  // legend
  if (o.legend) {
    const y0 = M + TITLE_H + o.height + 8;
    g.fillStyle = "#6b7280"; g.font = `600 10px ${FONT}`;
    g.fillText(o.legend.title.toUpperCase(), M, y0 + 12);
    if (o.legend.kind === "gradient") {
      const gw = Math.min(260, o.width - 80), gx = M, gy = y0 + 18;
      const grad = g.createLinearGradient(gx, 0, gx + gw, 0);
      o.legend.stops.forEach((c, i, a) => grad.addColorStop(i / (a.length - 1), c));
      g.fillStyle = grad; g.fillRect(gx, gy, gw, 8);
      g.fillStyle = "#4b5563"; g.font = `11px ${FONT}`;
      g.fillText(o.legend.minLabel, gx, gy + 22);
      g.textAlign = "right"; g.fillText(o.legend.maxLabel, gx + gw, gy + 22); g.textAlign = "left";
    } else {
      const items = o.legend.items;
      lay.rows.forEach((row, ri) => {
        const y = y0 + 20 + ri * ROW_H;
        for (const c of row) {
          const it = items[c.i];
          g.beginPath(); g.arc(M + c.x + SWATCH / 2, y + 5, SWATCH / 2, 0, 6.2832);
          g.fillStyle = it.color; g.fill();
          g.fillStyle = it.muted ? "#9ca3af" : "#374151"; g.font = `11px ${FONT}`;
          g.fillText(it.label, M + c.x + SWATCH + 6, y + 9);
        }
      });
    }
  }
  return cv;
}

function toBlob(cv: HTMLCanvasElement): Promise<Blob> {
  return new Promise((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error("PNG encoding failed"))), "image/png"));
}

/** Renders and downloads `topic-map-YYYY-MM-DD.png`. */
export async function downloadPng(o: ExportOptions): Promise<string> {
  const cv = renderExport(o);
  const blob = await toBlob(cv);
  const name = exportFilename(o.date ?? new Date());
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return name;
}

export const canCopyImage = () =>
  typeof navigator !== "undefined" && !!navigator.clipboard && typeof ClipboardItem !== "undefined";

/** Copies the export to the clipboard as a PNG (needs a secure context and ClipboardItem). */
export async function copyPng(o: ExportOptions): Promise<void> {
  const cv = renderExport(o);
  await navigator.clipboard.write([new ClipboardItem({ "image/png": toBlob(cv) })]);
}
