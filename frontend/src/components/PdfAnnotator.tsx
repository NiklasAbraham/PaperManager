import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Viewer, Worker, SpecialZoomLevel } from "@react-pdf-viewer/core";
import { highlightPlugin, Trigger } from "@react-pdf-viewer/highlight";
import type {
  HighlightArea,
  RenderHighlightTargetProps,
  RenderHighlightsProps,
} from "@react-pdf-viewer/highlight";
import "@react-pdf-viewer/core/lib/styles/index.css";
import "@react-pdf-viewer/highlight/lib/styles/index.css";

import type { Annotation, AnnotationColor } from "../types";
import {
  listAnnotations,
  createAnnotation,
  updateAnnotation,
  deleteAnnotation,
} from "../api/client";

// ── Constants ──────────────────────────────────────────────────────────────────

const COLOR_OPTIONS: AnnotationColor[] = ["yellow", "green", "blue", "red", "purple"];

const COLOR_BG: Record<AnnotationColor, string> = {
  yellow: "rgba(255, 235, 0, 0.45)",
  green: "rgba(0, 200, 80, 0.35)",
  blue: "rgba(56, 132, 255, 0.35)",
  red: "rgba(255, 60, 60, 0.4)",
  purple: "rgba(160, 32, 240, 0.35)",
};

const COLOR_SWATCH: Record<AnnotationColor, string> = {
  yellow: "#f5e800",
  green: "#00c850",
  blue: "#3884ff",
  red: "#ff3c3c",
  purple: "#a020f0",
};

// ── Types ──────────────────────────────────────────────────────────────────────

interface Props {
  paperId: string;
  pdfUrl: string;
  /** Called whenever highlights are created, updated, or deleted */
  onHighlightsChange?: (highlights: Annotation[]) => void;
  /** Zoom scale (0–2 as a fraction, e.g. 1 = 100%). Changing this remounts the viewer. */
  scale?: number | SpecialZoomLevel;
  /** Called with the resolved numeric scale after the viewer applies a SpecialZoomLevel */
  onScaleResolved?: (scale: number) => void;
  /** Initial page to show (0-indexed). Used when the component first mounts. */
  initialPage?: number;
}

interface TooltipPos {
  x: number;
  y: number;
}

export interface PdfAnnotatorHandle {
  jumpToPage: (pageIndex: number) => void;
}

// ── Component ──────────────────────────────────────────────────────────────────

