// New in PaperManager (the desk documents figure strips but has not built them).
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiUrl, fetchFigures } from "../../api/client";
import type { Figure } from "../../types";
import { differingParts } from "./figureStrips";
import "./strip.css";

/** One thumbnail. `url` is null when the source was refused by imageUrl(); `label` overrides the derived one. */
export type StripItem = { src: string; url: string | null; alt: string; label?: string };

type Props = {
  items: StripItem[];
  title?: string;
  /** Lightbox button "beside the chat"; omitted when the page has no preview pane. */
  onOpenBeside?: (url: string, caption: string) => void;
};

const FOCUSABLE = "button:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])";

function Broken({ src }: { src: string }) {
  return (
    <span className="kc-strip-broken" title={src}>
      <span className="kc-figure-broken-label">figure not shown</span>
    </span>
  );
}

function Lightbox({ items, labels, start, onClose, onOpenBeside }: {
  items: StripItem[]; labels: string[]; start: number; onClose: () => void; onOpenBeside?: Props["onOpenBeside"];
}) {
  const [i, setI] = useState(start);
  const [broken, setBroken] = useState<Set<number>>(new Set());
  const box = useRef<HTMLDivElement>(null);
  const last = items.length - 1;
  const go = useCallback((d: number) => setI((v) => Math.min(last, Math.max(0, v + d))), [last]);

  // Keys, focus and scroll: the page behind does not scroll while open, and gets everything back on close.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    box.current?.querySelector<HTMLElement>(".kc-lb-close")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
      else if (e.key === "Tab" && box.current) {
        const f = Array.from(box.current.querySelectorAll<HTMLElement>(FOCUSABLE));
        if (!f.length) return;
        const first = f[0], end = f[f.length - 1];
        const at = document.activeElement;
        if (!box.current.contains(at)) { e.preventDefault(); first.focus(); }
        else if (e.shiftKey && at === first) { e.preventDefault(); end.focus(); }
        else if (!e.shiftKey && at === end) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = prevOverflow;
      opener?.focus?.();
    };
  }, [go, onClose]);

  const it = items[i];
  const caption = it.alt || labels[i];
  return createPortal(
    <div className="kc-lightbox" role="dialog" aria-modal="true" aria-label={caption} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="kc-lb-box" ref={box}>
        <div className="kc-lb-bar">
          <span className="kc-lb-count">{i + 1} / {items.length}</span>
          <span className="kc-lb-spacer" />
          {onOpenBeside && it.url && (
            <button type="button" className="kc-lb-btn" onClick={() => { onOpenBeside(it.url!, caption); onClose(); }}>beside the chat</button>
          )}
          <button type="button" className="kc-lb-btn kc-lb-close" aria-label="Close" onClick={onClose}>close</button>
        </div>
        <div className="kc-lb-stage">
          <button type="button" className="kc-lb-nav prev" aria-label="Previous figure" disabled={i === 0} onClick={() => go(-1)}>‹</button>
          {it.url && !broken.has(i)
            ? <img key={it.url} src={it.url} alt={it.alt} onError={() => setBroken((s) => new Set(s).add(i))} />
            : <Broken src={it.src} />}
          <button type="button" className="kc-lb-nav next" aria-label="Next figure" disabled={i === last} onClick={() => go(1)}>›</button>
        </div>
        <div className="kc-lb-caption">{caption}</div>
      </div>
    </div>,
    document.body,
  );
}

/** Three or more images as one row of thumbnails; a click opens them large with arrows. */
export function FigureStrip({ items, title, onOpenBeside }: Props) {
  const [open, setOpen] = useState<number | null>(null);
  const [broken, setBroken] = useState<Set<number>>(new Set());
  const close = useCallback(() => setOpen(null), []);
  const derived = differingParts(items.map((x) => x.alt));
  const labels = items.map((x, n) => x.label ?? derived[n]);
  return (
    <div className="kc-strip">
      <div className="kc-strip-head">
        <span className="kc-kicker accent">figures</span>
        <span className="kc-strip-count">{items.length}</span>
        {title && <span className="kc-strip-title">{title}</span>}
      </div>
      <div className="kc-strip-row">
        {items.map((x, n) => (
          <div className="kc-strip-cell" key={n}>
            {x.url && !broken.has(n) ? (
              <button type="button" className="kc-strip-thumb" title={x.alt || labels[n]} onClick={() => setOpen(n)}>
                <img src={x.url} alt={x.alt} loading="lazy" onError={() => setBroken((s) => new Set(s).add(n))} />
              </button>
            ) : <Broken src={x.src} />}
            <span className="kc-strip-label" title={x.alt}>{labels[n]}</span>
          </div>
        ))}
      </div>
      {open !== null && items[open] && <Lightbox items={items} labels={labels} start={open} onClose={close} onOpenBeside={onOpenBeside} />}
    </div>
  );
}

/* ------------------------------------------------- all figures of a paper */

const loaded = new Map<string, Promise<Figure[]>>();
function figuresOf(paperId: string): Promise<Figure[]> {
  let p = loaded.get(paperId);
  if (!p) {
    p = fetchFigures(paperId);
    // Kept only while it is useful: a failure or an empty list is asked again next time.
    p.then((f) => { if (!f?.length) loaded.delete(paperId); }, () => loaded.delete(paperId));
    loaded.set(paperId, p);
  }
  return p;
}

const figureLabel = (f: Figure, n: number) => (f.figure_number != null && f.figure_number !== "" ? `Fig. ${f.figure_number}` : `p. ${f.page_number ?? n + 1}`);

/** `![title](/papers/<id>/figures/*)`: every extracted figure of the paper as a strip. */
export function PaperFigureStrip({ paperId, title, toUrl, onOpenBeside }: {
  paperId: string; title?: string; toUrl: (src: string) => string | null; onOpenBeside?: Props["onOpenBeside"];
}) {
  const [state, setState] = useState<{ figures: Figure[] } | { error: string } | null>(null);
  useEffect(() => {
    let live = true;
    setState(null);
    figuresOf(paperId)
      .then((f) => live && setState({ figures: (f ?? []).filter((x) => x.drive_file_id) }))
      .catch((e: unknown) => live && setState({ error: e instanceof Error ? e.message : "could not load" }));
    return () => { live = false; };
  }, [paperId]);

  if (!state) return <div className="kc-strip kc-strip-pending"><span className="kc-kicker accent">figures</span> loading …</div>;
  if ("error" in state) return <div className="kc-strip kc-strip-pending"><span className="kc-kicker accent">figures</span> not available ({state.error})</div>;
  if (!state.figures.length) {
    return <div className="kc-strip kc-strip-pending"><span className="kc-kicker accent">figures</span> {title ? `${title}: ` : ""}no figures extracted for this paper</div>;
  }
  const items: StripItem[] = state.figures.map((f, n) => {
    const src = `/papers/${paperId}/figures/${f.id}/image`;
    return { src, url: toUrl(src) ?? apiUrl(src), alt: f.caption ? `${figureLabel(f, n)}: ${f.caption}` : figureLabel(f, n), label: figureLabel(f, n) };
  });
  return <FigureStrip items={items} title={title} onOpenBeside={onOpenBeside} />;
}