const PdfAnnotator = forwardRef<PdfAnnotatorHandle, Props>(function PdfAnnotator({ paperId, pdfUrl, onHighlightsChange, onScaleResolved, scale = SpecialZoomLevel.PageWidth, initialPage = 0 }, ref) {
  const [highlights, setHighlights] = useState<Annotation[]>([]);
  const [activeAnnotation, setActiveAnnotation] = useState<Annotation | null>(null);
  const [tooltipPos, setTooltipPos] = useState<TooltipPos | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Track the current page so we can restore position on zoom remounts
  const [currentPage, setCurrentPage] = useState(initialPage);
  // The page to pass as initialPage on the next Viewer mount
  const [viewerInitialPage, setViewerInitialPage] = useState(initialPage);

  // Remount viewer when scale changes, preserving the current page position
  const [viewerKey, setViewerKey] = useState(0);
  const prevScale = useRef(scale);
  if (prevScale.current !== scale) {
    prevScale.current = scale;
    setViewerInitialPage(currentPage);
    setViewerKey((k) => k + 1);
  }

  useImperativeHandle(ref, () => ({
    jumpToPage(pageIndex: number) {
      setViewerInitialPage(pageIndex);
      setViewerKey((k) => k + 1);
    },
  }));

  // Load annotations on mount
  useEffect(() => {
    listAnnotations(paperId).then(setHighlights).catch(console.error);
  }, [paperId]);

  // Close tooltip on outside click
  useEffect(() => {
    if (!activeAnnotation) return;
    function handleOutside(e: MouseEvent) {
      if (tooltipRef.current && !tooltipRef.current.contains(e.target as Node)) {
        setActiveAnnotation(null);
        setTooltipPos(null);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [activeAnnotation]);

  // ── Highlight plugin ──────────────────────────────────────────────────────

  const renderHighlightTarget = (props: RenderHighlightTargetProps) => (
    <div
      style={{
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
        display: "flex",
        gap: 6,
        padding: "6px 8px",
        position: "absolute",
        left: `${props.selectionRegion.left}%`,
        top: `${props.selectionRegion.top + props.selectionRegion.height}%`,
        zIndex: 10,
        transform: "translateY(4px)",
      }}
    >
      {COLOR_OPTIONS.map((color) => (
        <button
          key={color}
          title={color}
          style={{
            background: COLOR_SWATCH[color],
            border: "2px solid rgba(0,0,0,0.15)",
            borderRadius: "50%",
            cursor: "pointer",
            height: 22,
            width: 22,
            flexShrink: 0,
          }}
          onClick={async () => {
            try {
              const saved = await createAnnotation(paperId, {
                page_number: props.highlightAreas[0]?.pageIndex ?? 0,
                highlighted_text: props.selectedText,
                color,
                note: "",
                position_json: JSON.stringify(props.highlightAreas),
              });
              setHighlights((prev) => [...prev, saved]);
            } catch (err) {
              console.error("Failed to save annotation", err);
            } finally {
              props.cancel();
            }
          }}
        />
      ))}
    </div>
  );

  const renderHighlights = (props: RenderHighlightsProps) => (
    <>
      {highlights
        .filter((ann) => {
          const areas: HighlightArea[] = JSON.parse(ann.position_json);
          return areas.some((a) => a.pageIndex === props.pageIndex);
        })
        .map((ann) => {
          const areas: HighlightArea[] = JSON.parse(ann.position_json);
          return areas
            .filter((area) => area.pageIndex === props.pageIndex)
            .map((area, idx) => (
              <React.Fragment key={`${ann.id}-${idx}`}>
                {/* Color overlay — pointer-events none so text is still selectable */}
                <div
                  style={{
                    ...props.getCssProperties(area, props.rotation),
                    background: COLOR_BG[ann.color as AnnotationColor] ?? COLOR_BG.yellow,
                    position: "absolute",
                    pointerEvents: "none",
                    mixBlendMode: "multiply",
                  }}
                />
                {/* Invisible click target on top */}
                <div
                  style={{
                    ...props.getCssProperties(area, props.rotation),
                    background: "transparent",
                    cursor: "pointer",
                    position: "absolute",
                    zIndex: 2,
                  }}
                  onClick={(e) => {
                    const rect = (e.currentTarget as HTMLElement)
                      .closest(".rpv-core__page-layer")
                      ?.getBoundingClientRect();
                    const x = Math.min(e.clientX, window.innerWidth - 300);
                    const y = Math.min(e.clientY + 8, window.innerHeight - 320);
                    setActiveAnnotation(ann);
                    setNoteDraft(ann.note);
                    setTooltipPos({ x, y });
                    void rect; // suppress unused
                  }}
                />
              </React.Fragment>
            ));
        })}
    </>
  );

  const plugin = highlightPlugin({
    renderHighlightTarget,
    renderHighlightContent: () => <></>,
    renderHighlights,
    trigger: Trigger.TextSelection,
  });

  // ── Tooltip actions ────────────────────────────────────────────────────────

  async function handleSaveNote() {
    if (!activeAnnotation) return;
    setSaving(true);
    try {
      const updated = await updateAnnotation(paperId, activeAnnotation.id, {
        note: noteDraft,
      });
      setHighlights((prev) =>
        prev.map((h) => (h.id === updated.id ? updated : h))
      );
      setActiveAnnotation(updated);
    } catch (err) {
      console.error("Failed to update note", err);
    } finally {
      setSaving(false);
    }
  }

  async function handleChangeColor(color: AnnotationColor) {
    if (!activeAnnotation) return;
    try {
      const updated = await updateAnnotation(paperId, activeAnnotation.id, { color });
      setHighlights((prev) =>
        prev.map((h) => (h.id === updated.id ? updated : h))
      );
      setActiveAnnotation(updated);
    } catch (err) {
      console.error("Failed to update color", err);
    }
  }

  async function handleDelete() {
    if (!activeAnnotation) return;
    try {
      await deleteAnnotation(paperId, activeAnnotation.id);
      setHighlights((prev) => prev.filter((h) => h.id !== activeAnnotation.id));
      setActiveAnnotation(null);
      setTooltipPos(null);
    } catch (err) {
      console.error("Failed to delete annotation", err);
    }
  }

  // Notify parent when highlights change
  useEffect(() => {
    onHighlightsChange?.(highlights);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlights]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div ref={containerRef} className="flex-1 relative overflow-auto">
        <Worker workerUrl="/pdf.worker.min.js">
          <Viewer
            key={viewerKey}
            fileUrl={pdfUrl}
            defaultScale={scale}
            initialPage={viewerInitialPage}
            plugins={[plugin]}
            onPageChange={(e) => setCurrentPage(e.currentPage)}
            onDocumentLoad={(e) => {
              // Only resolve the fit scale when the scale is a SpecialZoomLevel.
              // For numeric zoom steps the viewer remounts too, but we must NOT
              // overwrite resolvedScale.current back to the fit value.
              if (typeof scale !== "number") {
                e.doc.getPage(0).then((page) => {
                  const pdfPageWidth = page.getViewport({ scale: 1 }).width;
                  requestAnimationFrame(() => {
                    const scroller = containerRef.current?.querySelector(".rpv-core__inner-pages") as HTMLElement | null;
                    const w = scroller?.clientWidth ?? containerRef.current?.clientWidth ?? 0;
                    if (w > 0 && pdfPageWidth > 0) {
                      onScaleResolved?.(w / pdfPageWidth);
                    }
                  });
                });
              }
            }}
          />
        </Worker>

      {/* Annotation tooltip */}
      {activeAnnotation && tooltipPos && (
        <div
          ref={tooltipRef}
          style={{
            position: "fixed",
            top: tooltipPos.y,
            left: tooltipPos.x,
            zIndex: 9999,
            width: 288,
          }}
          className="bg-white rounded-xl shadow-2xl border border-gray-200 p-4 flex flex-col gap-3"
        >
          {/* Header */}
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs text-gray-500 italic line-clamp-3 flex-1">
              "{activeAnnotation.highlighted_text}"
            </p>
            <button
              onClick={() => { setActiveAnnotation(null); setTooltipPos(null); }}
              className="text-gray-400 hover:text-gray-600 text-sm leading-none flex-shrink-0"
            >
              ✕
            </button>
          </div>

          {/* Color swatches */}
          <div className="flex gap-2">
            {COLOR_OPTIONS.map((c) => (
              <button
                key={c}
                title={c}
                onClick={() => handleChangeColor(c)}
                style={{ background: COLOR_SWATCH[c] }}
                className={`w-5 h-5 rounded-full border-2 transition-transform ${
                  activeAnnotation.color === c
                    ? "border-gray-700 scale-110"
                    : "border-transparent hover:scale-105"
                }`}
              />
            ))}
          </div>

          {/* Note textarea */}
          <textarea
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            placeholder="Add a note…"
            rows={3}
            className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
          />

          {/* Actions */}
          <div className="flex gap-2">
            <button
              onClick={handleSaveNote}
              disabled={saving}
              className="flex-1 text-xs bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg py-1.5 font-medium"
            >
              {saving ? "Saving…" : "Save note"}
            </button>
            <button
              onClick={handleDelete}
              className="text-xs text-red-500 hover:text-red-700 px-2 py-1.5 rounded-lg hover:bg-red-50"
            >
              Delete
            </button>
          </div>
        </div>
      )}
      </div>
    </div>
  );
});

export default PdfAnnotator;
